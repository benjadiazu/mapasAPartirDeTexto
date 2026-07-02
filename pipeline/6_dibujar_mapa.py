import json
import folium
from folium.plugins import MousePosition
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"
_IMG_DIR = _ROOT / "output" / "mapas"
_IMG_DIR.mkdir(parents=True, exist_ok=True)

FILE_INPUT = _JSON_DIR / "diccionario_geografico.json"
FILE_OUTPUT = _IMG_DIR / "mapa_historico.html"

# Ruta relativa desde output/mapas/ hacia data/imagenes_ref/
NOMBRE_IMAGEN_ROSA = "../../data/imagenes_ref/rosa.png" 


def generar_mapa():
    if not FILE_INPUT.exists(): 
        print("❌ No existe el archivo de entrada.")
        return

    with open(FILE_INPUT, "r", encoding="utf-8") as f:
        datos = json.load(f)

    puntos_validos = {k: v for k, v in datos.items() if 'lat' in v and 'lon' in v}
    if not puntos_validos:
        print("❌ No hay puntos con coordenadas.")
        return

    lats = [info['lat'] for info in puntos_validos.values()]
    lons = [info['lon'] for info in puntos_validos.values()]
    centro_lat = sum(lats) / len(lats)
    centro_lon = sum(lons) / len(lons)

    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=6,
        tiles='CartoDB positron',
        attr='Tiles &copy; Esri'
    )

    # ============================================================
    # 1. CUADRÍCULA VISUAL
    # ============================================================
    grid_css = """
    <style>
        .leaflet-container {
            background-image: 
                linear-gradient(to right, rgba(0, 0, 0, 0.15) 1px, transparent 1px),
                linear-gradient(to bottom, rgba(0, 0, 0, 0.15) 1px, transparent 1px);
            background-size: 100px 100px;
        }
    </style>
    """
    mapa.get_root().header.add_child(folium.Element(grid_css))

    # ============================================================
    # 2. ROSA DE LOS VIENTOS (CONTROL TOTAL)
    # ============================================================
    rosa_html = f"""
    <div style="
        position: fixed;
        top: 15px;          /* antes era bottom */
        left: 35px;
        z-index: 9999;
    ">
        <img src="{NOMBRE_IMAGEN_ROSA}" 
            style="width: 240px; opacity: 0.9;">  
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(rosa_html))

    # ============================================================
    # 3. CONTROLES
    # ============================================================
    folium.LayerControl(position='bottomleft', imperial=False).add_to(mapa)
    MousePosition(position='topright', separator=' | ', prefix="COORD:").add_to(mapa)

    # ============================================================
    # 4. PUNTOS Y ETIQUETAS
    # ============================================================
    for lugar, info in puntos_validos.items():

        folium.CircleMarker(
            location=[info['lat'], info['lon']],
            radius=10,
            color='#5D4037',
            weight=2,
            fill=True,
            fill_color='#B71C1C',
            fill_opacity=0.7
        ).add_to(mapa)

        folium.Marker(
            location=[info['lat'], info['lon']],
            icon=folium.DivIcon(
                html=f'''
                <div style="
                    font-family: serif;
                    font-size: 11pt;
                    color: #2E1A12;
                    font-weight: bold;
                    text-shadow: 1px 1px 3px white;
                    white-space: nowrap;
                ">
                    {lugar}
                </div>
                '''
            )
        ).add_to(mapa)

    # ============================================================
    # GUARDAR
    # ============================================================
    mapa.save(FILE_OUTPUT)

    print("✅ Mapa generado correctamente.")
    print(f"📍 Archivo: {FILE_OUTPUT}")
    print("⚠️ Asegúrate de que 'rosa.png' esté en la carpeta img.")


if __name__ == "__main__":
    generar_mapa()