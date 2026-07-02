# generar_inecuaciones.py
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"

# ------------------------------------------------------------
# 1) Cargar salida del Step 4
# ------------------------------------------------------------
input_path = _JSON_DIR / "map_relations.json"

with open(input_path, "r", encoding="utf-8") as f:
    data = json.load(f)

lugares = data.get("lugares", [])
relaciones = data.get("relaciones", [])
pivotes = data.get("pivotes", [])

# Dejamos seed_layout vacío temporalmente para que Z3 resuelva 
# libremente la topología sin entrar en conflicto con coordenadas duras.
seed_layout = data.get("seed_layout", {}) 
#seed_layout = {}
geo_scores = data.get("geo_scores", {})

print(f"Cargados {len(lugares)} lugares y {len(relaciones)} relaciones.")
print(f"Pivotes disponibles: {len(pivotes)}")

# ------------------------------------------------------------
# 2) Parámetros geométricos globales
# ------------------------------------------------------------
N = max(1, len(lugares))
# Aumentamos el tamaño base para dar más "oxígeno" al grafo
SIDE = max(1000, 40 * N)

WIDTH = SIDE
HEIGHT = SIDE

# márgenes y radios base
MARGIN_DIR = max(8, SIDE // 28)
RADIUS_DIR = max(20, SIDE // 3)
DIST_CLOSE = max(14, SIDE // 10) 
DIST_CONNECT = max(16, SIDE // 3)

MIN_SEP = 0

# ------------------------------------------------------------
# 2b) Escala metros -> píxeles (Protegida contra extremos)
# ------------------------------------------------------------
all_dist_m = [
    r["distancia_m"]
    for r in relaciones
    if "distancia_m" in r and r["distancia_m"] is not None
]

if all_dist_m:
    # Límite lógico para el cálculo de escala (ej. 10 km). 
    # Las distancias mayores a esto no arruinarán la escala de los pueblos pequeños.
    DIST_MAX_LOGICA = 10000 
    
    # Filtramos las distancias extremas solo para el cálculo de la escala base
    distancias_razonables = [d for d in all_dist_m if d <= DIST_MAX_LOGICA]
    
    # Si todas las distancias eran extremas, usamos el límite máximo directamente
    max_dist_base = max(distancias_razonables) if distancias_razonables else DIST_MAX_LOGICA
    
    # Usar ~40% del lienzo para la distancia máxima "razonable"
    METROS_POR_PIXEL = max_dist_base / (SIDE * 0.4)
    print(
        f"Escala: {METROS_POR_PIXEL:.1f} m/px "
        f"(basado en dist max razonable: {max_dist_base:.0f}m, lienzo: {SIDE}px)"
    )
else:
    METROS_POR_PIXEL = None


def dist_m_to_px(metros):
    """Convierte metros a píxeles limitando el valor máximo para no romper el solver."""
    if METROS_POR_PIXEL is None or metros is None:
        return None
        
    raw_px = int(metros / METROS_POR_PIXEL)
    
    # LÍMITE DE SEGURIDAD: Ninguna distancia puede exigir más del 60% del lienzo.
    max_allowed_px = int(SIDE * 0.6) 
    
    # Acotamos el valor entre la separación mínima y el límite de seguridad
    return max(MIN_SEP + 1, min(raw_px, max_allowed_px))


# ------------------------------------------------------------
# 3) Traducción relación -> constraint serializable
# ------------------------------------------------------------
def relation_to_constraint(rel):
    """
    Traduce una relación espacial a una restricción geométrica
    que luego Z3 puede convertir directamente.
    """
    tipo = rel["tipo"].upper()
    dpx = dist_m_to_px(rel.get("distancia_m"))

    # --------------------------------------------------------
    # Relaciones direccionales
    # --------------------------------------------------------
    if tipo in ["NORTE_DE", "SUR_DE", "ESTE_DE", "OESTE_DE"]:
        if dpx:
            # Si hay distancia explícita, damos un margen de holgura
            margin = int(dpx * 0.8)       # Mínimo avance
            limit_fwd = int(dpx * 1.2)    # Máximo avance
            limit_lat = int(dpx * 0.5)    # Deriva lateral máxima (cono de búsqueda)
        else:
            # Sin distancia, usamos los rangos globales anchos
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

    # --------------------------------------------------------
    # Cercanía
    # --------------------------------------------------------
    if tipo == "CERCA_DE":
        # Si tiene distancia en metros, la respetamos. 
        # Si no, le damos un radio gigante (50% del lienzo) para que Z3 
        # no se estrese empacando. NetworkX los acercará visualmente después.
        bound = int(dpx * 1.3) if dpx else int(SIDE * 0.5)
        return {
            "kind": "circular",
            "radius": bound,
        }

    # --------------------------------------------------------
    # Conexiones Lógicas (Compatibilidad)
    # --------------------------------------------------------
    if tipo == "CONECTA":
        bound = int((dpx if dpx else DIST_CONNECT) * 1.2)
        return {
            "kind": "abs_box",
            "dx_max": bound,
            "dy_max": bound,
        }

    return None


# ------------------------------------------------------------
# 4) Construcción de inequalities.json
# ------------------------------------------------------------
ineq_data = {
    "lugares": lugares,
    "pivotes": pivotes,
    "seed_layout": seed_layout,
    "geo_scores": geo_scores,
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