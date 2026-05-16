import json
import logging
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from tools.cross_reference import cross_reference
from tools.fetch_document import fetch_document
from tools.search_boe import search_boe
from tools.search_datasets import search_datasets
from tools.write_report import write_report

load_dotenv()

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))
_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1000"))

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")

_TOOLS = [
    {
        "name": "search_datasets",
        "description": "Busca conjuntos de datos públicos en el catálogo datos.gob.es.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Términos de búsqueda en español.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de resultados. Por defecto 5.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_boe",
        "description": "Busca normas en la legislación consolidada del BOE (Boletín Oficial del Estado).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Términos de búsqueda en español.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de resultados. Por defecto 5.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_document",
        "description": "Descarga y extrae el contenido legible de una URL pública (HTML, XML o JSON).",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL pública a descargar.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "cross_reference",
        "description": (
            "Cruza dos fuentes de datos para encontrar conexiones, contradicciones "
            "o relaciones relevantes entre ellas en el contexto de la pregunta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text_a": {
                    "type": "string",
                    "description": "Contenido extraído de la primera fuente.",
                },
                "source_a": {
                    "type": "string",
                    "description": "Nombre descriptivo de la primera fuente.",
                },
                "text_b": {
                    "type": "string",
                    "description": "Contenido extraído de la segunda fuente.",
                },
                "source_b": {
                    "type": "string",
                    "description": "Nombre descriptivo de la segunda fuente.",
                },
                "question": {
                    "type": "string",
                    "description": "La pregunta original del usuario que motiva la investigación.",
                },
            },
            "required": ["text_a", "source_a", "text_b", "source_b", "question"],
        },
    },
    {
        "name": "write_report",
        "description": (
            "Genera y guarda el informe final de la investigación. "
            "Llamar solo cuando la investigación esté completa."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "object",
                    "description": "Resultado completo de la investigación.",
                    "properties": {
                        "question": {"type": "string"},
                        "summary": {"type": "string"},
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "fact": {"type": "string"},
                                    "source": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                                "required": ["fact", "source"],
                            },
                        },
                        "limitations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["question", "summary", "findings", "limitations", "sources"],
                },
            },
            "required": ["findings"],
        },
    },
]


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
          - status (str):     "completed" | "max_iterations_reached"
          - iterations (int): número de iteraciones consumidas
          - path (str | None): ruta del informe generado, o None si no se generó
    """
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    report_path = None
    write_report_called = False

    for iteration in range(_MAX_ITERATIONS):
        logger.info("Iteración %d/%d", iteration + 1, _MAX_ITERATIONS)

        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            logger.info("Agente terminó sin tool_use en iteración %d", iteration + 1)
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            logger.info(
                "Tool: %s | params: %s",
                block.name,
                json.dumps(block.input, ensure_ascii=False)[:200],
            )

            result = _dispatch_tool(block.name, block.input)

            if block.name == "write_report":
                write_report_called = True
                report_path = result.get("path")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        messages.append({"role": "user", "content": tool_results})

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
