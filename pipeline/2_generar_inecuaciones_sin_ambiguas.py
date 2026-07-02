# generar_inecuaciones_sin_ambiguas.py
# Igual que 2_generar_inecuaciones.py pero filtra CERCA_DE, LEJOS_DE y CONECTA
# antes de construir las inecuaciones, para el experimento de relaciones ambiguas.
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
seed_layout = data.get("seed_layout", {})
geo_scores = data.get("geo_scores", {})

print(f"Cargados {len(lugares)} lugares y {len(relaciones)} relaciones.")
print(f"Pivotes disponibles: {len(pivotes)}")

# ------------------------------------------------------------
# 1b) Filtrar relaciones espaciales ambiguas de distancia
# ------------------------------------------------------------
TIPOS_AMBIGUOS = {"CERCA_DE", "LEJOS_DE", "CONECTA"}
n_antes = len(relaciones)
relaciones = [r for r in relaciones if r["tipo"].upper() not in TIPOS_AMBIGUOS]
n_removidas = n_antes - len(relaciones)
print(f"[FILTRO] Relaciones ambiguas removidas: {n_removidas} (tipos: {', '.join(sorted(TIPOS_AMBIGUOS))})")
print(f"[FILTRO] Relaciones restantes para el solver: {len(relaciones)}")

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
# 3) Traducción relación -> constraint serializable
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

    # CERCA_DE, LEJOS_DE y CONECTA ya fueron filtrados antes de llegar aquí.
    # Este bloque queda solo como salvaguarda.
    if tipo in TIPOS_AMBIGUOS:
        return None

    return None


# ------------------------------------------------------------
# 4) Construcción de inequalities.json
# ------------------------------------------------------------
ineq_data = {
    "lugares": lugares,
    "pivotes": pivotes,
    "seed_layout": seed_layout,
    "geo_scores": geo_scores,
    "experimento": "sin_ambiguas",
    "relaciones_removidas": n_removidas,
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
# 5) Guardar JSON final
# ------------------------------------------------------------
output_path = _JSON_DIR / "inequalities.json"

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(ineq_data, f, indent=2, ensure_ascii=False)

print(f"Inecuaciones guardadas en: {output_path}")
print(f"Total constraints: {len(ineq_data['constraints'])}")
print(f"Seed layout disponible: {len(seed_layout)} pivotes posicionados")
