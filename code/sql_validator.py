"""
sql_validator.py
----------------
Defensa en profundidad para el SQL que genera Gemini, antes de que toque
SQL Server. Mismo principio que tools.py::_validate_* en NetOps AI, pero
para SQL en vez de subprocess/sockets: nunca confiar en que el modelo
"se porte bien" solo porque el prompt se lo pide.

Capas de defensa (cada una asume que las anteriores podrían fallar):
  1. Parseo real con sqlglot (no regex) -> si no parsea como SQL válido, se
     rechaza. Esto ya bloquea trucos de comentarios/sintaxis rota.
  2. Debe ser EXACTAMENTE UNA sentencia -> bloquea "SELECT ...; DROP ...".
  3. Debe ser un SELECT -> cualquier INSERT/UPDATE/DELETE/DROP/ALTER/EXEC/
     MERGE/TRUNCATE/GRANT se rechaza antes de llegar a la base.
  4. Whitelist de tablas y columnas contra schema_context.ALLOWED_SCHEMA ->
     bloquea acceso a sys.tables, información de otras bases, tablas nuevas
     que alguien agregue sin actualizar este archivo, etc.
  5. Si no trae límite de filas, se inyecta TOP 100 automáticamente.

Nota: además de esto, la conexión a SQL Server debe hacerse con un usuario
db_datareader (ver 00_crear_usuario_readonly.sql). Este validador es la
primera barrera, el permiso de base de datos es la segunda — ninguna de
las dos reemplaza a la otra.
"""

import sqlglot
from sqlglot import exp

from schema_context import ALLOWED_SCHEMA, ALLOWED_TABLES

MAX_ROWS_DEFAULT = 100
DIALECT = "tsql"


class SQLValidationError(Exception):
    """Se lanza cuando el SQL generado no pasa alguna capa de validación."""


def validate_and_prepare(raw_sql: str) -> str:
    """
    Recibe el SQL crudo generado por Gemini. Devuelve un SQL seguro para
    ejecutar, o lanza SQLValidationError con un motivo claro.
    """
    sql = _strip_markdown_fences(raw_sql).strip().rstrip(";").strip()

    if not sql:
        raise SQLValidationError("El modelo no generó ninguna sentencia SQL.")

    statements = _parse_statements(sql)

    if len(statements) != 1:
        raise SQLValidationError(
            f"Se esperaba una sola sentencia SQL, se recibieron {len(statements)}. "
            "Posible intento de encadenar comandos."
        )

    stmt = statements[0]

    _assert_is_select(stmt)
    _assert_no_forbidden_expressions(stmt)
    _assert_tables_and_columns_whitelisted(stmt)

    stmt = _ensure_row_limit(stmt)

    return stmt.sql(dialect=DIALECT)


def _strip_markdown_fences(text: str) -> str:
    # Gemini a veces envuelve el SQL en ```sql ... ``` pese a la instrucción
    # de no hacerlo; lo removemos antes de parsear.
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def _parse_statements(sql: str):
    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except Exception as e:
        raise SQLValidationError(f"El SQL generado no es válido y no pudo parsearse: {e}")

    statements = [s for s in statements if s is not None]
    return statements


def _assert_is_select(stmt: exp.Expression):
    if not isinstance(stmt, exp.Select):
        raise SQLValidationError(
            f"Solo se permiten sentencias SELECT. Se recibió: {type(stmt).__name__}."
        )


# Tipos de expresión de sqlglot que jamás deben aparecer, ni siquiera
# anidados dentro de una subquery de un SELECT aparentemente inocente.
_FORBIDDEN_EXPR_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.Command, exp.Merge, exp.Grant,
)


def _assert_no_forbidden_expressions(stmt: exp.Expression):
    for node in stmt.walk():
        node_expr = node[0] if isinstance(node, tuple) else node
        if isinstance(node_expr, _FORBIDDEN_EXPR_TYPES):
            raise SQLValidationError(
                f"Se detectó una operación no permitida ({type(node_expr).__name__}) "
                "dentro de la consulta."
            )
        # exec / sp_executesql / xp_cmdshell suelen aparecer como llamadas
        # a función o como Command; cubrimos también el caso de función.
        if isinstance(node_expr, exp.Anonymous):
            name = (node_expr.this or "").lower()
            if name in {"exec", "execute", "sp_executesql", "xp_cmdshell"}:
                raise SQLValidationError(f"Función no permitida: {name}")


def _collect_defined_aliases(stmt: exp.Expression) -> set:
    """
    Junta los alias que la propia consulta define (ej. SUM(g.importe) AS
    total_gasto). No representan un riesgo nuevo: el valor detrás del alias
    ya pasó por la validación normal de columnas/tablas, el alias es solo
    una etiqueta para poder referenciarlo en ORDER BY/HAVING.
    """
    aliases = set()
    for alias_node in stmt.find_all(exp.Alias):
        alias_name = alias_node.alias
        if alias_name:
            aliases.add(alias_name.lower())
    return aliases


def _assert_tables_and_columns_whitelisted(stmt: exp.Expression):
    tables_in_query = set()
    for table in stmt.find_all(exp.Table):
        table_name = table.name.lower()
        catalog = (table.catalog or "").lower()
        db = (table.db or "").lower()

        # Bloquea "master.dbo.empleados", "OtraBase.dbo.gastos", etc.
        # Nuestras queries solo deben referenciar dbo.tabla o tabla a secas,
        # nunca otra base de datos ni otro esquema.
        if catalog:
            raise SQLValidationError(
                f"No se permite calificar tablas con otra base de datos: '{catalog}'."
            )
        if db and db != "dbo":
            raise SQLValidationError(
                f"No se permite referenciar el esquema '{db}'. Solo se permite 'dbo'."
            )

        tables_in_query.add(table_name)
        if table_name not in ALLOWED_TABLES:
            raise SQLValidationError(
                f"Tabla no permitida: '{table_name}'. "
                f"Tablas permitidas: {sorted(ALLOWED_TABLES)}"
            )

    allowed_columns_union = set()
    for t in tables_in_query:
        allowed_columns_union |= ALLOWED_SCHEMA[t]

    defined_aliases = _collect_defined_aliases(stmt)

    for column in stmt.find_all(exp.Column):
        col_name = column.name.lower()
        if col_name == "*":
            continue
        if col_name in allowed_columns_union:
            continue
        # Solo eximimos referencias SIN calificador de tabla (ej. "ORDER BY
        # total_gasto", no "t.total_gasto") que coincidan con un alias
        # definido en esta misma consulta -- así no se puede usar el truco
        # para colar una columna real fuera de la whitelist con un alias
        # falso, porque igual necesitaría venir de una tabla ya validada.
        if not column.table and col_name in defined_aliases:
            continue
        raise SQLValidationError(
            f"Columna no permitida o no reconocida: '{col_name}'."
        )


def _ensure_row_limit(stmt: exp.Select) -> exp.Select:
    has_limit = stmt.args.get("limit") is not None
    # TOP en T-SQL se modela distinto según versión de sqlglot; chequeamos
    # ambos por robustez.
    has_top = stmt.args.get("top") is not None or "TOP" in stmt.sql(dialect=DIALECT).upper()[:40]

    if not has_limit and not has_top:
        stmt = stmt.copy()
        stmt.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROWS_DEFAULT)))

    return stmt
