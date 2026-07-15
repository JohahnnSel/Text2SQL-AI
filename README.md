# Libro de Gastos — Text-to-SQL con IA + Power BI

Plataforma de analítica de gastos de RRHH que combina un dashboard de Power
BI tradicional con un asistente conversacional que traduce preguntas en
lenguaje natural a SQL, las valida contra un firewall de seguridad propio,
las ejecuta contra SQL Server con un usuario de solo lectura, y devuelve
tanto los datos crudos como un resumen generado por IA.

Proyecto de portafolio pensado para demostrar: **modelado de bases de
datos, ETL, APIs REST, integración con LLMs, seguridad en aplicaciones de
IA, Business Intelligence y desarrollo frontend.**

Complementa a [NetOps AI](#) (agente de diagnóstico de redes sobre Google
Gemini) desde un ángulo distinto: acá el foco es datos estructurados,
Text-to-SQL y BI, en vez de function calling sobre herramientas de
diagnóstico.

---

## Capturas

> _Agregar acá las capturas del dashboard de Power BI, del frontend en
> acción, del SQL generado, y de `/docs` (Swagger). Sugerencia de
> estructura de carpeta:_
>
> ```
> imagenes/
> ├── powerbi/dashboard.png
> ├── frontend/consulta.png
> ├── consulta_sql/sql_generado.png
> └── api/swagger.png
> ```

---

## Características

- Traducción de lenguaje natural a SQL (Google Gemini)
- Validación estructural del SQL con `sqlglot` (no regex)
- Usuario de SQL Server de solo lectura, separado del usuario admin
- Resúmenes en lenguaje natural del resultado de cada consulta
- Dashboard de Power BI con modelo estrella y medidas DAX
- API REST con FastAPI, documentación automática en `/docs`
- ETL documentado y validado desde Excel a SQL Server
- Frontend web propio (HTML + CSS + JS, sin frameworks)
- Protección contra SQL injection, sentencias encadenadas y XSS

---

## Arquitectura

```
                        Usuario
                           │
                           ▼
              Frontend (HTML + CSS + JS)
                           │
                    POST /api/query
                           │
                           ▼
                    FastAPI (main.py)
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         │
      Gemini genera SQL                 │
      (gemini_client.py)                │
              │                         │
              ▼                         │
      sql_validator.py                  │
      (whitelist + sqlglot)             │
              │                         │
              ▼                         │
      SQL Server, usuario ReadOnly      │
      (db.py)                           │
              │                         │
              ▼                         │
      Gemini resume el resultado ◄──────┘
      (gemini_client.py)
              │
              ▼
          Frontend
```

El SQL Server de origen (`GastosRRHH`) también se conecta directamente a
Power BI Desktop en modo Import, como segunda vía de análisis —
dashboards tradicionales en paralelo al asistente conversacional.

---

## Tecnologías

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Base de datos | SQL Server Express, SSMS |
| IA | Google Gemini API (`gemini-3.1-flash-lite`), SDK oficial [`google-genai`](https://pypi.org/project/google-genai/) |
| Validación SQL | [`sqlglot`](https://github.com/tobymao/sqlglot) (parser real, no regex) |
| Frontend | HTML5, CSS3, JavaScript vanilla — sin frameworks ni build step |
| BI | Microsoft Power BI Desktop, DAX, Power Query |
| ETL | pandas, openpyxl, SQLAlchemy, pyodbc |
| Config | python-dotenv |

---

## Base de datos: `GastosRRHH`

Modelo **copo de nieve** con 4 tablas, migrado desde un Excel de origen
(`12_MODELO_DATOS_GASTOS_COPO_DE_NIEVE.xlsx`, 4 hojas).

```
Conceptos          Departamentos (PK compuesta: cod_dpto + jornada)
   │                      │
   │                      │  (FK compuesta)
   ▼                      ▼
 Gastos ◄───────────── Empleados
(~50.000 filas)
```

- **`Conceptos`**: tipos de gasto (Material, Comida, Desplazamiento,
  Alojamiento) e IVA asociado.
- **`Departamentos`**: clave primaria **compuesta** (`cod_dpto` +
  `jornada`) — cada departamento tiene un `plazo_pago` y `extra`
  distinto según el turno. No es un capricho de modelado: así viene el
  dato real en el Excel origen.
- **`Empleados`**: referencia a `Departamentos` con una FK igualmente
  compuesta (`cod_dpto`, `jornada`).
- **`Gastos`**: tabla de hechos, ~50.000 registros, con importe, fecha,
  estado de pago y fecha de pago.

### ETL (`migrate_excel_to_sql.py`)

```
Excel (4 hojas) → pandas (limpieza y tipado) → validación de integridad
referencial en Python → SQL Server (fast_executemany) → verificación de
conteos post-inserción
```

Puntos de diseño:
- Convierte `SI`/`NO` a `BIT`, tipa fechas, redondea decimales.
- **Valida integridad referencial antes de tocar SQL Server**: si algún
  gasto referenciara un empleado o concepto inexistente, el script frena
  con un mensaje claro en vez de dejar que SQL Server tire un error de FK
  genérico a mitad de carga.
- Inserta en orden de dependencias (`Conceptos → Departamentos →
  Empleados → Gastos`) usando `fast_executemany`, así las 50.000 filas de
  `Gastos` entran en segundos.

---

## Seguridad

La seguridad es el eje central del proyecto — no es una casilla que se
tilda al final, se construyó con capas independientes y se **probó** cada
una contra intentos de bypass reales (ver [Retos
encontrados](#retos-encontrados-y-cómo-se-resolvieron)).

### Capa 1 — Usuario de solo lectura en SQL Server

`00_crear_usuario_readonly.sql` crea `text2sql_reader` con únicamente el
rol `db_datareader`, más un `DENY` explícito de
`INSERT/UPDATE/DELETE/ALTER` como cinturón de seguridad adicional. La API
nunca se conecta con el usuario admin. Esta capa es independiente de
cualquier validación en el código: aunque el validador tuviera un agujero,
el usuario de base de datos no tiene permiso físico para escribir.

### Capa 2 — Validador de SQL (`sql_validator.py`)

Usa `sqlglot` para parsear el SQL generado por Gemini como un árbol
sintáctico real, no con expresiones regulares:

1. Debe ser **exactamente una** sentencia — bloquea `SELECT ...; DROP ...`.
2. Debe ser un `SELECT` — bloquea `INSERT/UPDATE/DELETE/DROP/ALTER/EXEC/
   MERGE/GRANT/TRUNCATE`, incluso anidados en subqueries.
3. **Whitelist de tablas y columnas** contra `schema_context.py` (fuente
   única de verdad, compartida con el prompt de Gemini).
4. Bloquea calificar tablas con otra base de datos o esquema
   (`master.dbo.empleados`).
5. Permite referencias a **alias definidos en la propia consulta** (ej.
   `ORDER BY total_gasto` cuando `total_gasto` es un `AS` del mismo
   `SELECT`), sin abrir la puerta a columnas reales inventadas.
6. Inyecta automáticamente `TOP 100` si la consulta no trae límite.

### Capa 3 — Frontend

Todo el contenido que viene del backend (SQL generado, filas de la base,
mensajes de error) se inserta con `textContent`, nunca `innerHTML` —
relevante porque ese contenido en última instancia sale de un LLM o de la
base de datos, no es texto de confianza.

---

## Retos encontrados (y cómo se resolvieron)

Documentar esto en detalle importa más que decir "el sistema es seguro":
cada uno de estos fue un caso real, reproducido con un test antes de
corregirlo.

### 1. Bypass de la whitelist con `master.dbo.tabla`

**Problema:** el validador solo comparaba el nombre de la tabla contra la
whitelist, ignorando el calificador de base de datos/esquema.
`SELECT * FROM master.dbo.empleados` colaba porque `.name` devolvía
`empleados` (permitido), sin chequear que el `catalog` fuera `master`.

**Cómo se encontró:** probando el validador contra una batería de
ataques típicos antes de darlo por bueno (bypass de calificador de base
de datos es un patrón conocido en firewalls de SQL).

**Fix:** se agregó el chequeo explícito de `table.catalog` y `table.db`
en `sql_validator.py` — cualquier calificador que no sea vacío o `dbo` se
rechaza.

**Test de regresión:** `master.dbo.empleados`, `OtraBase.dbo.gastos` y
`[master].[sys].[empleados]` deben rechazarse; `dbo.empleados` y
`empleados` a secas deben seguir aceptándose.

---

### 2. `DENY CONTROL` bloqueaba el acceso completo a la base (error 4060)

**Problema:** `00_crear_usuario_readonly.sql` incluía
`DENY ... CONTROL ON DATABASE::GastosRRHH`, pensado como un cinturón de
seguridad extra. `CONTROL` en SQL Server es el permiso máximo sobre la
base de datos e **implica todos los demás**, incluida la posibilidad de
conectarse. Denegarlo bloqueó el acceso completo al usuario de solo
lectura, no solo la escritura.

**Cómo se encontró:** al conectar la API por primera vez, apareció
`Login failed... (18456)` combinado con
`Cannot open database "GastosRRHH"... (4060)`, pese a que el login y el
usuario existían correctamente en sus niveles correspondientes.

**Fix:**
```sql
REVOKE CONTROL ON DATABASE::GastosRRHH FROM text2sql_reader;
DENY INSERT, UPDATE, DELETE, ALTER ON DATABASE::GastosRRHH TO text2sql_reader;
```
(`REVOKE`, no `GRANT`, porque `DENY` tiene prioridad sobre `GRANT` — hay
que revocar el `DENY` puntualmente para deshacerlo.)

**Lección:** un permiso "extra" de seguridad mal elegido puede ser más
restrictivo de lo previsto. `db_datareader` ya cubre la intención
original; el `DENY` puntual debe limitarse a los verbos de escritura, sin
incluir `CONTROL`.

---

### 3. El validador rechazaba alias legítimos del propio `SELECT`

**Problema:** preguntas como *"¿Qué conceptos representan el mayor gasto
de la empresa?"* generaban SQL válido y bien formado:
```sql
SELECT c.concepto, SUM(g.importe) AS total_gasto
FROM gastos g JOIN conceptos c ON g.cod_concepto = c.cod_concepto
GROUP BY c.concepto
ORDER BY total_gasto DESC
```
pero el validador lo rechazaba con `Columna no permitida: 'total_gasto'`.
No era un alias inventado sin sentido: era el propio alias del `SELECT`,
referenciado en el `ORDER BY` — sintaxis perfectamente válida en T-SQL,
pero `total_gasto` no existe como columna real en ninguna tabla, así que
la whitelist lo bloqueaba igual que bloquearía una columna inventada de
verdad.

**Cómo se encontró:** probando preguntas de agregación reales durante la
demo, no en la batería de ataques inicial — buen recordatorio de que los
casos límite de uso legítimo también hay que probarlos, no solo los
maliciosos.

**Fix:** se agregó `_collect_defined_aliases()` en `sql_validator.py`,
que junta los alias definidos en la propia consulta (`exp.Alias` de
`sqlglot`) y los exime del chequeo de whitelist **solo cuando aparecen
sin calificador de tabla** (`total_gasto`, no `t.total_gasto`) — así no
se puede usar el mismo mecanismo para colar una columna real fuera de la
whitelist disfrazada de alias.

**Test de regresión:** el alias `total_gasto` referenciado en `ORDER BY`
pasa; `g.total_gasto` (calificado, no es un alias real) sigue
rechazándose; `ORDER BY salario` sin que `salario` sea alias de esa
consulta sigue rechazándose.

---

## API (FastAPI)

### `GET /health`
Confirma que la API está corriendo.

### `POST /api/query`

Body:
```json
{ "pregunta": "¿Cuánto gastó cada departamento en total?" }
```

Respuesta:
```json
{
  "pregunta": "...",
  "sql_generado": "SELECT TOP 100 ...",
  "filas": [ { "nombre_dpto": "RRHH", "total": 12345.67 }, ... ],
  "total_filas": 8,
  "resumen": "RRHH lidera el gasto total con...",
  "duracion_ms": 812
}
```

Si el SQL generado no pasa el validador, la API responde `422` con el
motivo puntual del rechazo. Documentación interactiva completa (Swagger)
disponible en `/docs` una vez levantado el servidor.

---

## Integración con Gemini

Gemini cumple dos roles distintos en el flujo (`gemini_client.py`):

1. **Generación de SQL**: recibe la pregunta + la descripción del esquema
   (`schema_context.py`) y devuelve la sentencia T-SQL correspondiente,
   con `temperature=0` para mantenerlo determinístico.
2. **Resumen del resultado**: recibe la pregunta original, el SQL
   ejecutado y una muestra de las filas devueltas, y redacta 2-4 líneas en
   lenguaje natural.

El modelo nunca ejecuta nada por su cuenta — solo genera texto. Quien
ejecuta la query es `db.py`, y solo después de pasar por
`sql_validator.py`. Misma separación de responsabilidades que en
NetOps AI: el LLM decide/redacta, el código del servidor es el único que
toca recursos reales.

---

## Frontend

HTML + CSS + JS sin frameworks, servido por el mismo FastAPI
(`app.mount("/static", ...)`). Cada pregunta se muestra como una entrada
numerada — un registro cronológico real de consultas, no una lista
decorativa — con el SQL generado en una tarjeta estilo recibo impreso,
el resumen en prosa, la tabla de resultados y el tiempo de respuesta.
Un indicador de estado en el header confirma la conexión con `/health`
al cargar la página.

---

## Power BI

La base `GastosRRHH` se conecta directamente a Power BI Desktop en modo
**Import** (no DirectQuery): con ~50.000 filas totales, Import da mejor
rendimiento y acceso completo a DAX.

### El reto: Power BI no soporta relaciones de clave compuesta

`Departamentos` tiene PK compuesta (`cod_dpto` + `jornada`), y Power BI
solo relaciona tablas por una columna. Solución: se creó una clave
concatenada (`dpto_jornada_key = cod_dpto & "-" & jornada`) en Power
Query, en `Departamentos` y en `Empleados`, y la relación pasa por esa
columna.

### Modelo estrella resultante

```
              Calendario
                   │
                   ▼
              Gastos
             /      \
            /        \
     Empleados    Conceptos
          │
          ▼
    Departamentos
```

### Medidas DAX principales

Gasto Total, Gasto Pagado/Pendiente, % Pagado, Días Promedio de Pago vs.
Plazo Pago Promedio (con `Diferencia de Plazo` y `Estado de Pago` como
capas de severidad), Gasto per Cápita, Gasto Total con IVA.

### Dashboard — 3 páginas

1. **Resumen ejecutivo**: KPIs, evolución mensual, gasto por
   departamento/concepto.
2. **Análisis de pagos**: pagado vs. pendiente, cumplimiento de plazo por
   departamento.
3. **Análisis organizacional**: gasto por empleado, per cápita, por tipo
   de contrato.

---

## Instalación y ejecución (Windows)

```powershell
git clone <tu-repo>
cd Text2SQL-AI

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

1. Ejecutar `01_crear_esquema.sql` en SSMS → crea `GastosRRHH`.
2. `python migrate_excel_to_sql.py` → carga los datos.
3. Habilitar autenticación mixta en SQL Server (Propiedades del servidor →
   Seguridad) y reiniciar el servicio.
4. Ejecutar `00_crear_usuario_readonly.sql` → crea `text2sql_reader`.
5. `cp .env.example .env` → completar `GOOGLE_API_KEY` (gratis en
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey)) y
   los datos de conexión.
6. `uvicorn main:app --reload`
7. Abrir `http://localhost:8000` (frontend) o `http://localhost:8000/docs`
   (Swagger).

Para el dashboard: abrir Power BI Desktop → Obtener datos → SQL Server →
conectar a la misma base.

---

## Preguntas de ejemplo para una demo

1. ¿Cuánto gastó cada departamento en total?
2. ¿Cuáles son los cinco empleados con mayor gasto?
3. ¿Qué conceptos representan el mayor gasto de la empresa?
4. ¿Cuánto dinero sigue pendiente de pago?
5. ¿Qué departamentos tienen más gastos pendientes?
6. ¿Cuál es el gasto promedio por empleado?
7. ¿Cuáles fueron los diez gastos más altos registrados?
8. ¿Cuántos empleados hay por tipo de contrato?

### Lo que el sistema no puede responder (y por qué)

Es un **Text-to-SQL sobre un esquema fijo**, no un agente autónomo ni un
modelo predictivo. No va a responder bien preguntas que requieran
inferencia, opinión o datos que no están en la base:

- ❌ ¿Por qué aumentaron los gastos este año?
- ❌ ¿Qué departamento será el más costoso el próximo trimestre?
- ❌ ¿Qué decisiones recomendarías para reducir costos?

Estas preguntas necesitan análisis predictivo o inferencias que van más
allá de traducir lenguaje natural a una consulta sobre datos existentes —
una limitación honesta de la arquitectura, no un bug.

---

## Estructura del proyecto

```
Text2SQL-AI/
│
├── main.py                      # Endpoint FastAPI + sirve el frontend
├── gemini_client.py              # Generación de SQL + resumen con Gemini
├── sql_validator.py               # Validador (sqlglot, whitelist)
├── schema_context.py               # Fuente única de verdad del esquema
├── db.py                            # Ejecución contra SQL Server (readonly)
│
├── migrate_excel_to_sql.py           # ETL Excel → SQL Server
├── 01_crear_esquema.sql               # DDL: base + tablas + índices
├── 00_crear_usuario_readonly.sql       # Usuario de solo lectura
│
├── templates/
│   └── index.html
├── static/
│   ├── app.js
│   └── style.css
│
├── imagenes/                            # Capturas para este README
│   ├── powerbi/
│   ├── frontend/
│   ├── consulta_sql/
│   └── api/
│
├── requirements.txt
├── .env.example
└── README.md
```


---

## Autor

**Joan André Gallo Ugarte**

Ingeniería Mecatrónica — Universidad Continental
