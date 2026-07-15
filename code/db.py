"""
db.py
-----
Ejecuta el SQL ya validado contra SQL Server. Debe conectarse SIEMPRE con
el usuario de solo lectura creado en 00_crear_usuario_readonly.sql, nunca
con un usuario admin — el validador es la primera capa de defensa, este
usuario de base de datos es la segunda, independiente de la primera.
"""

import os
import pyodbc

QUERY_TIMEOUT_SECONDS = 10
HARD_ROW_CAP = 500  # última red de seguridad, incluso si algo raro pasa antes


def get_connection():
    server = os.environ["SQL_SERVER"]
    database = os.environ["SQL_DATABASE"]
    driver = os.environ.get("SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    user = os.environ["SQL_READONLY_USER"]
    password = os.environ["SQL_READONLY_PASSWORD"]

    conn_str = (
        f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
        f"UID={user};PWD={password};TrustServerCertificate=yes;"
    )
    conn = pyodbc.connect(conn_str, timeout=5)
    conn.timeout = QUERY_TIMEOUT_SECONDS
    return conn


def run_readonly_query(sql: str) -> list[dict]:
    """
    Ejecuta el SQL (ya pasado por sql_validator.validate_and_prepare) y
    devuelve las filas como lista de dicts. Se asume que sql ya es un
    SELECT validado; esta función no vuelve a validar nada, esa
    responsabilidad es de sql_validator.py.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)

        columnas = [col[0] for col in cursor.description]
        filas = []
        for row in cursor.fetchmany(HARD_ROW_CAP):
            filas.append(dict(zip(columnas, row)))

        return filas
    finally:
        conn.close()
