import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from tools.cross_reference import cross_reference
from tools.fetch_document import fetch_document
from tools.search_boe import search_boe
from tools.search_datasets import search_datasets
from tools.write_report import write_report

load_dotenv()

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))
_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "1000"))

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")

_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_datasets",
            description="Busca conjuntos de datos públicos en el catálogo datos.gob.es.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="Términos de búsqueda en español.",
                    ),
                    "max_results": types.Schema(
                        type="INTEGER",
                        description="Número máximo de resultados. Por defecto 5.",
                    ),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_boe",
            description="Busca normas en la legislación consolidada del BOE (Boletín Oficial del Estado).",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="Términos de búsqueda en español.",
                    ),
                    "max_results": types.Schema(
                        type="INTEGER",
                        description="Número máximo de resultados. Por defecto 5.",
                    ),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="fetch_document",
            description="Descarga y extrae el contenido legible de una URL pública (HTML, XML o JSON).",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "url": types.Schema(
                        type="STRING",
                        description="URL pública a descargar.",
                    ),
                },
                required=["url"],
            ),
        ),
        types.FunctionDeclaration(
            name="cross_reference",
            description=(
                "Cruza dos fuentes de datos para encontrar conexiones, contradicciones "
                "o relaciones relevantes entre ellas en el contexto de la pregunta."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "text_a": types.Schema(
                        type="STRING",
                        description="Contenido extraído de la primera fuente.",
                    ),
                    "source_a": types.Schema(
                        type="STRING",
                        description="Nombre descriptivo de la primera fuente.",
                    ),
                    "text_b": types.Schema(
                        type="STRING",
                        description="Contenido extraído de la segunda fuente.",
                    ),
                    "source_b": types.Schema(
                        type="STRING",
                        description="Nombre descriptivo de la segunda fuente.",
                    ),
                    "question": types.Schema(
                        type="STRING",
                        description="La pregunta original del usuario que motiva la investigación.",
                    ),
                },
                required=["text_a", "source_a", "text_b", "source_b", "question"],
            ),
        ),
        types.FunctionDeclaration(
            name="write_report",
            description=(
                "Genera y guarda el informe final de la investigación. "
                "Llamar solo cuando la investigación esté completa."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "findings": types.Schema(
                        type="OBJECT",
                        description="Resultado completo de la investigación.",
                        properties={
                            "question": types.Schema(type="STRING"),
                            "summary": types.Schema(type="STRING"),
                            "findings": types.Schema(
                                type="ARRAY",
                                items=types.Schema(
                                    type="OBJECT",
                                    properties={
                                        "fact": types.Schema(type="STRING"),
                                        "source": types.Schema(type="STRING"),
                                        "url": types.Schema(type="STRING"),
                                    },
                                ),
                            ),
                            "limitations": types.Schema(
                                type="ARRAY",
                                items=types.Schema(type="STRING"),
                            ),
                            "sources": types.Schema(
                                type="ARRAY",
                                items=types.Schema(type="STRING"),
                            ),
                        },
                        required=["question", "summary", "findings", "limitations", "sources"],
                    ),
                },
                required=["findings"],
            ),
        ),
    ]
)


def _dispatch_tool(name: str, inputs: dict):
    """Enruta la llamada a la tool correspondiente y devuelve su resultado."""
    if name == "search_datasets":
        return {"results": search_datasets(**inputs)}
    if name == "search_boe":
        return {"results": search_boe(**inputs)}
    if name == "fetch_document":
        return fetch_document(**inputs)
    if name == "cross_reference":
        return cross_reference(**inputs)
    if name == "write_report":
        return write_report(**inputs)
    return {"error": f"Tool desconocida: {name}"}


def run(question: str) -> dict:
    """
    Ejecuta el loop principal del agente investigador (ciclo ReAct).

    Envía la pregunta al modelo con las tools disponibles y repite el ciclo
    Reason → Act → Observe hasta que el agente llame a write_report, responda
    con texto puro o se agoten las iteraciones permitidas.

    Args:
        question: Pregunta de investigación en lenguaje natural.

    Returns:
        Dict con las claves:
          - status (str):      "completed" | "max_iterations_reached"
          - iterations (int):  número de iteraciones consumidas
          - path (str | None): ruta del informe generado, o None si no se generó
    """
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    messages = [types.Content(role="user", parts=[types.Part(text=question)])]
    report_path = None
    write_report_called = False

    for iteration in range(_MAX_ITERATIONS):
        logger.info("Iteración %d/%d", iteration + 1, _MAX_ITERATIONS)

        response = client.models.generate_content(
            model=_MODEL,
            contents=messages,
            config=genai.types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                tools=[_TOOLS],
                max_output_tokens=_MAX_TOKENS,
            ),
        )

        if not response.candidates:
            logger.error("La API de Gemini devolvió una respuesta sin candidatos")
            break

        model_content = response.candidates[0].content
        messages.append(model_content)

        function_call_parts = [
            part for part in model_content.parts if part.function_call
        ]

        if not function_call_parts:
            logger.info("Agente terminó sin function_call en iteración %d", iteration + 1)
            break

        response_parts = []
        for part in function_call_parts:
            tool_name = part.function_call.name
            tool_args = dict(part.function_call.args)

            logger.info(
                "Tool: %s | params: %s",
                tool_name,
                json.dumps(tool_args, ensure_ascii=False, default=str)[:200],
            )

            result = _dispatch_tool(tool_name, tool_args)

            if tool_name == "write_report":
                write_report_called = True
                report_path = result.get("path")

            response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=tool_name,
                        response={"result": result},
                    )
                )
            )

        messages.append(types.Content(role="tool", parts=response_parts))

        if write_report_called:
            logger.info(
                "Informe generado en iteración %d: %s", iteration + 1, report_path
            )
            break

    else:
        logger.warning(
            "Límite de iteraciones alcanzado (%d). La investigación no generó informe.",
            _MAX_ITERATIONS,
        )
        return {
            "status": "max_iterations_reached",
            "iterations": _MAX_ITERATIONS,
            "path": None,
        }

    logger.info("Status: completed | iteraciones usadas: %d", iteration + 1)
    return {
        "status": "completed",
        "path": report_path,
        "iterations": iteration + 1,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    question = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "¿Cuánto gasta el Ayuntamiento de Madrid en consultoría externa?"
    )
    result = run(question)
    print(result)
