"""
migrate_excel_to_sql.py
------------------------
Migra el Excel origen (4 hojas: GASTOS, EMPLEADOS, DEPARTAMENTOS, CONCEPTOS)
al esquema copo de nieve creado por 01_crear_esquema.sql en SQL Server.

Uso:
    1. Ejecutar 01_crear_esquema.sql en SQL Server (una sola vez).
    2. cp .env.example .env  y completar los datos de conexión.
    3. pip install -r requirements.txt
    4. python migrate_excel_to_sql.py

Diseño:
    - Idempotente: si la tabla destino ya tiene filas, las trunca antes de
      reinsertar (evita duplicados si se corre dos veces).
    - Inserta en orden de dependencias FK: Conceptos -> Departamentos ->
      Empleados -> Gastos.
    - Válida conteos de filas leídas vs. insertadas al final de cada tabla.
    - Usa fast_executemany de pyodbc vía SQLAlchemy para insertar los
      ~50.000 registros de Gastos en segundos, no minutos.
"""

import os
import sys
import logging
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("migrate")

load_dotenv()


# ------------------------------------------------------------------
# Conexión
# ------------------------------------------------------------------
def build_engine():
    server = os.environ["SQL_SERVER"]
    database = os.environ["SQL_DATABASE"]
    driver = os.environ.get("SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    trusted = os.environ.get("SQL_TRUSTED_CONNECTION", "yes").lower() == "yes"

    driver_param = driver.replace(" ", "+")

    if trusted:
        conn_str = (
            f"mssql+pyodbc://@{server}/{database}"
            f"?driver={driver_param}&trusted_connection=yes"
            f"&TrustServerCertificate=yes"
        )
    else:
        user = os.environ["SQL_USER"]
        password = os.environ["SQL_PASSWORD"]
        conn_str = (
            f"mssql+pyodbc://{user}:{password}@{server}/{database}"
            f"?driver={driver_param}&TrustServerCertificate=yes"
        )

    # fast_executemany acelera muchísimo los inserts masivos (Gastos: ~50k filas)
    engine = create_engine(conn_str, fast_executemany=True)
    return engine


# ------------------------------------------------------------------
# Lectura y limpieza del Excel
# ------------------------------------------------------------------
def read_excel_sheets(path: str) -> dict:
    log.info("Leyendo Excel: %s", path)
    xls = pd.ExcelFile(path)
    sheets = {name: xls.parse(name) for name in xls.sheet_names}
    for name, df in sheets.items():
        log.info("  Hoja '%s': %d filas, %d columnas", name, len(df), len(df.columns))
    return sheets


def clean_conceptos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        "Cod Concepto": "cod_concepto",
        "Concepto": "concepto",
        "IVA": "iva",
    })
    df["iva"] = df["iva"].round(4)
    return df[["cod_concepto", "concepto", "iva"]]


def clean_departamentos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        "Cod Dpto": "cod_dpto",
        "Nombre Dpto": "nombre_dpto",
        "JORNADA": "jornada",
        "PLAZO PAGO": "plazo_pago",
        "EXTRA": "extra",
    })
    df["extra"] = df["extra"].round(4)
    return df[["cod_dpto", "jornada", "nombre_dpto", "plazo_pago", "extra"]]


def clean_empleados(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        "Cod Empleado": "cod_empleado",
        "Nombre": "nombre",
        "Apellidos": "apellidos",
        "Fecha Incorporación": "fecha_incorporacion",
        "Departamento": "cod_dpto",
        "Tipo Contrato": "tipo_contrato",
        "Sexo": "sexo",
        "Casado": "casado",
        "Jornada": "jornada",
        "Fecha Nacimiento": "fecha_nacimiento",
        "NIF": "nif",
    })
    df["casado"] = df["casado"].astype(bool)
    # NaT / NaN se mantienen como NULL: fecha_nacimiento y nif son nullable
    df["nif"] = df["nif"].where(df["nif"].notna(), None)
    return df[[
        "cod_empleado", "nombre", "apellidos", "fecha_incorporacion",
        "cod_dpto", "jornada", "tipo_contrato", "sexo", "casado",
        "fecha_nacimiento", "nif",
    ]]


def clean_gastos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        "Num Gasto": "num_gasto",
        "Concepto": "cod_concepto",
        "Empleado": "cod_empleado",
        "Fecha Gasto": "fecha_gasto",
        "Importe": "importe",
        "Pagado": "pagado",
        "Fecha Pagado": "fecha_pagado",
    })
    df["pagado"] = df["pagado"].str.strip().str.upper().eq("SI")
    df["importe"] = df["importe"].round(4)
    # fecha_pagado debe ser NULL si aún no está pagado, aunque el Excel
    # traiga alguna fecha residual por error de captura
    df.loc[~df["pagado"], "fecha_pagado"] = pd.NaT
    return df[[
        "num_gasto", "cod_concepto", "cod_empleado", "fecha_gasto",
        "importe", "pagado", "fecha_pagado",
    ]]


# ------------------------------------------------------------------
# Validaciones antes de insertar (defensa en profundidad, mismo
# principio que tools.py::_validate_* en NetOps AI)
# ------------------------------------------------------------------
def validate_referential_integrity(gastos, empleados, departamentos, conceptos):
    errores = []

    empleados_validos = set(empleados["cod_empleado"])
    conceptos_validos = set(conceptos["cod_concepto"])
    deptos_validos = set(zip(departamentos["cod_dpto"], departamentos["jornada"]))
    emp_deptos_validos = set(zip(empleados["cod_dpto"], empleados["jornada"]))

    huerfanos_emp = set(gastos["cod_empleado"]) - empleados_validos
    if huerfanos_emp:
        errores.append(f"{len(huerfanos_emp)} gasto(s) referencian empleados inexistentes: {list(huerfanos_emp)[:5]}")

    huerfanos_concepto = set(gastos["cod_concepto"]) - conceptos_validos
    if huerfanos_concepto:
        errores.append(f"{len(huerfanos_concepto)} gasto(s) referencian conceptos inexistentes: {list(huerfanos_concepto)[:5]}")

    huerfanos_depto = emp_deptos_validos - deptos_validos
    if huerfanos_depto:
        errores.append(f"{len(huerfanos_depto)} empleado(s) referencian (departamento, jornada) inexistentes: {list(huerfanos_depto)[:5]}")

    if errores:
        for e in errores:
            log.error(e)
        raise ValueError("Validación de integridad referencial falló. Revisa el Excel origen antes de migrar.")

    log.info("Validación de integridad referencial: OK")


# ------------------------------------------------------------------
# Carga a SQL Server
# ------------------------------------------------------------------
def load_table(engine, df: pd.DataFrame, table_name: str):
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM dbo.{table_name}"))

    df.to_sql(
        table_name,
        con=engine,
        schema="dbo",
        if_exists="append",
        index=False,
        chunksize=1000,
        method=None,  # fast_executemany del engine ya optimiza el insert
    )

    with engine.begin() as conn:
        count = conn.execute(text(f"SELECT COUNT(*) FROM dbo.{table_name}")).scalar()

    if count != len(df):
        raise RuntimeError(
            f"{table_name}: se leyeron {len(df)} filas del Excel pero SQL Server "
            f"quedó con {count}. Migración inconsistente, revisar antes de continuar."
        )
    log.info("  -> %s: %d filas insertadas y verificadas", table_name, count)


def main():
    excel_path = os.environ.get("EXCEL_PATH", "./12_MODELO_DATOS_GASTOS_COPO_DE_NIEVE.xlsx")
    if not Path(excel_path).exists():
        log.error("No se encontró el archivo: %s", excel_path)
        sys.exit(1)

    sheets = read_excel_sheets(excel_path)

    conceptos = clean_conceptos(sheets["CONCEPTOS"])
    departamentos = clean_departamentos(sheets["DEPARTAMENTOS"])
    empleados = clean_empleados(sheets["EMPLEADOS"])
    gastos = clean_gastos(sheets["GASTOS"])

    log.info("Validando integridad referencial antes de tocar SQL Server...")
    validate_referential_integrity(gastos, empleados, departamentos, conceptos)

    engine = build_engine()
    log.info("Conectado a SQL Server. Insertando en orden de dependencias FK...")

    # Orden obligatorio: padres antes que hijos
    load_table(engine, conceptos, "Conceptos")
    load_table(engine, departamentos, "Departamentos")
    load_table(engine, empleados, "Empleados")
    load_table(engine, gastos, "Gastos")

    log.info("Migración completada sin errores.")


if __name__ == "__main__":
    main()
