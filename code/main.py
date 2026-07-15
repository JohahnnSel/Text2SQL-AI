"""
main.py
-------
Endpoint FastAPI del flujo Text-to-SQL:

  pregunta (lenguaje natural)
      -> Gemini genera SQL              (gemini_client.py)
      -> se valida el SQL               (sql_validator.py)
      -> se ejecuta contra SQL Server    (db.py, usuario read-only)
      -> Gemini resume el resultado     (gemini_client.py)
      -> se devuelve todo al cliente

Uso:
    pip install -r requirements.txt
    cp .env.example .env   # completar GOOGLE_API_KEY, SQL_*, etc.
    uvicorn main:app --reload

    curl -X POST http://localhost:8000/api/query \
         -H "Content-Type: application/json" \
         -d '{"pregunta": "¿Cuánto gastó el departamento de RRHH en total?"}'
"""

import logging
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from gemini_client import GeminiClient
from sql_validator import validate_and_prepare, SQLValidationError
from db import run_readonly_query

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("text2sql")

app = FastAPI(title="NetOps Analytics — Text-to-SQL con Gemini")

# En desarrollo local basta con permitir todo; en un despliegue real
# restringir a los orígenes concretos del frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

gemini = GeminiClient()

# Frontend: templates/index.html + static/{app.js,style.css}, sin build step.
# Mismo patrón que NetOps AI (Flask + templates/static), adaptado a FastAPI.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("templates/index.html")


class PreguntaRequest(BaseModel):
    pregunta: str


class QueryResponse(BaseModel):
    pregunta: str
    sql_generado: str
    filas: list[dict]
    total_filas: int
    resumen: str
    duracion_ms: int


@app.post("/api/query", response_model=QueryResponse)
def query(request: PreguntaRequest):
    inicio = time.perf_counter()
    pregunta = request.pregunta.strip()

    if not pregunta:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")

    # 1) Gemini traduce la pregunta a SQL
    try:
        sql_crudo = gemini.generate_sql(pregunta)
    except Exception as e:
        log.exception("Error generando SQL con Gemini")
        raise HTTPException(status_code=502, detail=f"Error al generar SQL: {e}")

    # 2) Validación: única puerta de entrada hacia SQL Server
    try:
        sql_seguro = validate_and_prepare(sql_crudo)
    except SQLValidationError as e:
        log.warning("SQL rechazado por el validador. Pregunta: %r | SQL crudo: %r | Motivo: %s",
                    pregunta, sql_crudo, e)
        raise HTTPException(
            status_code=422,
            detail=f"La consulta generada no pasó las validaciones de seguridad: {e}",
        )

    # 3) Ejecución contra SQL Server (usuario read-only)
    try:
        filas = run_readonly_query(sql_seguro)
    except Exception as e:
        log.exception("Error ejecutando SQL en SQL Server")
        raise HTTPException(status_code=502, detail=f"Error al ejecutar la consulta: {e}")

    # 4) Gemini resume el resultado en lenguaje natural
    try:
        resumen = gemini.summarize_result(pregunta, sql_seguro, filas)
    except Exception as e:
        log.exception("Error resumiendo el resultado con Gemini")
        resumen = "No se pudo generar el resumen en lenguaje natural, pero los datos están disponibles abajo."

    duracion_ms = int((time.perf_counter() - inicio) * 1000)

    log.info("Pregunta: %r | Filas: %d | Duración: %dms", pregunta, len(filas), duracion_ms)

    return QueryResponse(
        pregunta=pregunta,
        sql_generado=sql_seguro,
        filas=filas,
        total_filas=len(filas),
        resumen=resumen,
        duracion_ms=duracion_ms,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
