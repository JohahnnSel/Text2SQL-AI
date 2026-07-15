"""
gemini_client.py
-----------------
Envuelve las dos únicas llamadas a Gemini que necesita el flujo Text-to-SQL:

  1. generate_sql(pregunta)   -> traduce lenguaje natural a una sentencia SQL
  2. summarize_result(...)     -> convierte las filas devueltas por SQL Server
                                  en una respuesta breve en lenguaje natural

Nota de diseño: acá el modelo NUNCA ejecuta nada por su cuenta. Solo genera
texto (SQL o resumen); quien ejecuta la query es db.py, y solo después de
pasar por sql_validator.py. Es la misma separación de responsabilidades que
ITAgent en NetOps AI: el LLM decide/redacta, el código del lado del
servidor es el único que toca recursos reales.
"""

import os
from google import genai
from google.genai import types

from schema_context import SCHEMA_DESCRIPTION_FOR_LLM

MODEL_NAME = "gemini-3-flash-preview"


class GeminiClient:
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.environ["GOOGLE_API_KEY"]
        self._client = genai.Client(api_key=api_key)

    def generate_sql(self, pregunta_usuario: str) -> str:
        """Devuelve el SQL crudo generado por Gemini (sin validar todavía)."""
        prompt = f"""{SCHEMA_DESCRIPTION_FOR_LLM}

Pregunta del usuario: "{pregunta_usuario}"

Generá la sentencia SQL (T-SQL, SQL Server) que responde esta pregunta."""

        response = self._client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,  # SQL generado debe ser determinístico, no creativo
            ),
        )
        return response.text.strip()

    def summarize_result(self, pregunta_usuario: str, sql_ejecutado: str, filas: list[dict]) -> str:
        """Convierte el resultado tabular en 2-3 líneas de lenguaje natural."""
        if not filas:
            muestra = "(la consulta no devolvió filas)"
        else:
            # Solo mandamos una muestra acotada al modelo: no hace falta
            # (ni conviene) mandarle las 100 filas completas para resumir.
            muestra = str(filas[:15])

        prompt = f"""El usuario preguntó: "{pregunta_usuario}"

Se ejecutó esta consulta SQL:
{sql_ejecutado}

Resultado (muestra de hasta 15 filas de {len(filas)} totales):
{muestra}

Redactá una respuesta breve (2-4 líneas) en español, en lenguaje natural,
que responda la pregunta del usuario basándote en estos datos. No repitas
el SQL. Si el resultado está vacío, decilo claramente."""

        response = self._client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        return response.text.strip()
