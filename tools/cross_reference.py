import json
import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 3000

_SYSTEM_PROMPT = (
    "Eres un analista de datos públicos españoles. Tu trabajo es encontrar "
    "conexiones, contradicciones o relaciones relevantes entre dos fuentes "
    "de información en el contexto de una pregunta ciudadana concreta. "
    "Sé directo y cita datos específicos. Nunca inventes información."
)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def cross_reference(
    text_a: str,
    source_a: str,
    text_b: str,
    source_b: str,
    question: str,
    model: str = None,
) -> dict:
    """
    Cruza dos fuentes de datos usando el LLM para encontrar conexiones,
    contradicciones o relaciones relevantes en el contexto de una pregunta.

    Esta tool usa Claude internamente como motor de análisis: no aplica reglas
    heurísticas ni comparaciones de texto, sino que razona sobre el contenido
    semántico de ambas fuentes. Los textos se truncan a 3000 caracteres cada
    uno antes de enviarse al modelo.

    Args:
        text_a:   Contenido extraído de la primera fuente.
        source_a: Nombre descriptivo de la primera fuente (ej: "BOE").
        text_b:   Contenido extraído de la segunda fuente.
        source_b: Nombre descriptivo de la segunda fuente (ej: "datos.gob.es").
        question: La pregunta original del usuario que motiva la investigación.
        model:    Override puntual del modelo. Si es None se usa ANTHROPIC_MODEL
                  del entorno (o "claude-sonnet-4-20250514" como fallback).

    Returns:
        Dict con las claves:
          - question (str):       la pregunta original
          - source_a (str):       nombre de la fuente A
          - source_b (str):       nombre de la fuente B
          - connections (str):    conexiones encontradas entre las fuentes
          - contradictions (str | None): contradicciones detectadas, o None
          - conclusion (str):     conclusión provisional del análisis
          - raw_response (str):   respuesta completa del LLM sin procesar
        En caso de error de API devuelve el mismo dict con campos vacíos.
    """
    _model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    _max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1000"))

    empty = {
        "question": question,
        "source_a": source_a,
        "source_b": source_b,
        "connections": "",
        "contradictions": None,
        "conclusion": "",
        "raw_response": "",
    }

    if len(text_a) > _MAX_TEXT_CHARS:
        text_a = text_a[:_MAX_TEXT_CHARS]
    if len(text_b) > _MAX_TEXT_CHARS:
        text_b = text_b[:_MAX_TEXT_CHARS]

    user_message = (
        f"Pregunta ciudadana: {question}\n\n"
        f"FUENTE A — {source_a}:\n{text_a}\n\n"
        f"FUENTE B — {source_b}:\n{text_b}\n\n"
        "Analiza las dos fuentes en relación con la pregunta. "
        "Responde únicamente con un objeto JSON con exactamente estas claves:\n"
        "{\n"
        '  "connections": "texto con las conexiones encontradas entre las dos fuentes",\n'
        '  "contradictions": "texto con contradicciones detectadas, o null si no hay ninguna",\n'
        '  "conclusion": "conclusión provisional del análisis"\n'
        "}"
    )

    try:
        response = _get_client().messages.create(
            model=_model,
            max_tokens=_max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIStatusError as e:
        logger.error("Error HTTP %s de la API de Anthropic: %s", e.status_code, e.message)
        return empty
    except anthropic.APIConnectionError as e:
        logger.error("No se pudo conectar con la API de Anthropic: %s", e)
        return empty
    except Exception as e:
        logger.error("Error inesperado al llamar a la API de Anthropic: %s", e)
        return empty

    raw = next((b.text for b in response.content if b.type == "text"), "")
    parsed = _parse_llm_json(raw)

    return {
        "question": question,
        "source_a": source_a,
        "source_b": source_b,
        "connections": parsed.get("connections", ""),
        "contradictions": parsed.get("contradictions"),
        "conclusion": parsed.get("conclusion", ""),
        "raw_response": raw,
    }


def _parse_llm_json(text: str) -> dict:
    """Extrae el JSON de la respuesta del LLM de forma robusta.

    Si el modelo envuelve el JSON en un bloque de código o añade texto previo,
    localiza los delimitadores { } y parsea solo esa parte. Normaliza
    contradictions: convierte las cadenas "null" o vacías a None de Python.
    """
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end])
            if data.get("contradictions") in ("null", "", None):
                data["contradictions"] = None
            return data
        except json.JSONDecodeError:
            pass
    logger.warning("La respuesta del LLM no contiene JSON válido; usando texto crudo.")
    return {"connections": text, "contradictions": None, "conclusion": ""}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    text_a = """
    La Ley 9/2017 de Contratos del Sector Público establece que los contratos
    menores no pueden superar los 15.000 euros para obras ni 5.000 euros para
    suministros y servicios. El artículo 118 prohíbe expresamente el
    fraccionamiento de contratos para eludir estos límites y obliga a los
    órganos de contratación a no fragmentar un contrato con objeto de disminuir
    su cuantía y eludir los requisitos de publicidad o procedimiento de
    adjudicación que correspondan.
    """

    text_b = """
    El Ayuntamiento de Ejemplo adjudicó en 2022 un total de 847 contratos menores
    por un importe global de 3,2 millones de euros. El 34% de los contratos fueron
    adjudicados al mismo proveedor en conceptos similares (mantenimiento informático),
    con importes individuales de entre 4.800 y 4.999 euros, todos por debajo del
    umbral legal de 5.000 euros. El proveedor beneficiado, Informática SL, recibió
    288 adjudicaciones en el ejercicio, una media de 5,5 por semana.
    """

    pregunta = "¿Está el Ayuntamiento fraccionando contratos para eludir la ley?"

    print(f"Pregunta: {pregunta}\n")
    resultado = cross_reference(
        text_a=text_a,
        source_a="BOE — Ley 9/2017 de Contratos del Sector Público",
        text_b=text_b,
        source_b="Portal de transparencia del Ayuntamiento de Ejemplo",
        question=pregunta,
    )

    print(f"Conexiones:\n{resultado['connections']}\n")
    print(f"Contradicciones: {resultado['contradictions']}\n")
    print(f"Conclusión:\n{resultado['conclusion']}")
