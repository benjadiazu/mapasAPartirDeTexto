# generar_mapa.py
import json
from pathlib import Path

import networkx as nx
import matplotlib.pyplot as plt

_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"
_IMG_DIR = _ROOT / "output" / "mapas"

# ============================================================
# 1) CARGAR MAPA OFICIAL
# ============================================================

mapa_path = _JSON_DIR / "TierraMedia_GrafoOficial.json"

try:
    with open(mapa_path, "r", encoding="utf-8") as f:
        mapa_data = json.load(f)
except FileNotFoundError:
    print(f"❌ No se encontró el archivo: {mapa_path}")
    exit()

coords = mapa_data["coords"]
WIDTH = mapa_data["width"]
HEIGHT = mapa_data["height"]

lugares = list(coords.keys())

# ============================================================
# 2) CONSTRUIR GRAFO
# ============================================================

G = nx.Graph()

# Añadir nodos
for p in lugares:
    G.add_node(p)

# Nota: Si en el futuro deseas conectar los lugares, puedes definir
# una lista de tuplas (origen, destino) y usar G.add_edge(o, d) aquí.

# Posiciones extraídas directamente del JSON.
# Invertimos el eje Y (HEIGHT - y) para que el Norte quede arriba en el plot.
plot_pos = {
    p: (coords[p]["x"], HEIGHT - coords[p]["y"])
    for p in lugares
}

# ============================================================
# 3) EXPORTAR SVG FINAL
# ============================================================

plt.figure(figsize=(18, 14), dpi=220)

# Dibujar Nodos
nx.draw_networkx_nodes(
    G,
    plot_pos,
    node_size=650,
    node_color="#87CEEB", # Un tono celeste para los nodos
    edgecolors="#333333"
)

# Dibujar Aristas (Actualmente vacío, pero listo por si agregas conexiones)
nx.draw_networkx_edges(
    G,
    plot_pos,
    width=1.5,
    alpha=0.6,
    edge_color="#555555"
)

# Dibujar Etiquetas
nx.draw_networkx_labels(
    G,
    plot_pos,
    font_size=9,
    font_weight="bold",
    bbox=dict(facecolor="white", alpha=0.85, edgecolor="none", boxstyle="round,pad=0.3")
)

plt.title("Mapa de la Tierra Media", fontsize=16, fontweight="bold", pad=20)
plt.axis("equal") # Mantiene la proporción del mapa original
plt.axis("off")   # Oculta los ejes numéricos
plt.tight_layout()

_IMG_DIR.mkdir(parents=True, exist_ok=True)
out_svg = _IMG_DIR / "grafo_mapa_oficial.svg"
plt.savefig(out_svg, format="svg", bbox_inches="tight")
plt.close()

print(f"✅ Mapa SVG generado con éxito y guardado en {out_svg}")