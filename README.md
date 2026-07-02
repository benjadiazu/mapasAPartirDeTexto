# Seminario2025_ICI5541
GENERACIÓN DE MAPAS A PARTIR DE TEXTO

## Cómo ejecutar

### 1. Iniciar el servidor

```bash
python app.py
```

Esto levanta un servidor Flask en `http://localhost:5000`.

### 2. Abrir la interfaz web

Abre un navegador y navega a `http://localhost:5000`.

### 3. Subir un PDF y ejecutar el pipeline

1. Sube el archivo PDF con el texto literario.
2. Selecciona el tipo de pipeline: **Histórico** o **Fantasía**.
3. Haz clic en ejecutar. El progreso de cada paso se muestra en tiempo real.

### 4. Ver los resultados

Una vez completado el pipeline, los mapas generados se muestran en la misma interfaz:

| Pipeline | Salidas |
|----------|---------|
| Histórico | Mapa interactivo Folium (`mapa_historico.html`) + grafo SVG (`mapa_refinado.svg`) |
| Fantasía | Mapa visual (`mapa_fantasia.png`) + comparación de grafos + grafo SVG |

---

## Pipelines de ejecución

### Textos históricos

Los lugares mencionados existen en el mundo real y pueden ser georeferenciados.
El pipeline georreferencia primero, dibuja el mapa interactivo, y luego aplica el solver para generar además el grafo topológico.

```
1. pipeline/1_extraer_relaciones.py    → extrae relaciones espaciales del texto (PDF) con LLM
2. pipeline/5_georeferencia.py         → georreferencia los lugares con Pleiades / Wikidata
4. pipeline/2_generar_inecuaciones.py  → traduce las relaciones a inecuaciones geométricas
5. pipeline/3_resolver_mapa.py         → resuelve las inecuaciones con Z3 y genera coordenadas
6. pipeline/4_refinar_layout.py        → refina el layout con force-directed y exporta el grafo SVG
7. pipeline/6_dibujar_mapa.py          → dibuja el mapa histórico interactivo (Folium)

```

### Textos de fantasía

Los lugares son ficticios y no tienen coordenadas reales; el solver determina la disposición espacial.

```
1. pipeline/1_extraer_relaciones.py    → extrae relaciones espaciales del texto (PDF) con LLM
2. pipeline/2_generar_inecuaciones.py  → traduce las relaciones a inecuaciones geométricas
3. pipeline/3_resolver_mapa.py         → resuelve las inecuaciones con Z3 y genera coordenadas
4. pipeline/4_refinar_layout.py        → refina el layout con force-directed y exporta el grafo SVG
5. pipeline/5_generar_mapa_fantasia.py → genera el mapa de fantasía visual
```

## Descripción de cada script

| Script | Descripción |
|--------|-------------|
| `1_extraer_relaciones.py` | Extrae relaciones espaciales (NORTE_DE, SUR_DE, CERCA_DE, …) usando un LLM. Genera `output/json/map_relations.json`. |
| `2_generar_inecuaciones.py` | Traduce las relaciones a inecuaciones geométricas serializables. Genera `output/json/inequalities.json`. |
| `3_resolver_mapa.py` | Resuelve las inecuaciones con Z3 (solver incremental) y obtiene coordenadas. Genera `output/json/solution.json`. |
| `4_refinar_layout.py` | Aplica force-directed sobre la solución Z3, reescala y exporta el grafo. Genera `output/json/solution_refined.json` y `output/mapas/mapa_refinado.svg`. |
| `5_georeferencia.py` | Georreferencia los lugares con Pleiades y Wikidata. Genera `output/json/diccionario_geografico.json`. |
| `5_generar_mapa_fantasia.py` | Genera el mapa visual de fantasía. Genera `output/mapas/mapa_fantasia.png`. |
| `6_dibujar_mapa.py` | Dibuja los lugares georeferenciados en un mapa Folium interactivo. Genera `output/mapas/mapa_historico.html`. |

## Archivos de datos intermedios

| Archivo | Descripción |
|---------|-------------|
| `output/json/map_relations.json` | Relaciones espaciales extraídas por el LLM |
| `output/json/inequalities.json` | Inecuaciones para el solver |
| `output/json/solution.json` | Coordenadas resueltas por Z3 |
| `output/json/solution_refined.json` | Coordenadas refinadas con force-directed |
| `output/json/diccionario_geografico.json` | Coordenadas reales obtenidas por georreferenciación |
| `output/mapas/mapa_historico.html` | Mapa histórico interactivo (Folium) |
| `output/mapas/mapa_refinado.svg` | Grafo topológico generado por el solver |
| `output/mapas/mapa_fantasia.png` | Mapa de fantasía visual |
