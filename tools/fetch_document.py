import json
import logging
import os
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from tools.utils.http import _fetch_with_headers

logger = logging.getLogger(__name__)


def _max_chars() -> int:
    return int(os.getenv("MAX_TOKENS_PER_TOOL", "5000"))


def fetch_document(url: str) -> dict:
    """
    Descarga y extrae el contenido legible de cualquier URL pública.

    Detecta el tipo de contenido por la cabecera Content-Type y aplica
    la extracción adecuada: limpieza de HTML, parseo de XML o JSON,
    o rechazo educado de PDFs.

    Args:
        url: URL pública a descargar. Puede ser de datos.gob.es, BOE,
             INE o cualquier portal con datos abiertos.

    Returns:
        Dict con las claves:
          - url (str):          la URL original
          - content_type (str): MIME type detectado (sin parámetros charset…)
          - text (str):         texto extraído, truncado a 5000 caracteres
          - truncated (bool):   True si el texto fue truncado
        En caso de error de red devuelve el mismo dict con text vacío.
    """
    empty = {"url": url, "content_type": "", "text": "", "truncated": False}

    result = _fetch_with_headers(url)
    if result is None:
        return empty

    raw, content_type_header = result
    mime = content_type_header.split(";")[0].strip().lower()

    max_chars = _max_chars()
    text = _extract_text(raw, mime)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return {
        "url": url,
        "content_type": mime,
        "text": text,
        "truncated": truncated,
    }


def _extract_text(raw: bytes, mime: str) -> str:
    """Enruta la extracción de texto según el MIME type detectado.

    Devuelve el texto crudo decodificado como fallback si el tipo
    no es reconocido o el parseo falla.
    """
    if "pdf" in mime:
        return "PDF no soportado, usar la URL directamente"

    if "html" in mime:
        return _html_to_text(raw)

    if "xml" in mime:
        return _xml_to_text(raw)

    if "json" in mime:
        return _json_to_text(raw)

    return raw.decode("utf-8", errors="replace")


def _html_to_text(raw: bytes) -> str:
    """Extrae texto visible de HTML descartando scripts, estilos y navegación."""
    try:
        html = raw.decode("utf-8", errors="replace")
        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        return extractor.get_text()
    except Exception as e:
        logger.warning("No se pudo parsear HTML, devolviendo texto crudo: %s", e)
        return raw.decode("utf-8", errors="replace")


def _xml_to_text(raw: bytes) -> str:
    """Concatena el texto de todos los nodos de un documento XML."""
    try:
        root = ET.fromstring(raw)
        parts = [el.text.strip() for el in root.iter() if el.text and el.text.strip()]
        return " ".join(parts)
    except ET.ParseError as e:
        logger.warning("No se pudo parsear XML, devolviendo texto crudo: %s", e)
        return raw.decode("utf-8", errors="replace")


def _json_to_text(raw: bytes) -> str:
    """Parsea JSON y lo devuelve como texto indentado y legible."""
    try:
        data = json.loads(raw.decode("utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)
    except json.JSONDecodeError as e:
        logger.warning("No se pudo parsear JSON, devolviendo texto crudo: %s", e)
        return raw.decode("utf-8", errors="replace")


class _HTMLTextExtractor(HTMLParser):
    """HTMLParser que recolecta solo el texto visible de una página.

    Descarta el contenido de <script>, <style>, <head>, <nav>,
    <footer> y <noscript> para devolver únicamente texto legible.
    """

    _SKIP_TAGS = {"script", "style", "head", "nav", "footer", "noscript"}

    def __init__(self):
        super().__init__()
        self._texts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._texts.append(stripped)

    def get_text(self) -> str:
        """Devuelve el texto visible acumulado separado por espacios."""
        return " ".join(self._texts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_url = "https://datos.gob.es/apidata/catalog/dataset/l01280796-lista-de-personal.json"
    print(f"Descargando: {test_url}\n")

    doc = fetch_document(test_url)
    print(f"Tipo:     {doc['content_type']}")
    print(f"Truncado: {doc['truncated']}")
    print(f"\nTexto (primeros 500 chars):\n{doc['text'][:500]}")
