"""
Uso:  python analisis/ver_grafo_oficial.py output/json/CronicasDeNarnia_GrafoOficial.json
"""
import sys
import json
from pathlib import Path
import matplotlib.pyplot as plt

def main():
    if len(sys.argv) < 2:
        print("Uso: python ver_grafo_oficial.py <ruta_al_json>")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"Archivo no encontrado: {json_path}")
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    coords = data["coords"]
    width  = data.get("width",  max(v["x"] for v in coords.values()) + 100)
    height = data.get("height", max(v["y"] for v in coords.values()) + 100)

    xs = [v["x"] for v in coords.values()]
    ys = [height - v["y"] for v in coords.values()]   # invertir Y: norte arriba
    labels = list(coords.keys())

    fig, ax = plt.subplots(figsize=(14, 10))
    ax.scatter(xs, ys, s=80, color="#4A90D9", zorder=3)

    for label, x, y in zip(labels, xs, ys):
        ax.annotate(
            label, (x, y),
            textcoords="offset points", xytext=(6, 4),
            fontsize=7,
            bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", boxstyle="round,pad=0.2")
        )

    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(json_path.stem, fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
