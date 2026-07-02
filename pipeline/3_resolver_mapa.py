# solver_grafos.py
import json
import math
from pathlib import Path

from z3 import Optimize, Int, Or, If, sat, unknown
from collections import Counter


_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"

# ============================================================
# 1) CARGA
# ============================================================

with open(_JSON_DIR / "inequalities.json", "r", encoding="utf-8") as f:
    ineq_data = json.load(f)

with open(_JSON_DIR / "map_relations.json", "r", encoding="utf-8") as f:
    map_data = json.load(f)

lugares = ineq_data["lugares"]
constraints = ineq_data["constraints"]
params = ineq_data["params"]

WIDTH = params["WIDTH"]
HEIGHT = params["HEIGHT"]
MIN_SEP = params["MIN_SEP"]

seed_layout = map_data.get("seed_layout", {})
clusters = map_data.get("clusters", {})
pivotes = set(map_data.get("pivotes", []))

SOLVE_TIMEOUT_MS = 120000


# ============================================================
# 2) HELPERS
# ============================================================

def add_min_sep(s, dx, dy, d):
    s.add(Or(dx >= d, dx <= -d, dy >= d, dy <= -d))


# ============================================================
#  SOFT CONSTRAINTS — linear score expressions (no quadratics)
# ============================================================

def compute_soft_score(item, dx, dy):
    """Returns a Z3 arithmetic expression (≥ 0) representing how well
    the constraint is satisfied. All terms are linear to keep the
    optimizer fast. Called once per constraint; results are summed
    into a single maximize() call."""
    c = item["constraint"]
    kind = c.get("kind")

    tipo = item.get("tipo", "")
    weight = 3 if tipo in ["NORTE_DE", "SUR_DE", "ESTE_DE", "OESTE_DE"] else 1

    if kind == "directional":
        axis = c["axis"]
        op = c.get("op", ">=")
        margin = c.get("margin", 0)

        expr = dx if axis == "x" else dy

        # margin is already signed (negative for SUR_DE/OESTE_DE)
        if op in (">=", ">"):
            score = expr - margin
        else:
            score = margin - expr
        return weight * If(score > 0, score, 0)

    elif kind in ("proximity", "circular"):
        radius = c.get("max_dist", c.get("radius", 100))
        # Manhattan approximation avoids expensive quadratic terms
        abs_dx = If(dx >= 0, dx, -dx)
        abs_dy = If(dy >= 0, dy, -dy)
        score = radius - abs_dx - abs_dy
        return weight * If(score > 0, score, 0)

    elif kind == "abs_box":
        dx_max = c.get("dx_max", 100)
        dy_max = c.get("dy_max", 100)
        abs_dx = If(dx >= 0, dx, -dx)
        abs_dy = If(dy >= 0, dy, -dy)
        score = (dx_max - abs_dx) + (dy_max - abs_dy)
        return weight * If(score > 0, score, 0)

    return None


# ============================================================
# 3) LAYOUT JERÁRQUICO
# ============================================================

def build_cluster_layout(clusters, width, height):
    if not clusters:
        return {}

    cluster_names = list(clusters.keys())
    n = len(cluster_names)

    margin = int(min(width, height) * 0.1)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)

    cell_w = (width - 2 * margin) / max(1, cols)
    cell_h = (height - 2 * margin) / max(1, rows)

    centers = {}
    for i, cname in enumerate(cluster_names):
        col = i % cols
        row = i // cols
        x = int(margin + cell_w * (col + 0.5))
        y = int(margin + cell_h * (row + 0.5))
        centers[cname] = (x, y)

    return centers


def expand_cluster_seeds(cluster_centers, clusters):
    local_seed = {}

    for cname, places in clusters.items():
        if cname not in cluster_centers:
            continue

        base_x, base_y = cluster_centers[cname]
        ring = 40

        for i, p in enumerate(places):
            angle = (2 * math.pi * i) / max(1, len(places))

            x = int(base_x + ring * math.cos(angle))
            y = int(base_y + ring * math.sin(angle))

            local_seed[p] = {"x": x, "y": y}

    return local_seed


# ============================================================
# 4) CSR REAL (igual que antes)
# ============================================================

def evaluate_constraint(item, coords):
    A = item["origen"]
    B = item["destino"]

    if A not in coords or B not in coords:
        return False

    dx = coords[A]["x"] - coords[B]["x"]
    dy = coords[A]["y"] - coords[B]["y"]

    c = item["constraint"]
    kind = c.get("kind")

    if kind == "directional":
        axis = c["axis"]
        op = c["op"]
        margin = c.get("margin", 0)

        expr = dx if axis == "x" else dy

        ok = True

        if op == ">=":
            ok &= expr >= margin
        elif op == ">":
            ok &= expr > margin
        elif op == "<=":
            ok &= expr <= margin   # margin already negative for SUR_DE/OESTE_DE
        elif op == "<":
            ok &= expr < margin    # margin already negative for SUR_DE/OESTE_DE

        return ok

    elif kind == "proximity":
        max_dist = c.get("max_dist", 100)
        return dx * dx + dy * dy <= max_dist * max_dist

    elif kind == "circular":
        radius = c.get("radius", 100)
        return dx * dx + dy * dy <= radius * radius

    elif kind == "abs_box":
        dx_max = c.get("dx_max", 100)
        dy_max = c.get("dy_max", 100)
        return abs(dx) <= dx_max and abs(dy) <= dy_max

    return False


def compute_real_csr(constraints, coords):
    if not constraints:
        return 1.0, []

    rel_eval = []

    for item in constraints:
        ok = evaluate_constraint(item, coords)

        rel_eval.append({
            "origen": item["origen"],
            "tipo": item["tipo"],
            "destino": item["destino"],
            "satisface": ok
        })

    counter = Counter()

    for r in rel_eval:
        if not r["satisface"]:
            counter[r["tipo"]] += 1

    print("Fallos por tipo:", counter)

    csr = sum(r["satisface"] for r in rel_eval) / len(rel_eval)
    return round(csr, 4), rel_eval


# ============================================================
# 5) SOLVER OPTIMIZADO
# ============================================================

def solve_hybrid():
    s = Optimize()
    s.set(timeout=SOLVE_TIMEOUT_MS)

    x = {}
    y = {}

    for i, p in enumerate(lugares):
        x[p] = Int(f"x_{i}")
        y[p] = Int(f"y_{i}")

        # límites del mapa (HARD)
        s.add(x[p] >= 0, x[p] <= WIDTH)
        s.add(y[p] >= 0, y[p] <= HEIGHT)

    # ========================================================
    # layout inicial
    # ========================================================
    cluster_centers = build_cluster_layout(clusters, WIDTH, HEIGHT)
    hierarchical_seed = expand_cluster_seeds(cluster_centers, clusters)

    final_seed = dict(seed_layout)
    if hierarchical_seed:
        final_seed.update(hierarchical_seed)

    SEED_WINDOW = max(120, min(WIDTH, HEIGHT) // 6)

    for p, coord in final_seed.items():
        if p not in x or p not in pivotes:
            continue

        s.add(x[p] >= coord["x"] - SEED_WINDOW)
        s.add(x[p] <= coord["x"] + SEED_WINDOW)
        s.add(y[p] >= coord["y"] - SEED_WINDOW)
        s.add(y[p] <= coord["y"] + SEED_WINDOW)

    # ========================================================
    # separación mínima (HARD)
    # ========================================================
    seen_pairs = set()

    for item in constraints:
        A = item["origen"]
        B = item["destino"]

        if A not in x or B not in x:
            continue

        pair = tuple(sorted((A, B)))
        if pair in seen_pairs:
            continue

        seen_pairs.add(pair)
        add_min_sep(s, x[A] - x[B], y[A] - y[B], MIN_SEP)

    # ========================================================
    # OPTIMIZACIÓN (SOFT) — un único maximize sobre la suma total
    # ========================================================
    scores = []
    for item in constraints:
        A = item["origen"]
        B = item["destino"]

        if A not in x or B not in x:
            continue

        dx = x[A] - x[B]
        dy = y[A] - y[B]

        sc = compute_soft_score(item, dx, dy)
        if sc is not None:
            scores.append(sc)

    if scores:
        total = scores[0]
        for sc in scores[1:]:
            total = total + sc
        s.maximize(total)

    # ========================================================
    # resolver
    # ========================================================
    result = s.check()
    if result == sat:
        m = s.model()
    elif result == unknown:
        print("⚠️  Timeout del solver — usando mejor solución encontrada hasta ahora")
        m = s.model()
        if not m:
            raise RuntimeError("Timeout sin modelo disponible")
    else:
        raise RuntimeError("No se encontró solución SAT (UNSAT)")

    coords = {
        p: {
            "x": int(m.eval(x[p]).as_long()),
            "y": int(m.eval(y[p]).as_long())
        }
        for p in lugares
    }

    

    csr_real, rel_eval = compute_real_csr(constraints, coords)

    return {
        "coords": coords,
        "CSR": csr_real,
        "total_constraints": len(constraints),
        "width": WIDTH,
        "height": HEIGHT,
        "rel_eval": rel_eval,
        "solver_mode": "optimized_soft_constraints"
    }


# ============================================================
# 6) MAIN
# ============================================================

if __name__ == "__main__":
    solution = solve_hybrid()

    out = _JSON_DIR / "solution.json"

    with open(out, "w", encoding="utf-8") as f:
        json.dump(solution, f, indent=2, ensure_ascii=False)

    print(f"✅ Solución guardada en {out}")
    print(f"CSR real: {solution['CSR']}")
    print(f"Total constraints: {solution['total_constraints']}")
    print(f"Modo: {solution['solver_mode']}")