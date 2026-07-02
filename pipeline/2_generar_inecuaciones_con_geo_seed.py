# generar_inecuaciones_con_geo_seed.py
# Igual que 2_generar_inecuaciones.py pero inyecta las coordenadas reales
# de diccionario_geografico.json como seed_layout para el solver Z3.
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"

# ------------------------------------------------------------
# 1) Cargar salida del Step 1
# ------------------------------------------------------------
input_path = _JSON_DIR / "map_relations.json"

with open(input_path, "r", encoding="utf-8") as f:
    data = json.load(f)

lugares = data.get("lugares", [])
relaciones = data.get("relaciones", [])
pivotes = data.get("pivotes", [])
geo_scores = data.get("geo_scores", {})

print(f"Cargados {len(lugares)} lugares y {len(relaciones)} relaciones.")
print(f"Pivotes disponibles: {len(pivotes)}")

# ------------------------------------------------------------
# 2) Parámetros geométricos globales
# ------------------------------------------------------------
N = max(1, len(lugares))
SIDE = max(1000, 40 * N)

WIDTH = SIDE
HEIGHT = SIDE

MARGIN_DIR = max(8, SIDE // 28)
RADIUS_DIR = max(20, SIDE // 3)
DIST_CLOSE = max(14, SIDE // 10)
DIST_CONNECT = max(16, SIDE // 3)

MIN_SEP = 0

# ------------------------------------------------------------
# 2b) Escala metros -> píxeles
# ------------------------------------------------------------
all_dist_m = [
    r["distancia_m"]
    for r in relaciones
    if "distancia_m" in r and r["distancia_m"] is not None
]

if all_dist_m:
    DIST_MAX_LOGICA = 10000
    distancias_razonables = [d for d in all_dist_m if d <= DIST_MAX_LOGICA]
    max_dist_base = max(distancias_razonables) if distancias_razonables else DIST_MAX_LOGICA
    METROS_POR_PIXEL = max_dist_base / (SIDE * 0.4)
    print(
        f"Escala: {METROS_POR_PIXEL:.1f} m/px "
        f"(basado en dist max razonable: {max_dist_base:.0f}m, lienzo: {SIDE}px)"
    )
else:
    METROS_POR_PIXEL = None


def dist_m_to_px(metros):
    if METROS_POR_PIXEL is None or metros is None:
        return None
    raw_px = int(metros / METROS_POR_PIXEL)
    max_allowed_px = int(SIDE * 0.6)
    return max(MIN_SEP + 1, min(raw_px, max_allowed_px))


# ------------------------------------------------------------
# 3) Inyectar seed_layout desde coordenadas geográficas reales
# ------------------------------------------------------------
geo_seed_layout = {}
geo_path = _JSON_DIR / "diccionario_geografico.json"

if geo_path.exists():
    with open(geo_path, "r", encoding="utf-8") as f:
        diccionario = json.load(f)

    # Solo usar lugares con coordenadas válidas que estén en la lista de lugares
    lugares_set = set(lugares)
    geo_validos = {
        nombre: info
        for nombre, info in diccionario.items()
        if nombre in lugares_set and "lat" in info and "lon" in info
    }

    if len(geo_validos) >= 2:
        import numpy as _np

        _names_g = list(geo_validos.keys())
        _lats_g  = _np.array([geo_validos[n]["lat"] for n in _names_g])
        _lons_g  = _np.array([geo_validos[n]["lon"] for n in _names_g])

        # Filtro MAD idéntico al de step 7: excluir outliers geográficos
        # (p.ej. Alejandría, Sicilia) de la escala del canvas para que los
        # lugares del área principal queden distribuidos en todo el lienzo.
        _lat_med = float(_np.median(_lats_g))
        _lon_med = float(_np.median(_lons_g))
        _dists   = _np.sqrt((_lats_g - _lat_med)**2 + (_lons_g - _lon_med)**2)
        _d_med   = float(_np.median(_dists))
        _mad     = float(_np.median(_np.abs(_dists - _d_med)))
        _thresh  = _d_med + 2.5 * _mad
        _core    = _dists <= _thresh
        _outliers_seed = [n for n, m in zip(_names_g, _core) if not m]
        if _outliers_seed:
            print(f"[GEO SEED] Outliers excluidos de la escala del canvas: {_outliers_seed}")

        # Escala del canvas fijada solo con el núcleo geográfico
        _lats_core = _lats_g[_core]
        _lons_core = _lons_g[_core]
        min_lat, max_lat = float(_lats_core.min()), float(_lats_core.max())
        min_lon, max_lon = float(_lons_core.min()), float(_lons_core.max())

        lat_range = max_lat - min_lat if max_lat != min_lat else 1.0
        lon_range = max_lon - min_lon if max_lon != min_lon else 1.0

        MARGIN_GEO = int(SIDE * 0.1)
        usable = SIDE - 2 * MARGIN_GEO

        # Solo los del núcleo reciben seed; los outliers los posiciona Z3 libremente.
        _core_names = {n for n, m in zip(_names_g, _core) if m}
        for nombre, info in geo_validos.items():
            if nombre not in _core_names:
                continue
            px_x = int(MARGIN_GEO + (info["lon"] - min_lon) / lon_range * usable)
            # Y invertido: lat grande (norte) → y pequeño (arriba en pantalla)
            px_y = int(MARGIN_GEO + (max_lat - info["lat"]) / lat_range * usable)
            geo_seed_layout[nombre] = {"x": px_x, "y": px_y}

        print(f"[GEO SEED] {len(geo_seed_layout)} lugares con seed "
              f"({len(_outliers_seed)} outliers excluidos de la escala).")
    else:
        print("[GEO SEED] Menos de 2 lugares georeferenciados, seed no aplicado.")
else:
    print(f"[GEO SEED] No se encontró {geo_path}, seed no aplicado.")


# ------------------------------------------------------------
# 3b) Re-selección de pivotes con bonus geográfico
# ------------------------------------------------------------
# Los pivotes de step 1 se eligieron solo por conectividad, lo que puede
# favorecer genéricos como "Ciudad" (≈ Roma) o estructuras intra-urbanas.
# Aquí re-rankeamos multiplicando el score por 3 si el lugar tiene coords
# Wikidata confirmadas. Así un lugar verificado con score medio supera a
# un genérico sin coordenadas con score alto.
_MAX_PIVOTES = 5
_geo_confirmados = set(geo_validos.keys()) if 'geo_validos' in dir() else set()

def _pivote_score(nombre):
    base = geo_scores.get(nombre, {}).get("score_total", 0)
    return base * (3.0 if nombre in _geo_confirmados else 1.0)

if _geo_confirmados:
    pivotes = sorted(lugares, key=_pivote_score, reverse=True)[:_MAX_PIVOTES]
    _geo_piv = [p for p in pivotes if p in _geo_confirmados]
    _est_piv = [p for p in pivotes if p not in _geo_confirmados]
    print(f"[PIVOTES] Re-seleccionados por score×geo: {pivotes}")
    if _geo_piv:
        print(f"  ✓ Con coordenadas: {_geo_piv}")
    if _est_piv:
        print(f"  ~ Sin coordenadas (alta conectividad): {_est_piv}")
else:
    print(f"[PIVOTES] Sin datos geo — manteniendo pivotes de step 1: {pivotes}")


# ------------------------------------------------------------
# 4) Traducción relación -> constraint serializable
# ------------------------------------------------------------
def relation_to_constraint(rel):
    tipo = rel["tipo"].upper()
    dpx = dist_m_to_px(rel.get("distancia_m"))

    if tipo in ["NORTE_DE", "SUR_DE", "ESTE_DE", "OESTE_DE"]:
        if dpx:
            margin = int(dpx * 0.8)
            limit_fwd = int(dpx * 1.2)
            limit_lat = int(dpx * 0.5)
        else:
            margin = MARGIN_DIR
            limit_fwd = RADIUS_DIR
            limit_lat = RADIUS_DIR

        if tipo == "NORTE_DE":
            return {
                "kind": "directional",
                "axis": "y",
                "op": ">=",
                "margin": margin,
                "dx_max": limit_lat,
                "dy_max": limit_fwd,
            }
        if tipo == "SUR_DE":
            return {
                "kind": "directional",
                "axis": "y",
                "op": "<=",
                "margin": -margin,
                "dx_max": limit_lat,
                "dy_max": limit_fwd,
            }
        if tipo == "ESTE_DE":
            return {
                "kind": "directional",
                "axis": "x",
                "op": ">=",
                "margin": margin,
                "dx_max": limit_fwd,
                "dy_max": limit_lat,
            }
        if tipo == "OESTE_DE":
            return {
                "kind": "directional",
                "axis": "x",
                "op": "<=",
                "margin": -margin,
                "dx_max": limit_fwd,
                "dy_max": limit_lat,
            }

    if tipo == "CERCA_DE":
        bound = int(dpx * 1.3) if dpx else int(SIDE * 0.5)
        return {"kind": "circular", "radius": bound}

    if tipo == "CONECTA":
        bound = int((dpx if dpx else DIST_CONNECT) * 1.2)
        return {"kind": "abs_box", "dx_max": bound, "dy_max": bound}

    return None


# ------------------------------------------------------------
# 5) Construcción de inequalities.json
# ------------------------------------------------------------
ineq_data = {
    "lugares": lugares,
    "pivotes": pivotes,
    "seed_layout": geo_seed_layout,
    "geo_scores": geo_scores,
    "experimento": "con_geo_seed",
    "geo_seed_count": len(geo_seed_layout),
    "params": {
        "WIDTH": WIDTH,
        "HEIGHT": HEIGHT,
        "MARGIN_DIR": MARGIN_DIR,
        "RADIUS_DIR": RADIUS_DIR,
        "DIST_CLOSE": DIST_CLOSE,
        "DIST_CONNECT": DIST_CONNECT,
        "MIN_SEP": MIN_SEP,
        **(
            {"metros_por_pixel": round(METROS_POR_PIXEL, 2)}
            if METROS_POR_PIXEL
            else {}
        ),
    },
    "constraints": [],
}

seen = set()

for rel in relaciones:
    c = relation_to_constraint(rel)
    if c is None:
        continue

    signature = (
        rel["origen"],
        rel["tipo"],
        rel["destino"],
        json.dumps(c, sort_keys=True),
    )

    if signature in seen:
        continue
    seen.add(signature)

    entry = {
        "origen": rel["origen"],
        "destino": rel["destino"],
        "tipo": rel["tipo"],
        "constraint": c,
    }

    if "distancia_m" in rel:
        entry["distancia_m"] = rel["distancia_m"]

    ineq_data["constraints"].append(entry)


# ------------------------------------------------------------
# 6) Guardar JSON final
# ------------------------------------------------------------
output_path = _JSON_DIR / "inequalities.json"

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(ineq_data, f, indent=2, ensure_ascii=False)

print(f"Inecuaciones guardadas en: {output_path}")
print(f"Total constraints: {len(ineq_data['constraints'])}")
print(f"Seed layout con {len(geo_seed_layout)} coordenadas geográficas reales")
