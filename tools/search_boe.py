import json
import logging
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from tools.utils.http import _fetch
from tools.utils.xml_parser import _text

logger = logging.getLogger(__name__)

_SUMARIO_URL = "https://boe.es/datosabiertos/api/boe/sumario/{date}"
_DOC_URL = "https://boe.es/datosabiertos/api/legislacion-consolidada/id/{boe_id}/texto"
_CANONICAL_URL = "https://boe.es/buscar/act.php?id={boe_id}"


def search_boe(query: str, max_results: int = 5) -> list[dict]:
    """
    Busca disposiciones en el sumario diario del BOE por palabras clave.

    LIMITACIÓN: Esta función solo busca en disposiciones recientes
    (últimos 3 días). La API del BOE no ofrece búsqueda por texto
    en el histórico completo.

    Descarga el sumario del día en formato JSON e itera desde hoy
    hasta anteayer buscando disposiciones cuyo título contenga alguna
    de las palabras del query (case-insensitive, mínimo 3 caracteres).

    Args:
        query:       Términos de búsqueda. Se comprueba cada palabra
                     de longitud >= 3 contra el título de la disposición.
        max_results: Número máximo de resultados a devolver. Por defecto 5.

    Returns:
        Lista de dicts, uno por disposición, con las claves:
          - title (str):        título de la disposición
          - id (str):           identificador BOE (ej: BOE-A-2025-1234)
          - published_at (str): fecha de publicación (YYYYMMDD)
          - url (str):          URL HTML de la disposición en boe.es
          - summary (str):      primeros 200 caracteres del texto si disponible

        Devuelve lista vacía si no hay resultados en los últimos 3 días
        o si la API no responde.
    """
    keywords = [w.lower() for w in query.split() if len(w) >= 3]
    if not keywords:
        keywords = [query.lower()]

    today = datetime.now()
    for days_ago in range(3):
        date = today - timedelta(days=days_ago)
        date_str = date.strftime("%Y%m%d")

        data = _fetch_json(_SUMARIO_URL.format(date=date_str))
        if data is None:
            continue

        all_items = _collect_items(data)
        matches = [
            item for item in all_items
            if _matches_keywords(item.get("titulo", ""), keywords)
        ]

        if not matches:
            logger.info("Sin resultados en sumario BOE %s para: '%s'", date_str, query)
            continue

        logger.info(
            "Encontradas %d disposiciones en sumario %s para: '%s'",
            len(matches), date_str, query,
        )

        results = []
        for item in matches[:max_results]:
            boe_id = item.get("identificador", "")
            summary = item.get("texto", "")
            if summary and len(summary) > 200:
                summary = summary[:197] + "..."

            results.append({
                "title": item.get("titulo", ""),
                "id": boe_id,
                "published_at": date_str,
                "url": item.get("url_html", ""),
                "summary": summary,
            })
        return results

    logger.info("No se encontraron resultados en el BOE en los últimos 3 días para: '%s'", query)
    return []


def get_boe_document(boe_id: str) -> dict:
    """
    Descarga el texto completo de una norma consolidada del BOE dado su identificador.

    Args:
        boe_id: Identificador BOE de la norma (ej: BOE-A-2023-1234).

    Returns:
        Dict con las claves:
          - id (str):    identificador BOE
          - title (str): título de la norma
          - text (str):  texto completo truncado según MAX_TOKENS_PER_TOOL
          - url (str):   URL canónica del documento

        Devuelve dict con valores vacíos si la descarga o el parseo fallan.
    """
    empty = {"id": boe_id, "title": "", "text": "", "url": ""}

    url = _DOC_URL.format(boe_id=boe_id)
    raw = _fetch(url)
    if raw is None:
        return empty

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.error("XML inválido al descargar documento BOE '%s': %s", boe_id, e)
        return empty

    title = _text(root, "titulo")

    # El texto puede estar en un único elemento <texto> o distribuido en <articulo>
    text_node = root.find(".//texto")
    if text_node is not None and text_node.text:
        full_text = text_node.text.strip()
    else:
        parts = [el.text.strip() for el in root.iter() if el.text and el.text.strip()]
        full_text = " ".join(parts)

    max_chars = int(os.getenv("MAX_TOKENS_PER_TOOL", "5000"))
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars - 3] + "..."

    return {
        "id": boe_id,
        "title": title,
        "text": full_text,
        "url": _CANONICAL_URL.format(boe_id=boe_id),
    }


# --- helpers -----------------------------------------------------------------

def _fetch_json(url: str) -> dict | None:
    """Descarga una URL con Accept: application/json y devuelve el JSON o None."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning("HTTP %s al descargar sumario BOE: %s", e.code, url)
    except urllib.error.URLError as e:
        logger.error("No se pudo conectar con el BOE: %s", e.reason)
    except json.JSONDecodeError as e:
        logger.error("Respuesta del BOE no es JSON válido: %s", e)
    return None


def _collect_items(node) -> list[dict]:
    """Extrae recursivamente todas las disposiciones de la estructura del sumario.

    Identifica los nodos hoja que tienen 'identificador' y 'titulo' como items
    del BOE. No recurre dentro de un nodo ya identificado como item.
    """
    items = []
    if isinstance(node, dict):
        if "identificador" in node and "titulo" in node:
            items.append(node)
        else:
            for v in node.values():
                items.extend(_collect_items(v))
    elif isinstance(node, list):
        for element in node:
            items.extend(_collect_items(element))
    return items


def _matches_keywords(title: str, keywords: list[str]) -> bool:
    """Devuelve True si alguna keyword aparece en el título (case-insensitive)."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in keywords)


# --- ejemplo de uso ----------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    for query in ("contrato", "presupuesto"):
        print(f"Buscando en BOE: '{query}'")
        resultados = search_boe(query, max_results=3)

        if not resultados:
            print("  No se encontraron resultados en los últimos 3 días.\n")
            continue

        for i, norma in enumerate(resultados, 1):
            print(f"  [{i}] {norma['title'][:80]}")
            print(f"      ID:        {norma['id']}")
            print(f"      Publicado: {norma['published_at']}")
            print(f"      URL:       {norma['url']}")
        print()
