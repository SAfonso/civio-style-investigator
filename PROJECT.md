# civio-style-investigator

Agente de Claude Code que investiga preguntas sobre datos públicos españoles
de forma autónoma. Recibe una pregunta en lenguaje natural y produce un 
informe estructurado con hallazgos y fuentes citadas.

## Componentes

### Tools
- search_datasets(query)         — busca datasets en datos.gob.es
- fetch_document(url)            — descarga y extrae contenido de un documento
- cross_reference(data_a, data_b) — encuentra conexiones entre dos fuentes
- write_report(findings)         — escribe el informe final en Markdown

### Loop
El agente sigue el patrón ReAct:
Reason → Act → Observe → Reason → ...

Condiciones de parada:
1. Ha encontrado datos suficientes para responder con fuentes citables
2. Ha superado el límite de pasos (max_iterations) sin encontrar respuesta
   → escala al usuario con lo encontrado hasta ese momento

### Prompt
Rol: investigador de datos públicos españoles
Objetivo: responder preguntas ciudadanas con datos verificables y fuentes citadas
Restricción: nunca inventar datos, siempre citar fuente

## Estructura del proyecto

civio-style-investigator/
├── agent.py                  # Loop principal del agente
├── tools/
│   ├── search_datasets.py
│   ├── fetch_document.py
│   ├── cross_reference.py
│   └── write_report.py
├── prompts/
│   └── system.md             # System prompt del agente
├── examples/
│   ├── query_simple.txt      # Pregunta con respuesta directa
│   ├── query_complex.txt     # Pregunta que requiere cruzar fuentes
│   ├── query_no_data.txt     # Pregunta sin datos disponibles
│   └── query_ambiguous.txt   # Pregunta ambigua
└── reports/                  # Informes generados por el agente

## Lo que NO hace
- No personaliza el informe según el usuario
- No guarda estado entre ejecuciones
- No decide qué es importante políticamente — solo reporta datos
EOF