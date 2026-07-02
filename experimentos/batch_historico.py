"""
Batch experiment: pipeline histórico con y sin seed de coordenadas geográficas reales.

Condición A (con_geo_seed):
    Inyecta las coordenadas lat/lon de Pleiades/Wikidata como semilla para el solver Z3,
    forzando que los lugares se posicionen cerca de sus coordenadas reales.

Condición B (sin_geo_seed):
    Pipeline histórico estándar — el solver resuelve libremente sin información geográfica.

Texto: Historia de Roma Libro 1 al 10 - Tito Livio.pdf

Uso:
    python experimentos/batch_historico.py --experimento con_geo_seed
    python experimentos/batch_historico.py --experimento sin_geo_seed
    python experimentos/batch_historico.py --experimento ambos
    python experimentos/batch_historico.py --experimento ambos --runs 5

Resultados:
    experimentos/resultados/historico_con_geo_seed/run_01/{json,mapas}/
    experimentos/resultados/historico_sin_geo_seed/run_01/{json,mapas}/
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

PDF = ROOT / "data" / "textos" / "Historia de Roma Libro 1 al 10 - Tito Livio.pdf"

JSON_FILES = [
    "map_relations.json",
    "inequalities.json",
    "solution.json",
    "solution_refined.json",
    "diccionario_geografico.json",
]

MAP_FILES = [
    "mapa_historico.html",
    "mapa_refinado.svg",
]

# Pipeline histórico estándar (sin seed geográfico)
STEPS_SIN_SEED = [
    PIPELINE / "1_extraer_relaciones.py",
    PIPELINE / "5_georeferencia.py",
    PIPELINE / "6_dibujar_mapa.py",
    PIPELINE / "2_generar_inecuaciones.py",
    PIPELINE / "3_resolver_mapa.py",
    PIPELINE / "4_refinar_layout.py",
]

# Pipeline con seed geográfico real inyectado al solver
STEPS_CON_SEED = [
    PIPELINE / "1_extraer_relaciones.py",
    PIPELINE / "5_georeferencia.py",
    PIPELINE / "6_dibujar_mapa.py",
    PIPELINE / "2_generar_inecuaciones_con_geo_seed.py",
    PIPELINE / "3_resolver_mapa_con_geo_seed.py",
    PIPELINE / "4_refinar_layout.py",
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


def run_experiment(name: str, con_seed: bool, n_runs: int):
    if not PDF.exists():
        print(f"[ERROR] PDF no encontrado: {PDF}", flush=True)
        sys.exit(1)

    steps = STEPS_CON_SEED if con_seed else STEPS_SIN_SEED
    results_dir = RESULTADOS / name

    env = os.environ.copy()
    env["INPUT_PDF"] = str(PDF)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"\n{'='*60}", flush=True)
    print(f"Experimento : {name}", flush=True)
    print(f"Seed geo    : {'SÍ' if con_seed else 'NO'}", flush=True)
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
        description="Batch experiment: pipeline histórico con y sin seed geográfico real."
    )
    parser.add_argument(
        "--experimento",
        choices=["con_geo_seed", "sin_geo_seed", "ambos"],
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

    if args.experimento in ("con_geo_seed", "ambos"):
        run_experiment("historico_con_geo_seed", con_seed=True, n_runs=args.runs)

    if args.experimento in ("sin_geo_seed", "ambos"):
        run_experiment("historico_sin_geo_seed", con_seed=False, n_runs=args.runs)


if __name__ == "__main__":
    main()
