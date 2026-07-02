#!/usr/bin/env python3
"""
Compara el grafo generado por el modelo (solucion refinada del paso 4)
con el grafo oficial que mejor coincida (se elige automaticamente).

Produce:
  - output/mapas/comparacion_grafos.svg  (visualizacion solapada)
  - output/mapas/comparacion_grafos.png  (misma imagen en PNG)
  - Imprime en consola las metricas de similitud
"""

import os
import sys
import json
import math
import difflib
import numpy as np
import matplotlib
matplotlib.use("Agg")

# Forzar UTF-8 en consola Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent

GENERATED_JSON = BASE_DIR / "output/json/solution_refined.json"
RELATIONS_JSON = BASE_DIR / "output/json/map_relations.json"

# Grafos oficiales disponibles (hardcoded temporal)
OFFICIAL_GRAPHS = [
    BASE_DIR / "output/json/TierraMedia_GrafoOficial.json",
    BASE_DIR / "output/json/ImperioFinal_GrafoOficial.json",
]

OUTPUT_PNG        = BASE_DIR / "output/mapas/comparacion_grafos.png"
OUTPUT_SVG        = BASE_DIR / "output/mapas/comparacion_grafos.svg"
OUTPUT_PNG_COMMON = BASE_DIR / "output/mapas/comparacion_comunes.png"
OUTPUT_SVG_COMMON = BASE_DIR / "output/mapas/comparacion_comunes.svg"
OUTPUT_DETALLE    = BASE_DIR / "output/json/comparacion_detalle.json"

# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------
FUZZY_THRESHOLD = 0.75   # similitud mínima para aceptar un match fuzzy
BG_COLOR        = "#0d1117"
COLOR_GENERADO  = "#4FC3F7"   # azul claro
COLOR_OFICIAL   = "#EF5350"   # rojo
COLOR_MATCH     = "#66BB6A"   # verde — nodos comunes
COLOR_PIVOTE    = "#FFD54F"   # amarillo — pivotes del modelo


# ---------------------------------------------------------------------------
# Utilidades de datos
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def select_official_graph(gen_nodes: set) -> Path:
    """Elige el grafo oficial con más nodos en común con el grafo generado."""
    best_path, best_count = OFFICIAL_GRAPHS[0], -1
    for path in OFFICIAL_GRAPHS:
        if not path.exists():
            continue
        data = load_json(path)
        off_nodes = set(data["coords"].keys())
        matches = match_nodes(gen_nodes, off_nodes)
        if len(matches) > best_count:
            best_count = len(matches)
            best_path = path
    return best_path


def normalize_coords(coords: dict, width: float, height: float) -> dict:
    """Normaliza coordenadas al rango [0, 1] × [0, 1]."""
    return {
        name: (c["x"] / width, c["y"] / height)
        for name, c in coords.items()
    }


def compute_orientation_accuracy(norm_gen: dict, norm_off: dict, matches: dict,
                                 cerca_threshold: float = 0.15) -> dict:
    """
    Para cada par de nodos emparejados determina la relación espacial dominante
    en el grafo oficial (NORTE_DE, SUR_DE, ESTE_DE, OESTE_DE, CERCA_DE) y
    verifica si esa misma relación se cumple en el grafo generado.

    Usa coordenadas en convención pantalla (Y-down: norte = Y pequeño).
    """
    counts = {t: {"correctas": 0, "total": 0, "pares": []}
              for t in ["NORTE_DE", "SUR_DE", "ESTE_DE", "OESTE_DE", "CERCA_DE"]}

    off_names = list(matches.keys())

    for i in range(len(off_names)):
        for j in range(i + 1, len(off_names)):
            off_A, off_B = off_names[i], off_names[j]
            gen_A, gen_B = matches[off_A], matches[off_B]

            ox_A, oy_A = norm_off[off_A]
            ox_B, oy_B = norm_off[off_B]
            gx_A, gy_A = norm_gen[gen_A]
            gx_B, gy_B = norm_gen[gen_B]

            dx_off = ox_A - ox_B
            dy_off = oy_A - oy_B   # Y-down: negativo → A está más al norte
            dist_off = math.hypot(dx_off, dy_off)

            if dist_off < cerca_threshold:
                tipo = "CERCA_DE"
                correct = math.hypot(gx_A - gx_B, gy_A - gy_B) < cerca_threshold
            elif abs(dx_off) >= abs(dy_off):
                tipo = "ESTE_DE" if dx_off > 0 else "OESTE_DE"
                correct = (dx_off > 0) == (gx_A - gx_B > 0)
            else:
                tipo = "NORTE_DE" if dy_off < 0 else "SUR_DE"
                correct = (dy_off < 0) == (gy_A - gy_B < 0)

            counts[tipo]["total"] += 1
            if correct:
                counts[tipo]["correctas"] += 1
            counts[tipo]["pares"].append({"A": off_A, "B": off_B, "correcto": correct})

    return counts


def procrustes_align(source: dict, target: dict, matches: dict) -> dict:
    """
    Alinea `source` sobre `target` usando análisis de Procrustes completo
    (traslación + escala uniforme + rotación, sin reflexión).

    La transformación se calcula solo con los nodos emparejados y se aplica
    a todos los nodos de source.  matches: {nombre_oficial: nombre_generado}.
    """
    if len(matches) < 3:
        return source

    src_pts = np.array([source[matches[t]] for t in matches], dtype=float)
    tgt_pts = np.array([target[t]           for t in matches], dtype=float)

    src_mean = src_pts.mean(axis=0)
    tgt_mean = tgt_pts.mean(axis=0)
    src_c = src_pts - src_mean
    tgt_c = tgt_pts - tgt_mean

    src_scale = np.sqrt((src_c ** 2).sum() / len(src_c))
    if src_scale < 1e-10:
        return source
    tgt_scale = np.sqrt((tgt_c ** 2).sum() / len(tgt_c))

    src_n = src_c / src_scale
    tgt_n = tgt_c / tgt_scale

    # Rotación óptima: SVD de la matriz de covarianza cruzada
    M = src_n.T @ tgt_n
    U, _, Vt = np.linalg.svd(M)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:   # evitar reflexión
        Vt[-1, :] *= -1
        R = Vt.T @ U.T

    aligned = {}
    for name, (x, y) in source.items():
        pt = np.array([x, y], dtype=float)
        pt_aligned = (R @ ((pt - src_mean) / src_scale)) * tgt_scale + tgt_mean
        aligned[name] = (float(pt_aligned[0]), float(pt_aligned[1]))

    return aligned


def build_edge_set(relations: list, valid_nodes: set) -> set:
    """Convierte lista de relaciones {origen, destino} a aristas sin dirección."""
    edges = set()
    for rel in relations:
        u, v = rel.get("origen", ""), rel.get("destino", "")
        if u in valid_nodes and v in valid_nodes:
            edges.add(tuple(sorted([u, v])))
    return edges


# ---------------------------------------------------------------------------
# Emparejamiento de nodos
# ---------------------------------------------------------------------------

def match_nodes(set_gen: set, set_off: set, threshold: float = FUZZY_THRESHOLD) -> dict:
    """
    Empareja nodos entre los dos grafos.
    Primero busca coincidencia exacta (case-insensitive), luego fuzzy.

    Retorna dict  {nombre_oficial: nombre_generado}.
    """
    matched: dict[str, str] = {}
    gen_lower = {n.lower(): n for n in set_gen}
    unmatched_off = []

    # Pasada 1: exacta
    for off_name in set_off:
        if off_name.lower() in gen_lower:
            matched[off_name] = gen_lower[off_name.lower()]
        else:
            unmatched_off.append(off_name)

    # Pasada 2: fuzzy
    available_gen = [n for n in set_gen if n not in matched.values()]
    for off_name in unmatched_off:
        hits = difflib.get_close_matches(off_name, available_gen, n=1, cutoff=threshold)
        if hits:
            matched[off_name] = hits[0]
            available_gen.remove(hits[0])

    return matched


# ---------------------------------------------------------------------------
# Métricas de similitud
# ---------------------------------------------------------------------------

def _positional_similarity_common(norm_gen: dict, norm_off: dict, matches: dict) -> float:
    """
    Similitud posicional solo para nodos emparejados por nombre.
    Para cada par, calcula distancia euclidiana en [0,1]^2 y promedia.
    """
    if not matches:
        return 0.0
    dists = []
    for off_name, gen_name in matches.items():
        x1, y1 = norm_gen[gen_name]
        x2, y2 = norm_off[off_name]
        dists.append(math.hypot(x1 - x2, y1 - y2))
    avg_dist = sum(dists) / len(dists)
    return max(0.0, 1.0 - avg_dist / math.sqrt(2))


def compute_similarity(norm_gen, norm_off, matches) -> dict:
    n_off    = len(norm_off)
    n_common = len(matches)

    coverage   = n_common / n_off if n_off > 0 else 0.0
    pos_common = _positional_similarity_common(norm_gen, norm_off, matches)

    return {
        "n_gen":      len(norm_gen),
        "n_off":      n_off,
        "n_common":   n_common,
        "coverage":   coverage   * 100,
        "pos_common": pos_common * 100,
    }


# ---------------------------------------------------------------------------
# Visualización
# ---------------------------------------------------------------------------

def _draw_layer(ax, coords: dict, edges: set, color: str,
                z_base: int = 1, font_size: float = 5.5, node_size: int = 70):
    """Dibuja aristas, nodos y etiquetas de un grafo."""
    for u, v in edges:
        if u in coords and v in coords:
            x1, y1 = coords[u]
            x2, y2 = coords[v]
            ax.plot([x1, x2], [1 - y1, 1 - y2],
                    color=color, alpha=0.35, lw=0.9, zorder=z_base)

    xs = [x for x, _ in coords.values()]
    ys = [1 - y for _, y in coords.values()]
    ax.scatter(xs, ys, s=node_size, color=color, alpha=0.85,
               edgecolors="white", linewidths=0.5, zorder=z_base + 1)

    for name, (x, y) in coords.items():
        ax.annotate(
            name, (x, 1 - y),
            fontsize=font_size, color=color, ha="center", va="bottom",
            xytext=(0, 10), textcoords="offset points",
            zorder=z_base + 2, alpha=0.9,
        )


def plot_comparison(
    norm_gen: dict, norm_off: dict,
    gen_edges: set, off_edges: set,
    matches: dict, scores: dict,
    pivotes: set = None,
    show_match_lines: bool = True,
    show_match_rings: bool = True,
    show_gen_edges: bool = True,
    node_size: int = 70,
    font_size: float = 5.5,
) -> plt.Figure:

    pivotes = pivotes or set()

    fig, ax = plt.subplots(figsize=(18, 18))
    ax.set_facecolor(BG_COLOR)
    fig.patch.set_facecolor(BG_COLOR)

    # Líneas punteadas entre nodos emparejados
    if show_match_lines:
        for off_name, gen_name in matches.items():
            if gen_name not in norm_gen:
                continue
            x1, y1 = norm_gen[gen_name]
            x2, y2 = norm_off[off_name]
            ax.plot([x1, x2], [1 - y1, 1 - y2],
                    color=COLOR_MATCH, alpha=0.25, lw=0.8,
                    linestyle="--", zorder=3)

    # Capa del grafo generado: nodos normales (fondo)
    gen_normales = {n: v for n, v in norm_gen.items() if n not in pivotes}
    _draw_layer(ax, gen_normales, gen_edges if show_gen_edges else set(),
                COLOR_GENERADO, z_base=4, font_size=font_size, node_size=node_size)

    # Capa del grafo oficial (encima)
    _draw_layer(ax, norm_off, off_edges, COLOR_OFICIAL, z_base=6,
                font_size=font_size, node_size=node_size)

    # Resaltar nodos emparejados con un anillo verde
    if show_match_rings:
        for off_name, gen_name in matches.items():
            for coords_dict, name in [(norm_gen, gen_name), (norm_off, off_name)]:
                if name in coords_dict:
                    x, y = coords_dict[name]
                    ax.scatter(x, 1 - y, s=node_size * 2.3, color=COLOR_MATCH,
                               edgecolors="white", linewidths=1.0, zorder=8)

    # Pivotes del modelo (encima de todo)
    gen_pivotes = {n: v for n, v in norm_gen.items() if n in pivotes}
    pivot_node_size = int(node_size * 2.9)
    pivot_font_size = font_size * 1.18
    for name, (x, y) in gen_pivotes.items():
        ax.scatter(x, 1 - y, s=pivot_node_size, color=COLOR_PIVOTE,
                   edgecolors="white", linewidths=1.2, zorder=10)
        ax.annotate(
            name, (x, 1 - y),
            fontsize=pivot_font_size, color=COLOR_PIVOTE, fontweight="bold",
            ha="center", va="bottom",
            xytext=(0, 10), textcoords="offset points",
            zorder=11, alpha=1.0,
        )

    # ---- Leyenda ----
    patches = [
        mpatches.Patch(color=COLOR_GENERADO,
                       label=f"Grafo generado por modelo  ({scores['n_gen']} nodos)"),
        mpatches.Patch(color=COLOR_PIVOTE,
                       label=f"Pivotes del modelo              ({len(gen_pivotes)})"),
        mpatches.Patch(color=COLOR_OFICIAL,
                       label=f"Grafo oficial                      ({scores['n_off']} nodos)"),
        mpatches.Patch(color=COLOR_MATCH,
                       label=f"Nodos en común                ({scores['n_common']})"),
    ]
    ax.legend(
        handles=patches, loc="upper right", fontsize=10,
        facecolor="#161b22", labelcolor="white",
        edgecolor="#444", framealpha=0.95,
    )

    # ---- Panel de métricas ----
    sim_text = (
        f"{'━'*40}\n"
        f"  Cobertura de nodos   : {scores['coverage']:.1f}%\n"
        f"  Similitud posicional : {scores['pos_common']:.1f}%\n"
        f"{'━'*40}\n"
        f"  Nodos en común: {scores['n_common']} / {scores['n_off']}"
    )
    ax.text(
        0.01, 0.01, sim_text,
        transform=ax.transAxes, fontsize=10, color="white", va="bottom",
        fontfamily="monospace",
        bbox=dict(
            boxstyle="round,pad=0.6",
            facecolor="#161b22", alpha=0.92, edgecolor="#555",
        ),
    )

    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        "Comparación: Grafo Generado por Modelo  vs  Grafo Oficial",
        color="white", fontsize=15, pad=20, fontweight="bold",
    )

    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("  Comparación de grafos")
    print("=" * 50)

    print("\nCargando datos...")
    gen_data  = load_json(GENERATED_JSON)
    relations = load_json(RELATIONS_JSON)

    env_graph = os.environ.get("OFFICIAL_GRAPH")
    if env_graph and Path(env_graph).exists():
        official_path = Path(env_graph)
        print(f"  Grafo oficial (forzado por env): {official_path.name}")
    else:
        official_path = select_official_graph(set(gen_data["coords"].keys()))
        print(f"  Grafo oficial seleccionado: {official_path.name}")
    off_data   = load_json(official_path)

    # El grafo generado viene de nx.spring_layout (Y crece hacia arriba, conv. matemática).
    # El grafo oficial usa Y hacia abajo (conv. pantalla), igual que el sistema de plot.
    # Invertimos el Y del generado aquí para que ambos queden en la misma orientación
    # antes de dibujar (el plotting aplica 1-y a ambos, correcto para Y-abajo).
    gen_coords = gen_data["coords"]
    gen_h = gen_data["height"]
    gen_w = gen_data["width"]
    norm_gen = {
        name: (c["x"] / gen_w, 1.0 - c["y"] / gen_h)
        for name, c in gen_coords.items()
    }
    norm_off = normalize_coords(off_data["coords"], off_data["width"],  off_data["height"])

    gen_edges = build_edge_set(relations.get("relaciones", []), set(norm_gen))
    off_edges = build_edge_set(off_data.get("relaciones",   []), set(norm_off))

    print(f"  Grafo generado : {len(norm_gen)} nodos, {len(gen_edges)} aristas")
    print(f"  Grafo oficial  : {len(norm_off)} nodos, {len(off_edges)} aristas")

    print("\nEmparejando nodos...")
    matches = match_nodes(set(norm_gen), set(norm_off))

    print(f"  -> {len(matches)} nodos emparejados de {len(norm_off)} oficiales\n")

    if matches:
        print("Correspondencias:")
        for off_name, gen_name in sorted(matches.items()):
            marker = "=" if off_name.lower() == gen_name.lower() else "~"
            print(f"  [{marker}]  {off_name!r:30}  <->  {gen_name!r}")
    else:
        print("  (ningún nodo en común — verifica que el pipeline se ejecutó")
        print("   con el texto correcto antes de comparar)")

    scores = compute_similarity(norm_gen, norm_off, matches)

    sep = "-" * 50
    print(f"\n{sep}")
    print(f"  Cobertura de nodos     : {scores['coverage']:.1f}%")
    print(f"  Similitud posicional   : {scores['pos_common']:.1f}%")
    print(f"{sep}")

    print("\nCalculando precisión de orientaciones...")
    orient_counts = compute_orientation_accuracy(norm_gen, norm_off, matches)
    for tipo, v in orient_counts.items():
        if v["total"] > 0:
            pct = v["correctas"] / v["total"] * 100
            print(f"  {tipo:<12}: {v['correctas']}/{v['total']} ({pct:.0f}%)")

    node_table = [
        {
            "oficial":  off_name,
            "generado": gen_name,
            "off_x": round(norm_off[off_name][0], 3),
            "off_y": round(norm_off[off_name][1], 3),
            "gen_x": round(norm_gen[gen_name][0],  3),
            "gen_y": round(norm_gen[gen_name][1],  3),
        }
        for off_name, gen_name in sorted(matches.items())
    ]

    detalle = {
        "metricas": {
            "cobertura":            round(scores["coverage"],   1),
            "similitud_posicional": round(scores["pos_common"], 1),
            "n_common": scores["n_common"],
            "n_off":    scores["n_off"],
            "n_gen":    scores["n_gen"],
        },
        "nodos_emparejados": node_table,
        "orientaciones":     orient_counts,
    }
    OUTPUT_DETALLE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DETALLE, "w", encoding="utf-8") as f:
        json.dump(detalle, f, ensure_ascii=False, indent=2)

    pivotes = set(relations.get("pivotes", []))

    print("\nGenerando visualización solapada (todos los nodos)...")
    fig = plot_comparison(norm_gen, norm_off, gen_edges, off_edges, matches, scores, pivotes)

    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PNG, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    fig.savefig(OUTPUT_SVG, format="svg", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)

    print("Generando visualización solapada (modelo filtrado a nodos en común)...")
    common_gen_names = set(matches.values())
    norm_gen_common  = {n: v for n, v in norm_gen.items() if n in common_gen_names}
    scores_common = compute_similarity(norm_gen_common, norm_off, matches)

    fig_common = plot_comparison(
        norm_gen_common, norm_off,
        gen_edges, off_edges,
        matches, scores_common, pivotes,
        show_match_lines=True,
        show_match_rings=False,
        show_gen_edges=False,
        node_size=140,
        font_size=8.5,
    )
    fig_common.axes[0].set_title(
        "Comparación (modelo filtrado a nodos en común): Grafo Generado  vs  Grafo Oficial",
        color="white", fontsize=15, pad=20, fontweight="bold",
    )
    fig_common.savefig(OUTPUT_PNG_COMMON, format="png", dpi=150, bbox_inches="tight",
                       facecolor=fig_common.get_facecolor())
    fig_common.savefig(OUTPUT_SVG_COMMON, format="svg", dpi=150, bbox_inches="tight",
                       facecolor=fig_common.get_facecolor())
    plt.close(fig_common)

    print(f"\nArchivos generados:")
    print(f"  {OUTPUT_PNG}")
    print(f"  {OUTPUT_SVG}")
    print(f"  {OUTPUT_PNG_COMMON}")
    print(f"  {OUTPUT_SVG_COMMON}")


if __name__ == "__main__":
    main()
