# refinar_layout.py
import json
import math
from pathlib import Path

import networkx as nx
import matplotlib.pyplot as plt

_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"
_IMG_DIR = _ROOT / "output" / "mapas"

with open(_JSON_DIR / "solution.json", "r", encoding="utf-8") as f:
    solution = json.load(f)

with open(_JSON_DIR / "map_relations.json", "r", encoding="utf-8") as f:
    original_data = json.load(f)

coords = solution["coords"]
WIDTH = solution["width"]
HEIGHT = solution["height"]

lugares = list(coords.keys())

# usa relaciones del LLM, no de Z3, para no perder edges que Z3 falló en resolver
edges = []
for r in original_data.get("relaciones", []):
    o = r["origen"]
    d = r["destino"]
    if o in lugares and d in lugares:
        edges.append((o, d))

G = nx.Graph()

for p in lugares:
    G.add_node(p)

for a, b in edges:
    G.add_edge(a, b)

initial_pos = {
    p: (
        coords[p]["x"] / WIDTH,
        coords[p]["y"] / HEIGHT
    )
    for p in lugares
}

k = 2.0 / math.sqrt(max(1, len(lugares)))

_ineq_path = _JSON_DIR / "inequalities.json"
if _ineq_path.exists():
    with open(_ineq_path, "r", encoding="utf-8") as _iq:
        pivotes = set(json.load(_iq).get("pivotes", []))
else:
    pivotes = set(original_data.get("pivotes", []))

geo_path = _JSON_DIR / "diccionario_geografico.json"
geo_anchored = set()
if geo_path.exists():
    import json as _json
    import numpy as _np
    with open(geo_path, "r", encoding="utf-8") as _gf:
        _geo = _json.load(_gf)

    _cands = [n for n, info in _geo.items()
              if "lat" in info and "lon" in info and n in initial_pos]

    if _cands:
        _lats_4 = _np.array([_geo[n]["lat"] for n in _cands])
        _lons_4 = _np.array([_geo[n]["lon"] for n in _cands])
        _lat_med4 = float(_np.median(_lats_4))
        _lon_med4 = float(_np.median(_lons_4))
        _dists4   = _np.sqrt((_lats_4 - _lat_med4)**2 + (_lons_4 - _lon_med4)**2)
        _d_med4   = float(_np.median(_dists4))
        _mad4     = float(_np.median(_np.abs(_dists4 - _d_med4)))
        _thresh4  = _d_med4 + 2.5 * _mad4
        geo_anchored  = {n for n, d in zip(_cands, _dists4) if d <= _thresh4}
        _outliers4 = [n for n, d in zip(_cands, _dists4) if d > _thresh4]
        if _outliers4:
            print(f"  Geo-outliers NO fijados en spring_layout: {_outliers4}")

# solo fijar geo-anclados; pivotes sin coords en Z3 pueden estar en posiciones arbitrarias
# y anclarlos arrastraría todos sus vecinos estimados al lugar equivocado
geo_pivotes = pivotes & geo_anchored
non_geo_pivotes = pivotes - geo_anchored
fixed_nodes = list(geo_anchored) if geo_anchored else None

print(f"  Nodos fijados en spring_layout: {len(geo_anchored)} geo-anclados")
if non_geo_pivotes:
    print(f"  Pivotes sin coords (libres en spring): {sorted(non_geo_pivotes)}")
if geo_pivotes:
    print(f"  Pivotes con coords (ya fijados como geo): {sorted(geo_pivotes)}")

refined_pos = nx.spring_layout(
    G,
    pos=initial_pos,
    fixed=fixed_nodes,
    iterations=80,
    k=k,
    seed=42
)


def rescale_positions_proportional(pos_dict):
    xs = [p[0] for p in pos_dict.values()]
    ys = [p[1] for p in pos_dict.values()]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    margin = 40
    avail_w = WIDTH - 2 * margin
    avail_h = HEIGHT - 2 * margin

    scale = min(avail_w / span_x, avail_h / span_y)

    off_x = margin + (avail_w - span_x * scale) / 2
    off_y = margin + (avail_h - span_y * scale) / 2

    scaled = {}
    for node, (x, y) in pos_dict.items():
        sx = off_x + (x - min_x) * scale
        sy = off_y + (y - min_y) * scale
        scaled[node] = {"x": round(sx, 2), "y": round(sy, 2)}

    return scaled


final_coords = rescale_positions_proportional(refined_pos)


def fix_axis_orientation(coords, relaciones, width, height, min_votes=5):
    x_ok = x_tot = y_ok = y_tot = 0

    for r in relaciones:
        o, d = r.get("origen"), r.get("destino")
        tipo = r.get("tipo", "").upper()
        if o not in coords or d not in coords:
            continue
        ox, oy = coords[o]["x"], coords[o]["y"]
        dx, dy = coords[d]["x"], coords[d]["y"]

        if tipo == "ESTE_DE":
            x_ok += 1 if ox > dx else 0; x_tot += 1
        elif tipo == "OESTE_DE":
            x_ok += 1 if ox < dx else 0; x_tot += 1
        elif tipo == "NORTE_DE":
            y_ok += 1 if oy > dy else 0; y_tot += 1
        elif tipo == "SUR_DE":
            y_ok += 1 if oy < dy else 0; y_tot += 1

    flip_x = x_tot >= min_votes and (x_ok / x_tot) < 0.5
    flip_y = y_tot >= min_votes and (y_ok / y_tot) < 0.5

    if flip_x:
        cx = width / 2
        for name in coords:
            coords[name]["x"] = round(2 * cx - coords[name]["x"], 2)
        print(f"  eje X invertido ({x_ok}/{x_tot} ok antes) → corregido")
    else:
        print(f"  eje X: {x_ok}/{x_tot} restricciones satisfechas → correcto")

    if flip_y:
        cy = height / 2
        for name in coords:
            coords[name]["y"] = round(2 * cy - coords[name]["y"], 2)
        print(f"  eje Y invertido ({y_ok}/{y_tot} ok antes) → corregido")
    else:
        print(f"  eje Y: {y_ok}/{y_tot} restricciones satisfechas → correcto")

    return flip_x, flip_y


print("Verificando orientación de ejes...")
if geo_anchored:
    # el geo_seed garantiza orientación correcta para los anclas;
    # aplicar fix_axis_orientation usaría nodos no fijados (Z3 arbitrario)
    # y podría invertir el eje Y de los anclas, rompiendo la calibración en step 7
    print("  (orientación fija por geo_seed — corrección de ejes omitida)")
else:
    fix_axis_orientation(
        final_coords,
        original_data.get("relaciones", []),
        WIDTH, HEIGHT,
    )

refined_solution = {
    "coords": final_coords,
    "CSR_original": solution["CSR"],
    "width": WIDTH,
    "height": HEIGHT
}

out_json = _JSON_DIR / "solution_refined.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(refined_solution, f, indent=2, ensure_ascii=False)

print(f"✅ Layout refinado guardado en {out_json}")

plt.figure(figsize=(18, 10), dpi=220)

plot_pos = {
    p: (final_coords[p]["x"], final_coords[p]["y"])
    for p in lugares
}

nodos_normales = [p for p in lugares if p not in pivotes]
nodos_pivote   = [p for p in lugares if p in pivotes]

nx.draw_networkx_nodes(G, plot_pos, nodelist=nodos_normales,
                       node_size=650, node_color="#4A90D9")
nx.draw_networkx_nodes(G, plot_pos, nodelist=nodos_pivote,
                       node_size=750, node_color="#E8650A",
                       edgecolors="#333333", linewidths=1.5)

nx.draw_networkx_edges(
    G,
    plot_pos,
    width=1.5,
    alpha=0.85
)

nx.draw_networkx_labels(
    G,
    plot_pos,
    font_size=8,
    bbox=dict(facecolor="white", alpha=0.7, edgecolor="none")
)

plt.title("Mapa refinado · force-directed post Z3")
plt.axis("equal")
plt.axis("off")
plt.tight_layout()

_IMG_DIR.mkdir(parents=True, exist_ok=True)
out_svg = _IMG_DIR / "mapa_refinado.svg"
plt.savefig(out_svg, format="svg", bbox_inches="tight")
plt.close()

print(f"✅ SVG final guardado en {out_svg}")
