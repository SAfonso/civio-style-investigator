import re
from datetime import datetime
from pathlib import Path

_REPORTS_DIR = Path(__file__).parent.parent / "reports"


def write_report(findings: dict) -> dict:
    """
    Genera el informe final del agente investigador y lo guarda en disco.

    El informe se escribe en Markdown con las secciones: resumen ejecutivo,
    hallazgos con fuente citada para cada uno, limitaciones y fuentes
    consultadas. El nombre del fichero incluye un timestamp y un slug
    derivado de la pregunta para facilitar la identificación posterior.

    Args:
        findings: Dict con las claves:
          - question (str):        la pregunta original del usuario
          - summary (str):         respuesta directa en 2-3 líneas
          - findings (list[dict]): hallazgos, cada uno con {fact, source, url}
          - limitations (list[str]): qué no se pudo encontrar y por qué
          - sources (list[str]):   lista completa de URLs consultadas

    Returns:
        Dict con las claves:
          - path (str):       ruta absoluta del fichero generado
          - filename (str):   nombre del fichero
          - word_count (int): número de palabras del informe
    """
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    question = findings.get("question", "sin-titulo")
    summary = findings.get("summary", "")
    finding_items = findings.get("findings", [])
    limitations = findings.get("limitations", [])
    sources = findings.get("sources", [])

    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    slug = _slugify(question)
    filename = f"{timestamp}_{slug}.md"
    path = _REPORTS_DIR / filename

    date_str = now.strftime("%d/%m/%Y %H:%M")
    content = _build_markdown(question, summary, finding_items, limitations, sources, date_str)

    path.write_text(content, encoding="utf-8")

    return {
        "path": str(path),
        "filename": filename,
        "word_count": len(content.split()),
    }


def list_reports() -> list[dict]:
    """
    Lista todos los informes generados en el directorio reports/.

    Los informes se devuelven ordenados por nombre de fichero (que empieza
    por timestamp, por lo que el orden es cronológico).

    Returns:
        Lista de dicts, uno por informe, con las claves:
          - filename (str):    nombre del fichero
          - path (str):        ruta absoluta
          - created_at (str):  fecha de creación en formato ISO 8601
          - size_bytes (int):  tamaño del fichero en bytes
        Devuelve lista vacía si el directorio no existe o está vacío.
    """
    if not _REPORTS_DIR.exists():
        return []

    reports = []
    for report_path in sorted(_REPORTS_DIR.glob("*.md")):
        stat = report_path.stat()
        reports.append({
            "filename": report_path.name,
            "path": str(report_path),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "size_bytes": stat.st_size,
        })
    return reports


# --- helpers -----------------------------------------------------------------

def _slugify(text: str, max_len: int = 50) -> str:
    """Convierte texto a un slug seguro para nombres de fichero.

    Pasa a minúsculas, elimina caracteres no alfanuméricos y reemplaza
    espacios y guiones por guiones bajos.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "_", slug)
    slug = slug[:max_len].strip("_")
    return slug or "informe"


def _build_markdown(
    question: str,
    summary: str,
    finding_items: list[dict],
    limitations: list[str],
    sources: list[str],
    date_str: str,
) -> str:
    """Construye el contenido Markdown del informe."""
    lines = []

    lines += [f"# {question}", ""]

    lines += ["## Resumen ejecutivo", ""]
    lines.append(summary if summary else "_Sin resumen disponible._")
    lines.append("")

    lines += ["## Hallazgos", ""]
    if finding_items:
        for item in finding_items:
            fact = item.get("fact", "")
            source = item.get("source", "")
            url = item.get("url", "")
            citation = f"[{source}]({url})" if url else source
            lines.append(f"- {fact}. Fuente: {citation}")
    else:
        lines.append("_No se encontraron hallazgos._")
    lines.append("")

    lines += ["## Limitaciones", ""]
    if limitations:
        for limitation in limitations:
            lines.append(f"- {limitation}")
    else:
        lines.append("_Sin limitaciones registradas._")
    lines.append("")

    lines += ["## Fuentes consultadas", ""]
    if sources:
        for url in sources:
            lines.append(f"- {url}")
    else:
        lines.append("_Sin fuentes registradas._")
    lines.append("")

    lines += ["---", f"Generado el {date_str} por civio-style-investigator"]

    return "\n".join(lines)


# --- ejemplo de uso ----------------------------------------------------------

if __name__ == "__main__":
    ejemplo = {
        "question": "¿Cuánto gasta España en contratos menores de obra pública?",
        "summary": (
            "España adjudicó en 2022 un total de 284.000 contratos menores "
            "por un importe global de 1.200 millones de euros, según datos del "
            "Registro de Contratos del Sector Público."
        ),
        "findings": [
            {
                "fact": "En 2022 se adjudicaron 284.000 contratos menores en España",
                "source": "Registro de Contratos del Sector Público",
                "url": "https://www.hacienda.gob.es/es-ES/GobiernoAbierto/Datos%20Abiertos/Paginas/licitaciones_plataforma_contratacion.aspx",
            },
            {
                "fact": "El importe total de contratos menores ascendió a 1.200 M€",
                "source": "Informe OIRESCON 2022",
                "url": "https://www.hacienda.gob.es/oirescon",
            },
        ],
        "limitations": [
            "No se encontraron datos desagregados por comunidad autónoma para 2022.",
            "El portal datos.gob.es no devolvió resultados para la consulta 'contratos menores obra'.",
        ],
        "sources": [
            "https://www.hacienda.gob.es/es-ES/GobiernoAbierto/Datos%20Abiertos/Paginas/licitaciones_plataforma_contratacion.aspx",
            "https://www.hacienda.gob.es/oirescon",
            "https://datos.gob.es/apidata/catalog/dataset.json?q=contratos+menores",
        ],
    }

    resultado = write_report(ejemplo)
    print(f"Informe generado: {resultado['filename']}")
    print(f"Ruta:             {resultado['path']}")
    print(f"Palabras:         {resultado['word_count']}")

    print("\nInformes en reports/:")
    for r in list_reports():
        print(f"  {r['filename']}  ({r['size_bytes']} bytes)")
