import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET

from tools.utils.http import _fetch
from tools.utils.xml_parser import _text

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://boe.es/datosabiertos/api/legislacion-consolidada"
_DOC_URL = "https://boe.es/datosabiertos/api/legislacion-consolidada/id/{boe_id}/texto"
_CANONICAL_URL = "https://boe.es/buscar/act.php?id={boe_id}"


def search_boe(query: str, max_results: int = 5) -> list[dict]:
    """
    Busca normas en la legislación consolidada del BOE.

    Llama a la API pública de datos abiertos del BOE sin necesidad de API key
    y parsea la respuesta XML para extraer los metadatos de cada norma.

    Args:
        query:       Términos de búsqueda (palabras clave o texto libre).
        max_results: Número máximo de resultados a devolver. Por defecto 5.

    Returns:
        Lista de dicts, uno por norma, con las claves:
          - title (str):        título de la norma
          - id (str):           identificador BOE (ej: BOE-A-2023-1234)
          - published_at (str): fecha de publicación (formato YYYYMMDD o ISO)
          - url (str):          URL del texto completo en boe.es
          - summary (str):      primeros 200 caracteres del sumario si existe

        Devuelve lista vacía si la API no responde, devuelve error HTTP
        o el XML no tiene el formato esperado.
    """
    params = urllib.parse.urlencode({"q": query, "rows": max_results})
    url = f"{_SEARCH_URL}?{params}"

    raw = _fetch(url)
    if raw is None:
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.error("XML inválido en respuesta de búsqueda BOE: %s", e)
        return []

    normas = root.findall(".//norma")
    if not normas:
        logger.info("No se encontraron resultados en BOE para: '%s'", query)
        return []

    results = []
    for norma in normas[:max_results]:
        boe_id = _text(norma, "identificador")
        title = _text(norma, "titulo")
        published_at = _text(norma, "fecha_publicacion")
        url = _text(norma, "url_html") or (
            _CANONICAL_URL.format(boe_id=boe_id) if boe_id else ""
        )
        summary = _text(norma, "sumario")
        if summary and len(summary) > 200:
            summary = summary[:197] + "..."

        results.append({
            "title": title,
            "id": boe_id,
            "published_at": published_at,
            "url": url,
            "summary": summary,
        })

    return results


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
        # Concatenar texto de todos los párrafos/artículos como fallback
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


# --- ejemplo de uso ----------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    query = "contrato menor"
    print(f"Buscando en BOE: '{query}'\n")

    resultados = search_boe(query, max_results=3)

    if not resultados:
        print("No se encontraron resultados.")
    else:
        for i, norma in enumerate(resultados, 1):
            print(f"[{i}] {norma['title']}")
            print(f"    ID:          {norma['id']}")
            print(f"    Publicado:   {norma['published_at']}")
            print(f"    URL:         {norma['url']}")
            if norma["summary"]:
                print(f"    Sumario:     {norma['summary']}")
            print()

        # Descargar el texto completo del primero
        primer_id = resultados[0]["id"]
        if primer_id:
            print(f"Descargando texto completo de {primer_id}...\n")
            doc = get_boe_document(primer_id)
            print(f"Título: {doc['title']}")
            print(f"Texto (primeros 300 chars):\n{doc['text'][:300]}")
