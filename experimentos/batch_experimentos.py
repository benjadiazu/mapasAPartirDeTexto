"""
Batch experiment: ejecuta el pipeline de fantasía N veces con y sin
relaciones espaciales ambiguas (CERCA_DE, LEJOS_DE, CONECTA).

Uso:
    python experimentos/batch_experimentos.py --experimento sin_ambiguas
    python experimentos/batch_experimentos.py --experimento con_ambiguas
    python experimentos/batch_experimentos.py --experimento ambos
    python experimentos/batch_experimentos.py --experimento ambos --runs 5

Resultados guardados en:
    experimentos/resultados/sin_ambiguas/run_01/{json,mapas}/
    experimentos/resultados/con_ambiguas/run_01/{json,mapas}/
    ...
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "pipeline"
OUTPUT_JSON = ROOT / "output" / "json"
OUTPUT_MAPAS = ROOT / "output" / "mapas"
RESULTADOS = ROOT / "experimentos" / "resultados"

PDF = ROOT / "data" / "textos" / "J.R.R. Tolkien La Comunidad del anillo I.pdf"

JSON_FILES = [
    "map_relations.json",
    "inequalities.json",
    "solution.json",
    "solution_refined.json",
    "comparacion_detalle.json",
    "locations_fantasia.json",
]

MAP_FILES = [
    "mapa_refinado.svg",
    "mapa_fantasia.png",
    "comparacion_grafos.png",
    "comparacion_grafos.svg",
    "comparacion_comunes.png",
    "comparacion_comunes.svg",
]

STEP2_ORIGINAL = PIPELINE / "2_generar_inecuaciones.py"
STEP2_FILTRADO = PIPELINE / "2_generar_inecuaciones_sin_ambiguas.py"


def get_steps(sin_ambiguas: bool) -> list:
    step2 = STEP2_FILTRADO if sin_ambiguas else STEP2_ORIGINAL
    return [
        PIPELINE / "1_extraer_relaciones.py",
        step2,
        PIPELINE / "3_resolver_mapa.py",
        PIPELINE / "4_refinar_layout.py",
        PIPELINE / "5_comparar_grafos.py",
        PIPELINE / "5_generar_mapa_fantasia.py",
    ]


def run_step(step: Path, env: dict) -> bool:
    print(f"    → {step.name}", flush=True)
    result = subprocess.run(
        [sys.executable, str(step)],
        env=env,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(f"    [ERROR] {step.name} terminó con código {result.returncode}", flush=True)
        return False
    return True


def save_results(run_dir: Path):
    json_dir = run_dir / "json"
    mapas_dir = run_dir / "mapas"
    json_dir.mkdir(parents=True, exist_ok=True)
    mapas_dir.mkdir(parents=True, exist_ok=True)

    for fname in JSON_FILES:
        src = OUTPUT_JSON / fname
        if src.exists():
            shutil.copy2(src, json_dir / fname)

    for fname in MAP_FILES:
        src = OUTPUT_MAPAS / fname
        if src.exists():
            shutil.copy2(src, mapas_dir / fname)


def run_experiment(name: str, sin_ambiguas: bool, n_runs: int):
    if not PDF.exists():
        print(f"[ERROR] PDF no encontrado: {PDF}", flush=True)
        sys.exit(1)

    steps = get_steps(sin_ambiguas)
    results_dir = RESULTADOS / name

    env = os.environ.copy()
    env["INPUT_PDF"] = str(PDF)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"\n{'='*60}", flush=True)
    print(f"Experimento : {name}", flush=True)
    print(f"Runs        : {n_runs}", flush=True)
    print(f"PDF         : {PDF.name}", flush=True)
    print(f"Resultados  : {results_dir}", flush=True)
    print(f"{'='*60}", flush=True)

    exitosos = 0
    for i in range(1, n_runs + 1):
        run_dir = results_dir / f"run_{i:02d}"
        print(f"\n[{i:02d}/{n_runs}] {name}", flush=True)

        success = True
        for step in steps:
            if not run_step(step, env):
                success = False
                break

        save_results(run_dir)

        if success:
            exitosos += 1
            print(f"    ✓ Guardado en {run_dir.relative_to(ROOT)}", flush=True)
        else:
            print(f"    ✗ Pipeline falló — resultados parciales en {run_dir.relative_to(ROOT)}", flush=True)

    print(f"\nExperimento '{name}' completado: {exitosos}/{n_runs} runs exitosos.", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Ejecuta el pipeline de fantasía en batch para el experimento de relaciones ambiguas."
    )
    parser.add_argument(
        "--experimento",
        choices=["sin_ambiguas", "con_ambiguas", "ambos"],
        default="ambos",
        help="Condición experimental a ejecutar (default: ambos)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Número de ejecuciones por condición (default: 10)",
    )
    args = parser.parse_args()

    if args.experimento in ("sin_ambiguas", "ambos"):
        run_experiment("sin_ambiguas", sin_ambiguas=True, n_runs=args.runs)

    if args.experimento in ("con_ambiguas", "ambos"):
        run_experiment("con_ambiguas", sin_ambiguas=False, n_runs=args.runs)


if __name__ == "__main__":
    main()
