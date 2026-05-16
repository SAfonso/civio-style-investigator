import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from tools.cross_reference import cross_reference
from tools.fetch_document import fetch_document
from tools.search_boe import search_boe
from tools.search_datasets import search_datasets
from tools.write_report import write_report

load_dotenv()

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))
_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "1000"))
_REQUEST_DELAY = int(os.getenv("GEMINI_REQUEST_DELAY", "0"))

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


def _collect_urls(tool_name: str, tool_args: dict, result: dict) -> list[str]:
    """Extrae las URLs consultadas de los argumentos y resultados de una tool."""
    urls = []
    if tool_name == "fetch_document":
        url = tool_args.get("url", "")
        if url:
            urls.append(url)
    elif tool_name in ("search_datasets", "search_boe"):
        for item in result.get("results", []):
            if isinstance(item, dict) and item.get("url"):
                urls.append(item["url"])
    return urls


def _auto_report(question: str, summary: str, consulted_urls: list[str], limitation: str) -> str:
    """Llama a write_report con los datos mínimos disponibles y devuelve el path."""
    result = write_report({
        "question": question,
        "summary": summary,
        "findings": [],
        "limitations": [limitation],
        "sources": consulted_urls,
    })
    return result.get("path", "")


def _generate_with_retry(client, contents, config, max_retries: int = 2):
    """Llama a generate_content con reintentos automáticos ante error 429.

    Espera 60 segundos entre reintentos. Lanza la excepción original si se
    agotan los reintentos o si el error no es un rate limit (código 429).
    """
    for attempt in range(max_retries + 1):
        try:
            return client.models.generate_content(
                model=_MODEL, contents=contents, config=config
            )
        except genai_errors.ClientError as e:
            is_rate_limit = getattr(e, "code", None) == 429 or "429" in str(e)
            if is_rate_limit and attempt < max_retries:
                logger.warning(
                    "Rate limit alcanzado — esperando 60s antes de reintentar "
                    "(intento %d/%d)",
                    attempt + 1,
                    max_retries,
                )
                time.sleep(60)
            else:
                if is_rate_limit:
                    logger.error(
                        "Rate limit alcanzado — abortando tras %d reintentos", max_retries
                    )
                raise


def run(question: str) -> dict:
    """
    Ejecuta el loop principal del agente investigador (ciclo ReAct).

    Envía la pregunta al modelo con las tools disponibles y repite el ciclo
    Reason → Act → Observe hasta que el agente llame a write_report, responda
    con texto puro o se agoten las iteraciones permitidas. En los dos últimos
    casos genera automáticamente un informe con los datos recopilados.

    Los errores 429 (rate limit) se reintentan hasta 2 veces con una espera
    de 60 segundos. Si se agotan los reintentos, se genera un informe de
    abort y se devuelve con status "rate_limit_abort".

    Args:
        question: Pregunta de investigación en lenguaje natural.

    Returns:
        Dict con las claves:
          - status (str):     "completed" | "text_response" |
                              "max_iterations_reached" | "rate_limit_abort"
          - iterations (int): número de iteraciones consumidas
          - path (str):       ruta del informe generado (siempre presente)
    """
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    config = genai.types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        tools=[_TOOLS],
        max_output_tokens=_MAX_TOKENS,
    )
    messages = [types.Content(role="user", parts=[types.Part(text=question)])]
    report_path = None
    write_report_called = False
    consulted_urls: list[str] = []

    for iteration in range(_MAX_ITERATIONS):
        logger.info("Iteración %d/%d", iteration + 1, _MAX_ITERATIONS)

        try:
            response = _generate_with_retry(client, messages, config)
        except genai_errors.ClientError as e:
            logger.error("Error de API de Gemini — abortando investigación: %s", e)
            report_path = _auto_report(
                question=question,
                summary="La investigación fue interrumpida por un error de la API de Gemini.",
                consulted_urls=consulted_urls,
                limitation=f"Error de API (rate limit o conexión) tras reintentos: {e}",
            )
            return {
                "status": "rate_limit_abort",
                "path": report_path,
                "iterations": iteration + 1,
            }

        if not response.candidates:
            logger.error("La API de Gemini devolvió una respuesta sin candidatos")
            break

        model_content = response.candidates[0].content
        messages.append(model_content)

        function_call_parts = [
            part for part in model_content.parts if part.function_call
        ]

        if not function_call_parts:
            text_parts = [part.text for part in model_content.parts if part.text]
            agent_text = "\n".join(text_parts).strip()

            logger.info(
                "Agente terminó con respuesta de texto — generando informe automático"
            )
            report_path = _auto_report(
                question=question,
                summary=agent_text or "El agente no encontró información suficiente.",
                consulted_urls=consulted_urls,
                limitation="El agente no encontró datos suficientes en las fuentes consultadas",
            )
            logger.info("Informe automático generado: %s", report_path)
            return {
                "status": "text_response",
                "path": report_path,
                "iterations": iteration + 1,
            }

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
            consulted_urls.extend(_collect_urls(tool_name, tool_args, result))

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

        if _REQUEST_DELAY > 0:
            logger.info("Esperando %ds para respetar rate limit...", _REQUEST_DELAY)
            time.sleep(_REQUEST_DELAY)

    else:
        logger.warning(
            "Límite de iteraciones alcanzado (%d) — generando informe automático.",
            _MAX_ITERATIONS,
        )
        report_path = _auto_report(
            question=question,
            summary="La investigación alcanzó el límite máximo de iteraciones sin completarse.",
            consulted_urls=consulted_urls,
            limitation=(
                f"La investigación alcanzó el límite de {_MAX_ITERATIONS} iteraciones "
                "sin completarse."
            ),
        )
        logger.info("Informe automático generado: %s", report_path)
        return {
            "status": "max_iterations_reached",
            "path": report_path,
            "iterations": _MAX_ITERATIONS,
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
