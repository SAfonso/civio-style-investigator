import json
import logging
import urllib.parse

from tools.utils.http import _fetch

logger = logging.getLogger(__name__)

_TITLE_URL = (
    "https://datos.gob.es/apidata/catalog/dataset/title/{query}"
    "?_pageSize={size}&_page=0"
)
_KEYWORD_URL = (
    "https://datos.gob.es/apidata/catalog/dataset/keyword/{query}"
    "?_pageSize={size}&_page=0"
)

_STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "los", "las", "por", "del",
    "con", "un", "una", "que", "es", "al",
}


def search_datasets(query: str, max_results: int = 5) -> list[dict]:
    """
    Busca datasets en el catálogo público de datos.gob.es.

    Para queries de más de una palabra, divide el query en palabras
    significativas (descartando stopwords) y busca cada una por separado,
    combinando y deduplicando los resultados. Los datasets que aparecen
    en más búsquedas individuales se devuelven primero.

    Args:
        query:       Términos de búsqueda en español. Se ignoran stopwords
                     comunes y se toman las 3 palabras más significativas
                     si el query supera ese número.
        max_results: Número máximo de datasets a devolver. Por defecto 5.

    Returns:
        Lista de dicts, uno por dataset, ordenada por relevancia:
          - title (str):         título del dataset
          - id (str):            último segmento de la URL canónica
          - description (str):   descripción truncada a 200 caracteres
          - url (str):           URL canónica del dataset (_about)
          - formats (list[str]): formatos disponibles en mayúsculas (CSV, JSON…)

        Devuelve lista vacía si la API no responde o no hay resultados.
    """
    words = _significant_words(query)

    items_by_id: dict[str, dict] = {}
    score_by_id: dict[str, int] = {}

    for word in words:
        for item in _search_word(word, max_results):
            item_id = item.get("id") or item.get("url", "")
            if item_id not in items_by_id:
                items_by_id[item_id] = item
                score_by_id[item_id] = 0
            score_by_id[item_id] += 1

    sorted_items = sorted(
        items_by_id.values(),
        key=lambda x: score_by_id.get(x.get("id") or x.get("url", ""), 0),
        reverse=True,
    )
    return sorted_items[:max_results]


def _significant_words(query: str) -> list[str]:
    """Devuelve hasta 3 palabras significativas del query, sin stopwords."""
    words = [w for w in query.split() if w.lower() not in _STOPWORDS]
    if not words:
        words = query.split()
    return words[:3]


def _search_word(word: str, max_results: int) -> list[dict]:
    """Busca un único término: título primero, keyword como fallback."""
    encoded = urllib.parse.quote(word, safe="")
    results = _search(_TITLE_URL.format(query=encoded, size=max_results))
    if not results:
        results = _search(_KEYWORD_URL.format(query=encoded, size=max_results))
    return results


def _search(url: str) -> list[dict]:
    """Descarga y parsea una URL de búsqueda de la API de datos.gob.es."""
    raw = _fetch(url)
    if raw is None:
        return []

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.error("Respuesta de datos.gob.es no es JSON válido: %s", e)
        return []

    items = data.get("result", {}).get("items", [])
    if not items:
        logger.info("Sin resultados en: %s", url)
        return []

    results = []
    for item in items:
        title = _extract_text(item.get("title", []))
        description = _extract_text(item.get("description", []))
        if len(description) > 200:
            description = description[:197] + "..."

        about = item.get("_about", "")
        item_id = about.rstrip("/").split("/")[-1] if about else ""

        formats = _extract_formats(item.get("distribution", []))

        results.append({
            "title": title,
            "id": item_id,
            "description": description,
            "url": about,
            "formats": formats,
        })

    return results


def _extract_text(values: list, preferred_lang: str = "es") -> str:
    """Extrae texto de una lista de objetos multilang de la API.

    Acepta tanto el formato {_value, _lang} como {value, lang}.
    Prefiere el idioma español; hace fallback al primer valor disponible.
    """
    if not values:
        return ""
    for v in values:
        if not isinstance(v, dict):
            continue
        lang = v.get("_lang") or v.get("lang", "")
        if lang == preferred_lang:
            return v.get("_value") or v.get("value", "")
    first = values[0]
    if isinstance(first, dict):
        return first.get("_value") or first.get("value", "")
    return str(first)


def _extract_formats(distributions: list) -> list[str]:
    """Devuelve lista ordenada de formatos únicos extraídos de las distribuciones."""
    formats: set[str] = set()
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

    for query in ("municipios Barcelona", "contratos menores ayuntamiento"):
        print(f"Buscando: '{query}'")
        print(f"  Palabras significativas: {_significant_words(query)}")
        datasets = search_datasets(query, max_results=3)

        if not datasets:
            print("  No se encontraron resultados.\n")
            continue

        for i, ds in enumerate(datasets, 1):
            print(f"  [{i}] {ds['title']}")
            print(f"      ID:       {ds['id']}")
            print(f"      Desc:     {ds['description'][:80]}...")
            print(f"      URL:      {ds['url']}")
            print(f"      Formatos: {', '.join(ds['formats']) or 'N/A'}")
        print()
