"""Helper HTTP compartido para todas las tools.
Descarga una URL con timeout de 10s y manejo de errores centralizado.
"""
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def _fetch(url: str) -> bytes | None:
    """Descarga una URL con timeout de 10 s. Devuelve bytes o None si hay error."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        logger.error("HTTP %s al acceder a: %s", e.code, url)
    except urllib.error.URLError as e:
        logger.error("No se pudo conectar con: %s — %s", url, e.reason)
    except Exception as e:
        logger.error("Error inesperado al descargar %s: %s", url, e)
    return None


def _fetch_with_headers(url: str) -> tuple[bytes, str] | None:
    """Como _fetch, pero también devuelve la cabecera Content-Type.

    Returns:
        Tupla (body_bytes, content_type) o None si hay error de red.
        content_type puede ser cadena vacía si el servidor no la envía.
    """
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.read(), content_type
    except urllib.error.HTTPError as e:
        logger.error("HTTP %s al acceder a: %s", e.code, url)
    except urllib.error.URLError as e:
        logger.error("No se pudo conectar con: %s — %s", url, e.reason)
    except Exception as e:
        logger.error("Error inesperado al descargar %s: %s", url, e)
    return None
