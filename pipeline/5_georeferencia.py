import json
import requests
import time
from pathlib import Path

# ============================================================
# CONFIGURACIÓN DE RUTAS
# ============================================================
_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"

FILE_RELATIONS = _JSON_DIR / "map_relations.json"
FILE_OUTPUT = _JSON_DIR / "diccionario_geografico.json"

# Cabeceras para no ser bloqueados por anti-bots y exigir JSON
HEADERS = {
    "User-Agent": "Georreferenciacion_Historica/1.0",
    "Accept": "application/json"
}

def fallback_wikidata(lugar_es):
    """
    Plan B: Si Pleiades falla, buscamos en Wikidata.
    Wikidata sabe las coordenadas de casi cualquier ciudad romana.
    """
    url_search = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={lugar_es}&language=es&format=json"
    try:
        res = requests.get(url_search, headers=HEADERS, timeout=5)
        data = res.json()
        if data.get("search"):
            # Tomamos el primer resultado (el ID de la entidad, ej. Q11896 para Veyes)
            entity_id = data["search"][0]["id"]
            
            # Consultamos las coordenadas (Propiedad P625 en Wikidata)
            url_entity = f"https://www.wikidata.org/w/api.php?action=wbgetclaims&entity={entity_id}&property=P625&format=json"
            res_ent = requests.get(url_entity, headers=HEADERS, timeout=5)
            data_ent = res_ent.json()
            
            if "P625" in data_ent["claims"]:
                coords = data_ent["claims"]["P625"][0]["mainsnak"]["datavalue"]["value"]
                return {
                    "lat": coords["latitude"],
                    "lon": coords["longitude"],
                    "source": "Wikidata",
                    "id": entity_id
                }
    except Exception as e:
        pass
    return None

def run_georeferencing():
    if not FILE_RELATIONS.exists():
        print(f"❌ Error: Falta {FILE_RELATIONS}")
        return

    with open(FILE_RELATIONS, "r", encoding="utf-8") as f:
        data_relaciones = json.load(f)

    traducciones_pleiades = data_relaciones.get("traducciones_pleiades", {})
    lugares = data_relaciones.get("lugares", [])
    diccionario_geografico = {}

    print(f"Iniciando georreferenciación de {len(lugares)} lugares...")

    for lugar_es in lugares:
        lugar_busqueda = traducciones_pleiades.get(lugar_es, lugar_es)
        print(f"🔍 Buscando: {lugar_es}...", end=" ", flush=True)

        # 1. INTENTO CON PLEIADES
        url_pleiades = f"https://pleiades.stoa.org/search?title={lugar_busqueda}&fmt=json"
        encontrado = False

        try:
            response = requests.get(url_pleiades, headers=HEADERS, timeout=10)

            # Verificamos que realmente sea JSON antes de parsear
            if response.status_code == 200 and "application/json" in response.headers.get("Content-Type", ""):
                resultados = response.json()
                if "features" in resultados and len(resultados["features"]) > 0:
                    for feature in resultados["features"]:
                        if "reprPoint" in feature and feature["reprPoint"] is not None:
                            lon, lat = feature["reprPoint"]
                            diccionario_geografico[lugar_es] = {
                                "lat": lat,
                                "lon": lon,
                                "source": "Pleiades",
                                "id": feature.get("id", ""),
                            }
                            encontrado = True
                            print(f"✅ (Pleiades)")
                            break

            # 2. PLAN B: WIKIDATA (Si Pleiades falló, devolvió HTML o no encontró nada)
            if not encontrado:
                wiki_data = fallback_wikidata(lugar_es)
                if wiki_data:
                    diccionario_geografico[lugar_es] = {
                        "lat": wiki_data["lat"],
                        "lon": wiki_data["lon"],
                        "source": "Wikidata",
                        "id": wiki_data["id"],
                    }
                    encontrado = True
                    print(f"✅ (Wikidata)")
                else:
                    print(f"❌ (Sin coordenadas)")

            time.sleep(0.5) # Cortesía con las APIs

        except Exception as e:
            print(f"🔥 Error en la petición: {e}")

    with open(FILE_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(diccionario_geografico, f, ensure_ascii=False, indent=2)

    print(f"\n¡Proceso terminado! Diccionario guardado en: {FILE_OUTPUT}")

if __name__ == "__main__":
    run_georeferencing()