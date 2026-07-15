"""
schema_context.py
------------------
Descripción del esquema de GastosRRHH. Es la ÚNICA fuente de verdad:
- gemini_client.py la usa para que el modelo sepa qué tablas/columnas existen.
- sql_validator.py la usa como whitelist para rechazar cualquier SQL que
  toque algo fuera de este esquema.

Si en algún momento agregás una tabla o columna nueva, se actualiza acá y
ambos lados quedan sincronizados automáticamente.
"""

# tabla -> set de columnas permitidas
ALLOWED_SCHEMA = {
    "conceptos": {"cod_concepto", "concepto", "iva"},
    "departamentos": {"cod_dpto", "jornada", "nombre_dpto", "plazo_pago", "extra"},
    "empleados": {
        "cod_empleado", "nombre", "apellidos", "fecha_incorporacion",
        "cod_dpto", "jornada", "tipo_contrato", "sexo", "casado",
        "fecha_nacimiento", "nif",
    },
    "gastos": {
        "num_gasto", "cod_concepto", "cod_empleado", "fecha_gasto",
        "importe", "pagado", "fecha_pagado",
    },
}

ALLOWED_TABLES = set(ALLOWED_SCHEMA.keys())

# Descripción en lenguaje natural + DDL simplificado para el prompt de Gemini.
# Incluye las relaciones (FKs) para que el modelo arme los JOIN correctos,
# y aclara la particularidad del esquema copo de nieve (clave compuesta).
SCHEMA_DESCRIPTION_FOR_LLM = """
Esquema de base de datos "GastosRRHH" (SQL Server, esquema dbo):

TABLA conceptos
  - cod_concepto INT (PK)
  - concepto NVARCHAR      -- ej: ALOJAMIENTO, COMIDA, DESPLAZAMIENTO, MATERIAL
  - iva DECIMAL

TABLA departamentos
  - cod_dpto INT
  - jornada NVARCHAR        -- MAÑANA, TARDE o COMPLETA
  - nombre_dpto NVARCHAR    -- ej: ADMINISTRACION, RRHH, CONTABILIDAD, COMERCIAL
  - plazo_pago INT          -- días de plazo de pago para esa combinación depto+jornada
  - extra DECIMAL
  PK compuesta: (cod_dpto, jornada) -- IMPORTANTE: cada departamento tiene
  una fila distinta por cada jornada, con su propio plazo_pago y extra.

TABLA empleados
  - cod_empleado VARCHAR (PK)
  - nombre NVARCHAR
  - apellidos NVARCHAR
  - fecha_incorporacion DATE
  - cod_dpto INT
  - jornada NVARCHAR
  - tipo_contrato NVARCHAR  -- INDEFINIDO, TEMPORAL, PRACTICAS
  - sexo NVARCHAR           -- HOMBRE, MUJER
  - casado BIT
  - fecha_nacimiento DATE (puede ser NULL)
  - nif VARCHAR (puede ser NULL)
  FK compuesta (cod_dpto, jornada) -> departamentos (cod_dpto, jornada)
  IMPORTANTE: para unir empleados con departamentos hay que hacer JOIN por
  AMBAS columnas (cod_dpto Y jornada), nunca solo por cod_dpto.

TABLA gastos
  - num_gasto INT (PK)
  - cod_concepto INT -> FK a conceptos.cod_concepto
  - cod_empleado VARCHAR -> FK a empleados.cod_empleado
  - fecha_gasto DATE
  - importe DECIMAL
  - pagado BIT             -- 1 = pagado, 0 = pendiente
  - fecha_pagado DATE (NULL si pagado = 0)

Reglas para generar SQL:
- Usar SIEMPRE nombres de tabla y columna en minúscula, tal como aparecen arriba.
- Para unir empleados con departamentos, el JOIN debe incluir cod_dpto Y jornada.
- Nunca inventar columnas o tablas que no estén en esta lista.
- Si la pregunta no especifica un límite de filas y podría devolver muchas,
  agregar TOP 100.
- Responder ÚNICAMENTE con la sentencia SQL, sin explicaciones, sin
  comentarios, sin backticks de markdown, sin punto y coma al final.
""".strip()
