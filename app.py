from flask import Flask, render_template, request, jsonify, Response, send_file
import subprocess
import os
import uuid
from pathlib import Path

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent

# Almacén temporal de uploads en memoria: upload_id -> (path, original_filename)
_uploads: dict[str, tuple[str, str]] = {}

# Mapeo de nombre de PDF (sin extensión) → grafo oficial a usar en la comparación
_OFFICIAL_GRAPH_MAP: dict[str, str] = {
    "ElCaminoDeLosReyes": "ArchivoDeLasTormentas_GrafoOficial.json",
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    if "pdf" not in request.files:
        return jsonify({"error": "No se encontró archivo PDF"}), 400

    f = request.files["pdf"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "El archivo debe ser PDF"}), 400

    upload_id = uuid.uuid4().hex[:8]
    dest = ROOT / "data" / "textos" / f"input_{upload_id}.pdf"
    f.save(dest)
    original_name = Path(f.filename).stem
    _uploads[upload_id] = (str(dest), original_name)
    return jsonify({"upload_id": upload_id})


@app.route("/run/<upload_id>")
def run(upload_id):
    if upload_id not in _uploads:
        return "Upload no encontrado", 404

    tipo = request.args.get("tipo", "historico")
    pdf_path, original_name = _uploads[upload_id]

    pipeline = ROOT / "pipeline"
    if tipo == "historico":
        steps = [
            pipeline / "1_extraer_relaciones.py",
            pipeline / "5_georeferencia.py",
            pipeline / "2_generar_inecuaciones_con_geo_seed.py",
            pipeline / "3_resolver_mapa_con_geo_seed.py",
            pipeline / "4_refinar_layout.py",
            pipeline / "7_dibujar_mapa_historico_completo.py",
        ]
    else:
        steps = [
            pipeline / "1_extraer_relaciones.py",
            pipeline / "2_generar_inecuaciones.py",
            pipeline / "3_resolver_mapa.py",
            pipeline / "4_refinar_layout.py",
            pipeline / "5_comparar_grafos.py",
            pipeline / "5_generar_mapa_fantasia.py",
        ]

    env = os.environ.copy()
    env["INPUT_PDF"] = pdf_path
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    official_graph = _OFFICIAL_GRAPH_MAP.get(original_name)
    if official_graph:
        env["OFFICIAL_GRAPH"] = str(ROOT / "output" / "json" / official_graph)

    cleanup_pdf = False

    def generate():
        nonlocal cleanup_pdf
        yield "data: Iniciando pipeline...\n\n"

        for step in steps:
            name = step.name
            yield f"data: \n\n"
            yield f"data: ── {name} ──\n\n"

            try:
                proc = subprocess.Popen(
                    ["python", str(step)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    cwd=str(ROOT),
                )
                for line in proc.stdout:
                    yield f"data: {line.rstrip()}\n\n"
                proc.wait()

                if proc.returncode != 0:
                    yield f"data: Error en {name} (código {proc.returncode})\n\n"
                    yield f"event: error\ndata: {name}\n\n"
                    return

                if step == steps[-1]:
                    cleanup_pdf = True

            except Exception as exc:
                yield f"data: Excepción: {exc}\n\n"
                yield f"event: error\ndata: {exc}\n\n"
                return

        if cleanup_pdf:
            try:
                Path(pdf_path).unlink(missing_ok=True)
                _uploads.pop(upload_id, None)
            except Exception as exc:
                yield f"data: Aviso: no se pudo borrar el PDF temporal: {exc}\n\n"

        yield f"event: done\ndata: {tipo}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/output/svg")
def output_svg():
    path = ROOT / "output" / "mapas" / "mapa_refinado.svg"
    if not path.exists():
        return "SVG no generado", 404
    return send_file(path, mimetype="image/svg+xml")


@app.route("/output/mapa")
def output_mapa():
    path = ROOT / "output" / "mapas" / "mapa_historico_completo.html"
    if not path.exists():
        return "Mapa no generado", 404
    return send_file(path)


@app.route("/output/fantasia")
def output_fantasia():
    path = ROOT / "output" / "mapas" / "mapa_fantasia.png"
    if not path.exists():
        return "Mapa fantasía no generado", 404
    return send_file(path, mimetype="image/png")


@app.route("/output/comparacion")
def output_comparacion():
    path = ROOT / "output" / "mapas" / "comparacion_grafos.png"
    if not path.exists():
        return "Comparación no generada", 404
    return send_file(path, mimetype="image/png")


@app.route("/output/comparacion/comunes")
def output_comparacion_comunes():
    path = ROOT / "output" / "mapas" / "comparacion_comunes.png"
    if not path.exists():
        return "Comparación (comunes) no generada", 404
    return send_file(path, mimetype="image/png")


@app.route("/output/comparacion/detalle")
def output_comparacion_detalle():
    path = ROOT / "output" / "json" / "comparacion_detalle.json"
    if not path.exists():
        return "Detalle no generado", 404
    return send_file(path, mimetype="application/json")


if __name__ == "__main__":
    app.run(debug=True, threaded=True, port=5000)
