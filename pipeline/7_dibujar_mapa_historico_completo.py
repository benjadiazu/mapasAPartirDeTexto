# 7_dibujar_mapa_historico_completo.py
# Genera un mapa Folium completo con:
#   - Lugares conocidos (Pleiades/Wikidata) → coordenadas reales
#   - Lugares desconocidos → coordenadas estimadas revirtiendo
#     la transformación lat/lon → píxel que hizo 2_generar_inecuaciones_con_geo_seed.py
#
# Requiere haber corrido: 1 → 5 → 2(geo_seed) → 3 → 4

import json
import numpy as np
import folium
from folium.plugins import MousePosition
from pathlib import Path

# ── Verificación tierra/mar (Natural Earth + shapely) ────────
# Descarga ne_110m_land.geojson la primera vez y lo cachea en data/.
# Funciona para cualquier región del mundo, no solo el Mediterráneo.
try:
    import json as _json
    import urllib.request
    from pathlib import Path as _Path
    from shapely.geometry import Point, shape as _shape
    from shapely.ops import unary_union as _unary_union

    _NE_URL = (
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
        "/master/geojson/ne_110m_land.geojson"
    )
    _NE_CACHE = _Path(__file__).resolve().parent.parent / "data" / "ne_110m_land.geojson"

    def _load_land():
        if not _NE_CACHE.exists():
            print(f"  Descargando Natural Earth land 110m → {_NE_CACHE} ...", end="", flush=True)
            _NE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(_NE_URL, _NE_CACHE)
            print(" ✓")
        with open(_NE_CACHE, encoding="utf-8") as _f:
            _data = _json.load(_f)
        polys = [_shape(feat["geometry"]) for feat in _data["features"]]
        return _unary_union(polys)

    _LAND = _load_land()
    print("[tierra/mar] Natural Earth 110m cargado.")

    def is_on_land(lat: float, lon: float) -> bool:
        return bool(_LAND.contains(Point(lon, lat)))

except Exception as _e:
    print(f"[tierra/mar] No disponible ({_e}) — se omite verificación tierra/mar.")
    def is_on_land(*_) -> bool:
        return True

_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"
_IMG_DIR = _ROOT / "output" / "mapas"
_IMG_DIR.mkdir(parents=True, exist_ok=True)

FILE_REFINED  = _JSON_DIR / "solution_refined.json"
FILE_GEO      = _JSON_DIR / "diccionario_geografico.json"
FILE_RELS     = _JSON_DIR / "map_relations.json"
FILE_OUTPUT   = _IMG_DIR  / "mapa_historico_completo.html"

NOMBRE_IMAGEN_ROSA = "../../data/imagenes_ref/rosa.png"

# ============================================================
# 1) CARGAR DATOS
# ============================================================

for path in [FILE_REFINED, FILE_GEO]:
    if not path.exists():
        print(f"❌ Falta {path}")
        raise SystemExit(1)

with open(FILE_REFINED, "r", encoding="utf-8") as f:
    refined = json.load(f)

with open(FILE_GEO, "r", encoding="utf-8") as f:
    diccionario_geo = json.load(f)

relaciones = []
pivotes_set = set()
if FILE_RELS.exists():
    with open(FILE_RELS, "r", encoding="utf-8") as f:
        _rels_data = json.load(f)
    relaciones = _rels_data.get("relaciones", [])
    pivotes_set = set(_rels_data.get("pivotes", []))

# Preferir pivotes re-seleccionados con bonus geo (step 2) si existen
_ineq_path = _JSON_DIR / "inequalities.json"
if _ineq_path.exists():
    with open(_ineq_path, "r", encoding="utf-8") as _iq:
        _ineq_pivotes = json.load(_iq).get("pivotes", [])
    if _ineq_pivotes:
        pivotes_set = set(_ineq_pivotes)

coords_px = refined["coords"]

# ============================================================
# 2) SEPARAR CONOCIDOS Y DESCONOCIDOS
# ============================================================

conocidos = {
    nombre: diccionario_geo[nombre]
    for nombre in coords_px
    if nombre in diccionario_geo and "lat" in diccionario_geo[nombre]
}

desconocidos_px = {
    nombre: coords_px[nombre]
    for nombre in coords_px
    if nombre not in conocidos
}

print(f"Lugares conocidos  (Pleiades/Wikidata): {len(conocidos)}")
print(f"Lugares desconocidos (a estimar por Z3): {len(desconocidos_px)}")

# ============================================================
# 3) CALIBRAR TRANSFORMACIÓN PÍXEL → LAT/LON
#    Usamos los lugares conocidos como conjunto de calibración,
#    filtrando outliers geográficos con el método IQR para que
#    lugares lejanos (Londres, Egipto, etc.) no distorsionen
#    la regresión lineal.
# ============================================================

if len(conocidos) < 2:
    print("❌ Se necesitan al menos 2 lugares conocidos para calibrar la transformación.")
    raise SystemExit(1)

nombres_cal = list(conocidos.keys())
px_x_cal = np.array([coords_px[n]["x"] for n in nombres_cal])
px_y_cal = np.array([coords_px[n]["y"] for n in nombres_cal])
lon_cal  = np.array([conocidos[n]["lon"] for n in nombres_cal])
lat_cal  = np.array([conocidos[n]["lat"] for n in nombres_cal])

# Filtro por distancia MAD (Median Absolute Deviation) desde el centroide.
# Más robusto que IQR para muestras pequeñas con puntos dispersos (mares,
# cordilleras, capitales de región) que sesgarían la regresión lineal.
lat_med = float(np.median(lat_cal))
lon_med = float(np.median(lon_cal))

distances = np.sqrt((lat_cal - lat_med) ** 2 + (lon_cal - lon_med) ** 2)
dist_med = float(np.median(distances))
mad      = float(np.median(np.abs(distances - dist_med)))
threshold = dist_med + 2.5 * mad if mad > 0.05 else dist_med + 2.0
mask = distances <= threshold

outliers = [n for n, m in zip(nombres_cal, mask) if not m]
if outliers:
    print(f"Outliers excluidos de calibración (MAD): {outliers}")

px_x_cal = px_x_cal[mask]
px_y_cal = px_y_cal[mask]
lon_cal  = lon_cal[mask]
lat_cal  = lat_cal[mask]

if len(px_x_cal) < 2:
    print("❌ Quedan menos de 2 puntos tras filtrar outliers.")
    raise SystemExit(1)

# Regresión lineal: lon = a*px_x + b  |  lat = c*px_y + d
a_lon, b_lon = np.polyfit(px_x_cal, lon_cal, 1)
a_lat, b_lat = np.polyfit(px_y_cal, lat_cal, 1)

print(f"\nTransformación calibrada con {len(px_x_cal)} puntos (sin outliers):")
print(f"  lon = {a_lon:.6f} * px_x + {b_lon:.4f}")
print(f"  lat = {a_lat:.6f} * px_y + {b_lat:.4f}")

# Detección de calibración degenerada: si el coeficiente es casi cero,
# el layout colapsó en esa dimensión (spring_layout sin anclas geográficas).
_MIN_COEF = 1e-4  # menos de 0.1°/1000px → inútil
if abs(a_lon) < _MIN_COEF or abs(a_lat) < _MIN_COEF:
    print(
        f"⚠️  CALIBRACIÓN DEGENERADA: a_lon={a_lon:.2e}, a_lat={a_lat:.2e}\n"
        f"   El layout colapsó en una dimensión — todos los puntos estimados\n"
        f"   quedarán en una línea. Revisa step 4 / relaciones cardinales."
    )

# ============================================================
# 4) ESTIMAR COORDENADAS DE LUGARES DESCONOCIDOS
#    y filtrar los que caen fuera de la región geográfica
#    de interés (bounding box de calibración + margen).
# ============================================================

LAT_MARGIN = 4.0
LON_MARGIN = 5.0
lat_min_bbox = float(lat_cal.min()) - LAT_MARGIN
lat_max_bbox = float(lat_cal.max()) + LAT_MARGIN
lon_min_bbox = float(lon_cal.min()) - LON_MARGIN
lon_max_bbox = float(lon_cal.max()) + LON_MARGIN

estimados = {}
inciertos = []  # mencionados en el texto pero sin posición geográfica determinable

for nombre, px in desconocidos_px.items():
    lat_est = float(a_lat * px["y"] + b_lat)
    lon_est = float(a_lon * px["x"] + b_lon)

    dentro_bbox = (
        lat_min_bbox <= lat_est <= lat_max_bbox
        and lon_min_bbox <= lon_est <= lon_max_bbox
    )
    en_tierra = is_on_land(lat_est, lon_est)

    if dentro_bbox and en_tierra:
        estimados[nombre] = {"lat": lat_est, "lon": lon_est}
    else:
        inciertos.append(nombre)

inciertos.sort()
print(f"Lugares estimados dentro del área  : {len(estimados)}")
print(f"Lugares con posición incierta      : {len(inciertos)}")

# ============================================================
# 5) CONSTRUIR MAPA FOLIUM
# ============================================================

todos_lat = [v["lat"] for v in conocidos.values()] + [v["lat"] for v in estimados.values()]
todos_lon = [v["lon"] for v in conocidos.values()] + [v["lon"] for v in estimados.values()]
centro_lat = float(np.mean(todos_lat))
centro_lon = float(np.mean(todos_lon))

mapa = folium.Map(
    location=[centro_lat, centro_lon],
    zoom_start=6,
    tiles="CartoDB positron",
    attr="Tiles © CartoDB"
)

# Cuadrícula visual
grid_css = """
<style>
    .leaflet-container {
        background-image:
            linear-gradient(to right, rgba(0,0,0,0.12) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(0,0,0,0.12) 1px, transparent 1px);
        background-size: 100px 100px;
    }
</style>
"""
mapa.get_root().header.add_child(folium.Element(grid_css))

# Rosa de los vientos
rosa_html = f"""
<div style="position:fixed; top:15px; left:35px; z-index:9999;">
    <img src="{NOMBRE_IMAGEN_ROSA}" style="width:240px; opacity:0.9;">
</div>
"""
mapa.get_root().html.add_child(folium.Element(rosa_html))

# Controles
folium.LayerControl(position="bottomleft", imperial=False).add_to(mapa)
MousePosition(position="topright", separator=" | ", prefix="COORD:").add_to(mapa)

# ── Lugares CONOCIDOS ────────────────────────────────────────
# Azul oscuro por defecto; dorado si es pivote
for nombre, datos in conocidos.items():
    source = datos.get("source", "real")
    lat, lon = datos["lat"], datos["lon"]
    es_pivote = nombre in pivotes_set

    circle_color   = "#8B6914" if es_pivote else "#1a4f8a"
    fill_color     = "#FFD700" if es_pivote else "#1a6fc4"
    label_color    = "#5a3e00" if es_pivote else "#0d2b52"
    label_prefix   = "★ "     if es_pivote else ""
    tooltip_extra  = "<br><b>⭐ Pivote</b>" if es_pivote else ""
    radius         = 12 if es_pivote else 10

    folium.CircleMarker(
        location=[lat, lon],
        radius=radius,
        color=circle_color,
        weight=2,
        fill=True,
        fill_color=fill_color,
        fill_opacity=0.90,
        tooltip=f"<b>{nombre}</b><br>Fuente: {source}{tooltip_extra}",
        popup=folium.Popup(
            f"<b>{nombre}</b><br>Fuente: {source}<br>"
            f"Lat: {lat:.4f} | Lon: {lon:.4f}",
            max_width=220
        )
    ).add_to(mapa)

    folium.Marker(
        location=[lat, lon],
        icon=folium.DivIcon(html=f"""
            <div style="font-family:serif; font-size:11pt; color:{label_color};
                        font-weight:bold; text-shadow:1px 1px 3px white;
                        white-space:nowrap;">
                {label_prefix}{nombre}
            </div>""")
    ).add_to(mapa)

# ── Lugares ESTIMADOS ─────────────────────────────────────────
# Naranja por defecto; dorado si es pivote
for nombre, datos in estimados.items():
    lat, lon = datos["lat"], datos["lon"]
    es_pivote = nombre in pivotes_set

    circle_color   = "#8B6914" if es_pivote else "#a05000"
    fill_color     = "#FFD700" if es_pivote else "#e07b00"
    label_color    = "#5a3e00" if es_pivote else "#6b3300"
    label_prefix   = "★ "     if es_pivote else ""
    tooltip_extra  = "<br><b>⭐ Pivote</b>" if es_pivote else ""
    radius         = 12 if es_pivote else 10

    folium.CircleMarker(
        location=[lat, lon],
        radius=radius,
        color=circle_color,
        weight=2,
        fill=True,
        fill_color=fill_color,
        fill_opacity=0.90,
        tooltip=f"<b>{nombre}</b><br>Posición estimada (Z3){tooltip_extra}",
        popup=folium.Popup(
            f"<b>{nombre}</b><br>Estimado por Z3<br>"
            f"Lat: {lat:.4f} | Lon: {lon:.4f}",
            max_width=220
        )
    ).add_to(mapa)

    folium.Marker(
        location=[lat, lon],
        icon=folium.DivIcon(html=f"""
            <div style="font-family:serif; font-size:11pt; color:{label_color};
                        font-weight:bold; text-shadow:1px 1px 3px white;
                        white-space:nowrap;">
                {label_prefix}{nombre}
            </div>""")
    ).add_to(mapa)

# ── Leyenda ──────────────────────────────────────────────────
leyenda_html = """
<div style="position:fixed; bottom:30px; left:30px; background:white;
            padding:14px 18px; border:2px solid #aaa; border-radius:10px;
            z-index:1000; font-size:13px; font-family:serif; line-height:1.8;">
    <b>Leyenda</b><br>
    <span style="color:#FFD700; font-size:18px;">●</span>
        Pivote (lugar más conectado)<br>
    <span style="color:#1a6fc4; font-size:18px;">●</span>
        Lugar conocido (Pleiades / Wikidata)<br>
    <span style="color:#e07b00; font-size:18px;">●</span>
        Lugar estimado (Z3, anclado a coords reales)<br>
    <span style="color:#888; font-size:18px;">▶</span>
        Ver lugares sin posición determinada →
</div>
"""
mapa.get_root().html.add_child(folium.Element(leyenda_html))

# ── Panel lateral: lugares con posición incierta ─────────────
if inciertos:
    items_html = "\n".join(
        f'<li style="padding:2px 0; border-bottom:1px solid #eee;">'
        f'{"<b style=\"color:#8B6914\">★ " + nombre + "</b>" if nombre in pivotes_set else nombre}'
        f'</li>'
        for nombre in inciertos
    )
    panel_html = f"""
<div id="panel-inciertos"
     style="position:fixed; top:60px; right:0; width:260px; max-height:80vh;
            background:white; border:2px solid #999; border-right:none;
            border-radius:10px 0 0 10px; z-index:1000;
            font-family:serif; font-size:12px; box-shadow:-3px 3px 8px rgba(0,0,0,0.2);
            display:flex; flex-direction:column;">

    <!-- Cabecera clicable -->
    <div onclick="(function(){{
            var b=document.getElementById('pi-body');
            var i=document.getElementById('pi-icon');
            if(b.style.display==='none'){{b.style.display='block';i.textContent='▼';}}
            else{{b.style.display='none';i.textContent='▶';}}
         }})()"
         style="cursor:pointer; background:#f0f0f0; padding:10px 14px;
                border-radius:8px 0 0 0; display:flex; justify-content:space-between;
                align-items:center; font-weight:bold; color:#444;">
        <span>Posición incierta&nbsp;({len(inciertos)})</span>
        <span id="pi-icon">▶</span>
    </div>

    <!-- Cuerpo colapsable -->
    <div id="pi-body" style="display:none; overflow-y:auto; max-height:calc(80vh - 42px);
                              padding:8px 14px;">
        <p style="color:#666; font-size:11px; margin:4px 0 8px 0;">
            Estos lugares aparecen en el texto pero el texto no proporciona
            suficiente contexto geográfico para ubicarlos en el mapa.
        </p>
        <ul style="list-style:none; margin:0; padding:0; color:#333;">
{items_html}
        </ul>
    </div>
</div>
"""
    mapa.get_root().html.add_child(folium.Element(panel_html))

# ============================================================
# 6) GUARDAR
# ============================================================

mapa.save(FILE_OUTPUT)
print(f"\n✅ Mapa histórico completo guardado en: {FILE_OUTPUT}")
print(f"   ● Conocidos (Wikidata/Pleiades) : {len(conocidos)}")
print(f"   ● Estimados (Z3 dentro del área): {len(estimados)}")
print(f"   ▶ Posición incierta (panel)     : {len(inciertos)}")
