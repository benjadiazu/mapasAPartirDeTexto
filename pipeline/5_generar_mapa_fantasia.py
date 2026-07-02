"""
Pipeline step 5: Generate fantasy map using FantasyMapGenerator with city/town
positions taken from output/json/solution_refined.json.

Coordinate conversion:
- solution_refined.json uses mathematical convention (matplotlib): y increases
  upward, so large y = visual top.
- FantasyMapGenerator also uses mathematical convention internally: ny=1 = top.
- Therefore: ny = y / height  (no flip needed)
"""
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _ascii_name(name: str) -> str:
    """Strip diacritics so the C++ font engine (ASCII-only) doesn't crash."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"
_IMG_DIR = _ROOT / "output" / "mapas"
_EXE = _ROOT / "FantasyMapGenerator" / "build" / "map_generation.exe"

# ============================================================
# 1) CARGAR solution_refined.json
# ============================================================

with open(_JSON_DIR / "solution_refined.json", "r", encoding="utf-8") as f:
    refined = json.load(f)

coords = refined["coords"]
width = refined["width"]
height = refined["height"]

# ============================================================
# 2) CONVERTIR A FORMATO locations.json PARA FantasyMapGenerator
#    Todas las ubicaciones se tratan como "towns" (marcadores con nombre).
#    nx = x / width
#    ny = 1.0 - y / height  (flip eje Y: canvas->mapa)
# ============================================================

towns = []
for name, pos in coords.items():
    nx = pos["x"] / width
    ny = pos["y"] / height
    # Clamp to [0.02, 0.98] to keep markers away from map edges
    nx = max(0.02, min(0.98, nx))
    ny = max(0.02, min(0.98, ny))
    towns.append({"name": _ascii_name(name), "nx": round(nx, 6), "ny": round(ny, 6)})

locations = {"cities": [], "towns": towns}

locations_path = _JSON_DIR / "locations_fantasia.json"
with open(locations_path, "w", encoding="utf-8") as f:
    json.dump(locations, f, indent=2, ensure_ascii=False)

print(f"[OK] Locations guardadas en {locations_path} ({len(towns)} ubicaciones)")

# ============================================================
# 3) LLAMAR A FantasyMapGenerator
# ============================================================

_IMG_DIR.mkdir(parents=True, exist_ok=True)
output_path = _IMG_DIR / "mapa_fantasia.png"

if not _EXE.exists():
    print(f"[ERROR] Ejecutable no encontrado: {_EXE}")
    print("   Compila FantasyMapGenerator primero:")
    print("   cd FantasyMapGenerator && cmake -B build && cmake --build build --config Release")
    sys.exit(1)

cmd = [
    str(_EXE),
    "--locations", str(locations_path),
    "--output", str(output_path),
    "--no-borders",
    "--no-arealabels",
    "--timeseed",
    "--verbose",
]

print(f"\n[>>] Ejecutando: {' '.join(cmd)}\n")
result = subprocess.run(cmd, capture_output=False)

if result.returncode == 0:
    print(f"\n[OK] Mapa fantasia generado en {output_path}")
else:
    print(f"\n[ERROR] FantasyMapGenerator termino con codigo {result.returncode}")
    sys.exit(result.returncode)
