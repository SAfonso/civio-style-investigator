import json
import logging
import urllib.parse

from tools.utils.http import _fetch

logger = logging.getLogger(__name__)

_BASE_URL = "https://datos.gob.es/apidata/catalog/dataset.json"


def search_datasets(query: str, max_results: int = 5) -> list[dict]:
    """
    Busca datasets en el catálogo público de datos.gob.es.

    Llama a la API REST del catálogo con los términos de búsqueda y devuelve
    los metadatos básicos de cada dataset encontrado.

    Args:
        query:       Términos de búsqueda en lenguaje natural o palabras clave.
        max_results: Número máximo de datasets a devolver. Por defecto 5.

    Returns:
        Lista de dicts, uno por dataset, con las claves:
          - title (str):        título del dataset
          - description (str):  descripción truncada a 200 caracteres
          - url (str):          URL canónica del dataset en datos.gob.es
          - formats (list[str]): formatos disponibles en mayúsculas (CSV, JSON…)

        Devuelve lista vacía si la API no responde, devuelve error HTTP,
        el JSON es inválido o no hay resultados para la búsqueda.
    """
    params = urllib.parse.urlencode({
        "q": query,
        "_pageSize": max_results,
        "_page": 0,
    })
    request_url = f"{_BASE_URL}?{params}"

    raw = _fetch(request_url)
    if raw is None:
        return []

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.error("Respuesta de datos.gob.es no es JSON válido: %s", e)
        return []

    items = data.get("result", {}).get("items", [])
    if not items:
        return []

    results = []
    for item in items:
        title = _extract_text(item.get("title", []))
        description = _extract_text(item.get("description", []))
        if len(description) > 200:
            description = description[:197] + "..."

        identifier = item.get("identifier", "")
        url = f"https://datos.gob.es/es/catalogo/{identifier}" if identifier else ""

        formats = _extract_formats(item.get("distribution", []))

        results.append({
            "title": title,
            "description": description,
            "url": url,
            "formats": formats,
        })

    return results


def _extract_text(values: list, preferred_lang: str = "es") -> str:
    """Extrae texto en el idioma preferido de una lista [{_value, _lang}]."""
    if not values:
        return ""
    for v in values:
        if isinstance(v, dict) and v.get("_lang") == preferred_lang:
            return v.get("_value", "")
    # Fallback al primer valor disponible
    first = values[0]
    if isinstance(first, dict):
        return first.get("_value", "")
    return str(first)


def _extract_formats(distributions: list) -> list[str]:
    """Devuelve lista ordenada de formatos únicos extraídos de las distribuciones."""
    formats = set()
    for dist in distributions:
        if not isinstance(dist, dict):
            continue
        fmt = dist.get("format", {})
        if isinstance(fmt, dict):
            label = _extract_text(fmt.get("label", []))
            if label:
                formats.add(label.upper())
        elif isinstance(fmt, str) and fmt:
            formats.add(fmt.upper())
    return sorted(formats)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    query = "presupuestos municipales"
    print(f"Buscando: '{query}'\n")

    datasets = search_datasets(query, max_results=3)

    if not datasets:
        print("No se encontraron resultados.")
    else:
        for i, ds in enumerate(datasets, 1):
            print(f"[{i}] {ds['title']}")
            print(f"    {ds['description']}")
            print(f"    URL:      {ds['url']}")
            print(f"    Formatos: {', '.join(ds['formats']) or 'N/A'}")
            print()
