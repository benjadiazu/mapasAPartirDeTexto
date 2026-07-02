from dotenv import load_dotenv
import json
import time
import unicodedata
import PyPDF2
import os
import re
from pathlib import Path
from collections import defaultdict
from openai import OpenAI
import networkx as nx

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent
_JSON_DIR = _ROOT / "output" / "json"

pdf_path = Path(os.environ.get(
    "INPUT_PDF",
    str(_ROOT / "data" / "textos" / "Historia de Roma Libro 1 al 10 - Tito Livio.pdf")
))
MAX_CHUNKS = 200
MAX_PIVOTES = 5

VALID_TIPOS = {"NORTE_DE", "SUR_DE", "ESTE_DE", "OESTE_DE", "CERCA_DE", "CONECTA"}

INVERSE_REL = {
    "NORTE_DE": "SUR_DE",
    "SUR_DE": "NORTE_DE",
    "ESTE_DE": "OESTE_DE",
    "OESTE_DE": "ESTE_DE",
}

ARTS = {"el", "la", "los", "las", "del", "de", "al", "lo"}

GENERIC_PREFIXES = {
    "ciudad", "pueblo", "aldea", "villa",
    "reino", "imperio", "region", "provincia",
    "territorio", "isla", "mar", "rio", "río",
    "lago", "valle", "bosque", "montana",
    "montaña", "montes", "cordillera",
    "desierto", "puerto", "camino",
    "colina", "monte", "fortaleza",
    "muralla", "campamento"
}

MACRO_GEO_PREFIXES = {
    "ciudad", "pueblo", "aldea", "villa",
    "reino", "imperio", "region", "provincia",
    "territorio", "isla", "mar", "rio", "río",
    "lago", "valle", "bosque", "montana",
    "montaña", "montes", "cordillera",
    "desierto", "puerto", "camino",
    "colina", "monte"
}

GENERIC_NON_MACRO_PREFIXES = {
    "templo", "foro", "curia", "palacio",
    "casa", "torre", "puerta", "muralla",
    "campamento", "fortaleza", "plaza",
    "calle", "tribuna", "senado",
    "capilla", "edificio", "santuario", "higuera",
    # estructuras intra-urbanas / calles romanas
    "ciudadela", "vicus", "clivus",
}

UNIDADES_A_METROS = {
    "m": 1,
    "metro": 1,
    "metros": 1,
    "km": 1000,
    "kilometro": 1000,
    "kilómetro": 1000,
    "kilometros": 1000,
    "kilómetros": 1000,
    "milla": 1480,
    "millas": 1480,
    "estadio": 185,
    "estadios": 185,
    "legua": 5572,
    "leguas": 5572,
    "jornada": 30000,
    "jornadas": 30000,
}


def strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def clean_surface(text) -> str:
    if text is None:
        return ""

    if isinstance(text, dict):
        for k in ["nombre", "place", "lugar", "name", "text"]:
            if k in text:
                text = text[k]
                break
        else:
            return ""

    if isinstance(text, list):
        text = " ".join(str(x) for x in text)

    text = str(text).strip()
    text = re.sub(r"[\"'""''.,;:()\[\]]+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_for_matching(text: str) -> str:
    text = clean_surface(text)
    text = strip_accents(text).lower()
    toks = text.split()
    while toks and toks[0] in ARTS:
        toks.pop(0)
    return " ".join(toks)


def semantic_core(text: str) -> str:
    norm = normalize_for_matching(text)
    toks = norm.split()
    if not toks:
        return ""

    if len(toks) >= 2 and toks[0] in GENERIC_PREFIXES:
        toks = toks[1:]
        while toks and toks[0] in ARTS:
            toks.pop(0)

    return " ".join(toks)


def parse_distance_value(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = strip_accents(str(value).lower()).strip()

    word_map = {
        "un": 1,
        "una": 1,
        "uno": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "media": 0.5,
        "medio": 0.5
    }

    m = re.search(r"\d+(\.\d+)?", s)
    if m:
        return float(m.group())

    for word, num in word_map.items():
        if word in s.split():
            return float(num)

    if "media" in s:
        return 0.5

    return None


def convertir_a_metros(distancia, unidad):
    if distancia is None or unidad is None:
        return None

    clave = strip_accents(str(unidad).strip().lower())
    factor = UNIDADES_A_METROS.get(clave)

    if factor is None:
        return None

    value = parse_distance_value(distancia)
    if value is None:
        return None

    return round(value * factor, 1)


def split_text_by_chapters(text):
    text = text.replace("\r\n", "\n").strip()

    patterns = [
        r"\n\s*[IXVLCDM]+\.\s",
        r"\[\d+(?:,\d+)?\]",
        r"\n\s*\d+\s*\n",
        r"CAPÍTULO\s+[IXVLCDM\d]+",
        r"LIBRO\s+[IXVLCDM\d]+"
    ]

    combined_pattern = "|".join(patterns)

    try:
        parts = re.split(combined_pattern, text, flags=re.IGNORECASE)
    except Exception as e:
        print(f"Error en split: {e}")
        return [text]

    chunks = []

    if parts and len(parts[0].strip()) > 100:
        chunks.append(parts[0].strip())

    for p in parts:
        content = p.strip()
        if len(content) > 50:
            chunks.append(content)

    # Fallback: si no detectó estructura, segmenta por bloques fijos
    if not chunks or len(chunks) <= 1:
        print("DEBUG: No se detectó estructura clara. Segmentando por bloques fijos.")
        chunks = [text[i:i+3000] for i in range(0, len(text), 3000)]

    return chunks


def is_relevant(chunk):
    keywords = [
        "norte", "sur", "este", "oeste", "cerca", "millas",
        "rio", "río", "valle", "bosque", "ciudad",
        "territorio", "isla", "monte", "colina"
    ]
    c = strip_accents(chunk.lower())
    return any(k in c for k in keywords)


system_prompt = """
Extrae TODOS los lugares, territorios y accidentes geográficos del texto proporcionado. Este texto puede ser histórico, del mundo real, de fantasía o ciencia ficción.

OBJETIVO PRINCIPAL (ALTO RECALL):
Extrae la mayor cantidad de entidades espaciales posibles.
Criterio de Inclusión: Si es un espacio físico, región o hito donde un individuo, ejército o personaje puede estar, viajar, cruzar o mirar, EXTRÁELO.
Esto incluye: países, imperios, regiones, accidentes geográficos (montañas, cordilleras, ríos, océanos), asentamientos (ciudades, pueblos, aldeas, campamentos), e hitos específicos (caminos, puentes, bosques, fortalezas).

REGLA DE ORO DE LOS TEXTOS:
Usa SIEMPRE el texto exacto del documento para los nombres de los lugares. No inventes, traduzcas ni resumas los nombres en las listas principales.

RELACIONES Y TOPOLOGÍA (OBLIGATORIO):
Tu objetivo es construir una red conectada de lugares.
REGLA ESTRICTA: TODO lugar extraído DEBE tener al menos una (1) relación con otro lugar. ¡No dejes nodos huérfanos!

JERARQUÍA DE RELACIONES (¡CRÍTICO!):
Debes esforzarte al máximo por usar direcciones cardinales. Usa tu comprensión del texto para deducir la orientación.

Usa estrictamente estos tipos, en este orden de preferencia:
1. Direcciones Cardinales (PRIORIDAD ALTA): NORTE_DE, SUR_DE, ESTE_DE, OESTE_DE.
   - Úsalas siempre que el texto lo indique, o si la narrativa de un viaje sugiere una dirección clara (ej. si marchan hacia el atardecer, es OESTE_DE).
2. CERCA_DE (PRIORIDAD MEDIA): Úsalo para lugares explícitamente vecinos o adyacentes donde la dirección exacta no importa.
3. CONECTA (ÚLTIMO RECURSO): Úsalo SOLO si es absolutamente imposible deducir un punto cardinal o cercanía, pero sabes que los lugares están en la misma ruta narrativa o pertenecen a la misma región. NO abuses de este comodín.

DISTANCIAS (Opcional):
Solo si el texto menciona distancias o tiempos de viaje explícitos:
- distancia: valor numérico puro (ej. 40, 3, 500)
- unidad: (ej. "millas", "días", "kilómetros", "leguas")

EXCLUSIONES EXPLÍCITAS:
- NO extraigas el nombre del mundo/universo completo (ej: "Tierra Media" = el mundo entero, no un lugar específico).
- NO extraigas razas, especies o pueblos como lugares ("Orcos", "Elfos").
- NO extraigas fenómenos cosmológicos ("Mares del cielo", "Vacío").
- Solo incluye lugares donde un personaje físicamente puede estar parado o viajar hacia.

DICCIONARIO DE NORMALIZACIÓN:
Crea un objeto "traducciones_pleiades". La clave es el nombre exacto extraído del texto. El valor es su nombre estandarizado, su equivalente histórico (ej. en latín/inglés para mapas reales) o su nombre oficial en el canon de la obra. Si no requiere normalización, simplemente repite el nombre original.

FORMATO DE SALIDA (JSON ESTRICTO):
{
  "lugares": [
    "Lugar A",
    "Lugar B",
    "Lugar C"
  ],
  "relaciones": [
    {
      "origen": "Lugar A",
      "destino": "Lugar B",
      "tipo": "NORTE_DE",
      "distancia": 15,
      "unidad": "millas"
    },
    {
      "origen": "Lugar B",
      "destino": "Lugar C",
      "tipo": "CONECTA"
    }
  ],
  "traducciones_pleiades": {
    "Lugar A": "Nombre_Estandar_A",
    "Lugar B": "Nombre_Estandar_B",
    "Lugar C": "Lugar C"
  }
}
"""


def choose_best_variant(variants):
    variants = list(set(v for v in variants if v))

    def score(v):
        core_len = len(semantic_core(v).split())
        surface_len = len(normalize_for_matching(v).split())
        return (abs(surface_len - core_len), len(v))

    return min(variants, key=score)


def canonicalize_places(raw_places):
    canonical_groups = defaultdict(set)

    for place in raw_places:
        place_clean = clean_surface(place)
        if not place_clean:
            continue

        core = semantic_core(place_clean)
        if not core:
            continue

        canonical_groups[core].add(place_clean)

    alias_map = {}
    canonical_places = []

    for _, variants in canonical_groups.items():
        best = choose_best_variant(variants)
        canonical_places.append(best)

        for v in variants:
            alias_map[clean_surface(v)] = best

    return sorted(set(canonical_places)), alias_map, canonical_groups


def canonical_relation_signature(origen, tipo, destino, dist, unidad):
    if tipo in INVERSE_REL:
        inv = INVERSE_REL[tipo]
        pair1 = (origen, tipo, destino)
        pair2 = (destino, inv, origen)
        return min(pair1, pair2) + (dist, unidad)
    return (origen, tipo, destino, dist, unidad)


def remap_relations(relations, alias_map):
    remapped = []
    seen = set()

    for r in relations:
        if not isinstance(r, dict):
            continue

        origen_raw = clean_surface(r.get("origen", ""))
        destino_raw = clean_surface(r.get("destino", ""))
        tipo = clean_surface(r.get("tipo", "")).upper()

        if not origen_raw or not destino_raw:
            continue

        if tipo not in VALID_TIPOS:
            continue

        origen = alias_map.get(origen_raw, origen_raw)
        destino = alias_map.get(destino_raw, destino_raw)

        if origen == destino:
            continue

        dist_raw = clean_surface(r.get("distancia"))
        unidad_raw = clean_surface(r.get("unidad"))

        sig = canonical_relation_signature(
            origen,
            tipo,
            destino,
            dist_raw,
            unidad_raw
        )

        if sig in seen:
            continue

        seen.add(sig)

        new_r = {
            "origen": origen,
            "destino": destino,
            "tipo": tipo
        }

        if dist_raw:
            new_r["distancia"] = dist_raw

        if unidad_raw:
            new_r["unidad"] = unidad_raw

        dist_m = convertir_a_metros(dist_raw, unidad_raw)
        if dist_m is not None:
            new_r["distancia_m"] = dist_m

        remapped.append(new_r)

    return remapped


def semantic_bonus(place, mentions, degree, rel_diversity):
    norm = normalize_for_matching(place)
    toks = norm.split()

    if not toks:
        return -5

    score = 0

    if len(toks) >= 2 and toks[0] in MACRO_GEO_PREFIXES:
        score += 4

    core_len = len(semantic_core(place).split())
    if 1 <= core_len <= 3:
        score += 2

    if len(toks) == 1 and degree >= 2:
        score += 2

    if len(toks) <= 2 and mentions >= 5 and degree == 0:
        score -= 4

    if rel_diversity >= 2:
        score += 2

    return score


def build_geo_scores(canonical_places, remapped_relations, full_text):
    text_norm = normalize_for_matching(full_text)

    mentions = {}
    degree = defaultdict(int)
    near_degree = defaultdict(int)
    rel_types = defaultdict(set)

    for place in canonical_places:
        key = re.escape(normalize_for_matching(place))
        mentions[place] = len(re.findall(rf"\b{key}\b", text_norm))

    for rel in remapped_relations:
        o, d, t = rel["origen"], rel["destino"], rel["tipo"]

        degree[o] += 1
        degree[d] += 1
        rel_types[o].add(t)
        rel_types[d].add(t)

        if t == "CERCA_DE":
            near_degree[o] += 1
            near_degree[d] += 1

    geo_scores = {}
    for place in canonical_places:
        diversity = len(rel_types.get(place, set()))
        bonus = semantic_bonus(place, mentions.get(place, 0), degree.get(place, 0), diversity)

        score = (
            3 * mentions.get(place, 0)
            + 2 * degree.get(place, 0)
            + near_degree.get(place, 0)
            + 2 * diversity
            + bonus
        )

        geo_scores[place] = {
            "score_total": score,
            "mentions": mentions.get(place, 0),
            "degree": degree.get(place, 0),
            "near_degree": near_degree.get(place, 0),
            "relation_diversity": diversity,
            "semantic_bonus": bonus,
        }

    return geo_scores


def classify_place(place, metrics):
    norm = normalize_for_matching(place)
    toks = norm.split()

    if not toks:
        return False, "empty"

    first = toks[0]
    score = metrics["score_total"]
    degree = metrics["degree"]
    mentions = metrics["mentions"]
    diversity = metrics["relation_diversity"]

    if first in GENERIC_NON_MACRO_PREFIXES:
        return False, "micro_prefix"
    if len(toks) == 1 and norm in GENERIC_PREFIXES:
        return False, "generic_standalone"
    if score < 2:
        return False, "low_score"
    if mentions >= 6 and degree == 0:
        return False, "narrative_noise"
    if diversity >= 2:
        return True, "diverse_relations"
    if degree >= 2:
        return True, "well_connected"
    if score >= 10:
        return True, "high_score"

    return True, "default_keep"


def filter_places_step3(canonical_places, geo_scores, remapped_relations):
    kept_places = []
    discarded = {}

    for place in canonical_places:
        keep, reason = classify_place(place, geo_scores[place])
        if keep:
            kept_places.append(place)
        else:
            discarded[place] = reason

    kept_set = set(kept_places)
    filtered_relations = [
        r for r in remapped_relations
        if r["origen"] in kept_set and r["destino"] in kept_set
    ]

    return kept_places, filtered_relations, discarded


def infer_place_role(place, metrics, canonical_group):
    toks = normalize_for_matching(place).split()

    degree = metrics["degree"]
    mentions = metrics["mentions"]
    diversity = metrics["relation_diversity"]
    score = metrics["score_total"]
    alias_count = len(canonical_group)

    macro_score = 0
    micro_score = 0

    if len(toks) >= 2:
        macro_score += 2
    if degree >= 2:
        macro_score += 2
    if diversity >= 2:
        macro_score += 2
    if score >= 10:
        macro_score += 2

    if len(toks) == 1 and mentions >= 5 and degree == 0:
        micro_score += 2
    if alias_count <= 1 and mentions <= 2 and degree == 0:
        micro_score += 2
    if len(toks) <= 2 and diversity == 0:
        micro_score += 1

    if macro_score >= micro_score + 2:
        return "macro"
    if micro_score >= macro_score + 2:
        return "micro"
    return "ambiguous"


def looks_like_non_place(place, metrics):
    original = clean_surface(place)
    norm = normalize_for_matching(place)
    toks = norm.split()

    if not toks:
        return True

    degree = metrics["degree"]
    diversity = metrics["relation_diversity"]

    if not any(c.isupper() for c in original):
        return True

    vague_markers = {
        "parte", "lado", "inferior", "superior",
        "nombre", "lleva", "cercanas", "circundantes",
        "mismo", "siguiente", "otra", "redonda"
    }
    if len(toks) >= 2 and any(t in vague_markers for t in toks):
        return True

    starts_with_article = original.lower().startswith(("el ", "la ", "un ", "una ", "las ", "los "))
    if starts_with_article and len(original.split()) >= 4:
        return True

    collective_heads = {
        "pueblo", "ejercito", "caballeria",
        "senado", "enemigo", "aliados",
        "tribu", "dioses",
    }
    RACE_WORDS = {
        "orcos", "elfos", "enanos", "hobbits", "trolls",
        "dragones", "humanos", "hombres", "nazgul"
    }
    if norm in RACE_WORDS:
        return True
    if len(toks) == 2 and toks[0] in collective_heads:
        return True

    _DEIDADES = {
        "apolo", "diana", "esculapio", "hercules", "juno", "jupiter",
        "latona", "marte", "mercurio", "minerva", "neptuno", "quirino",
        "saturno", "tellus", "vulcano", "baco", "ceres", "pluto",
        "proserpina", "pan", "atis", "cibeles", "isis",
        "vesta", "mater", "fauna", "faunus", "jano", "pales", "ops",
        "venus", "diana", "fortuna", "flora", "pomona", "lucina",
    }
    if norm in _DEIDADES or (toks and toks[0] in _DEIDADES):
        return True

    _PRAENOMINA = {
        "cayo", "lucio", "marco", "tito", "publio", "gneo", "quinto",
        "aulo", "manio", "servio", "tiberio", "sexto", "apio",
    }
    if toks and toks[0] in _PRAENOMINA:
        return True

    _PERSONAS = {
        "alejandro magno", "alejandro", "cleopatra", "eneas", "lavinia",
        "pirro", "trebio", "romulo", "remo", "romular",
        "amulio", "numitor", "verginio", "coriolano",
        # reyes y generales no-romanos mencionados en Livio
        "antioco", "dario", "ciro", "filipo", "perseo",
        "pompeyo el grande", "pompeyo", "cesar",
        "tarquinio", "tarquino", "troilo",
        # mitológicos
        "eneas", "romo", "turno",
    }
    if norm in _PERSONAS:
        return True

    _PUEBLOS = {
        # plurales / colectivos
        "etruscos", "marsios", "sabinos", "volscos", "volsines",
        "veyentinos", "veyentina", "samnitas", "galos", "ecuos",
        "latinos", "faliscos", "campanos", "vestinos",
        "fidenenses", "marrucinos", "pelignos", "sidicianos",
        "hernicos", "volsinienses", "auruncianos", "antiates",
        # singulares / adjetivos gentilicios
        "latino", "galo", "etrusco", "sabino", "volsco", "samnita",
        "ecuos", "falisco", "campano", "vestino", "herni",
        # adjetivos geográficos derivados (no son topónimos)
        "acaico", "acaica", "balearico", "balearica",
        "caudino", "caudina", "dalmatico", "dalmatica",
        "numidico", "numidica", "regilense",
        "fidenense", "antiate", "veliterne",
        # tribus originales de Roma (no son topónimos)
        "ramnes", "ticies", "luceres",
    }
    if norm in _PUEBLOS:
        return True

    _ABSTRACTOS = {
        "estado", "estado albano", "estado romano", "estado latino",
        "ciudad natal", "ciudadela", "circo",
        "juegos", "utente", "romular",
        "tesoro", "tesoro publico",
        "laguna infernal", "rio aqueronte",
        "occidente", "oriente", "fondo", "otro veyes",
        "nacion latina",
        # asambleas / lugares de reunión abstractos
        "asamblea", "comicio", "comicios",
        # estructuras militares genéricas
        "pretorio",
        # colinas intra-urbanas de Roma (a escala regional no son topónimos útiles)
        "capitolio", "capitolino", "capitolina",
    }
    if norm in _ABSTRACTOS:
        return True

    _EVENT_HEADS = {"guerra", "batalla", "asedio", "conquista", "tratado", "siglo"}
    if toks and toks[0] in _EVENT_HEADS:
        return True

    _INST_HEADS = {"liga", "nacion", "alianza", "consejo"}
    if toks and toks[0] in _INST_HEADS:
        return True

    _DESC_MODIFIERS = {"actual", "moderna", "moderno", "antiguo", "antigua", "llamado", "llamada"}
    if toks and toks[0] in _DESC_MODIFIERS:
        return True

    _CARDINAL = {"norte", "sur", "este", "oeste"}
    if len(toks) >= 2 and toks[0] in _CARDINAL and toks[1] == "de":
        return True

    _EDITORIAL_WORDS = {
        "library", "press", "publisher", "publishers", "edition", "editions",
        "biblioteca",
    }
    if any(t in _EDITORIAL_WORDS for t in toks):
        return True

    if len(toks) == 1 and norm in GENERIC_PREFIXES:
        return True

    return False


def semantic_validation_step35(final_places, final_relations, geo_scores, canonical_groups):
    kept = []
    discarded = {}

    for place in final_places:
        core = semantic_core(place)
        group = canonical_groups.get(core, {place})

        if looks_like_non_place(place, geo_scores[place]):
            discarded[place] = "semantic_non_place"
            continue

        role = infer_place_role(place, geo_scores[place], group)

        if role == "macro":
            kept.append(place)
        elif role == "ambiguous":
            if geo_scores[place]["degree"] >= 1:
                kept.append(place)
            else:
                discarded[place] = "semantic_ambiguous"
        else:
            discarded[place] = "semantic_micro"

    kept_set = set(kept)

    filtered_relations = [
        r for r in final_relations
        if r["origen"] in kept_set and r["destino"] in kept_set
    ]

    return kept, filtered_relations, discarded


def infer_city_likelihood(place, metrics):
    norm = normalize_for_matching(place)
    toks = norm.split()

    generic_place_heads = {
        "ciudad", "pueblo", "villa", "aldea",
        "territorio", "region", "región",
        "provincia", "monte", "rio", "río",
        "lago", "isla", "bosque", "valle",
        "campos", "praderas", "colinas"
    }

    if len(toks) == 1 and toks[0] in generic_place_heads:
        return False, {"reason": "generic_geographic_noun"}

    if not toks:
        return False, "empty"

    degree = metrics["degree"]
    mentions = metrics["mentions"]
    diversity = metrics["relation_diversity"]
    score = metrics["score_total"]

    city_score = 0
    non_city_score = 0

    if 1 <= len(toks) <= 2:
        city_score += 2
    if degree >= 2:
        city_score += 2
    if diversity >= 2:
        city_score += 2
    if mentions >= 2:
        city_score += 1
    if score >= 10:
        city_score += 2

    if len(toks) >= 3:
        non_city_score += 2
    first = toks[0]
    if first in MACRO_GEO_PREFIXES:
        non_city_score += 2
    if first in GENERIC_NON_MACRO_PREFIXES:
        non_city_score += 3
    if degree <= 1 and diversity == 0:
        non_city_score += 2
    if mentions >= 5 and degree <= 1:
        non_city_score += 2

    return city_score > non_city_score, {
        "city_score": city_score,
        "non_city_score": non_city_score
    }


def city_filter_step38(final_places, final_relations, geo_scores):
    # Deshabilitado: era demasiado agresivo y eliminaba ríos, montes y regiones válidas.
    return final_places, final_relations, {}


def remove_microtoponyms_by_neighborhood(final_places, final_relations):
    G = nx.Graph()

    for p in final_places:
        G.add_node(p)

    for r in final_relations:
        o = r["origen"]
        d = r["destino"]
        if o != d:
            G.add_edge(o, d)

    kept = []
    discarded = {}

    for node in G.nodes():
        neighbors = list(G.neighbors(node))
        degree = len(neighbors)

        if degree == 0:
            discarded[node] = "isolated_no_relations"
            continue

        neighbor_degrees = [G.degree(n) for n in neighbors]
        max_neighbor_degree = max(neighbor_degrees)

        # satélite extremo: 1 sola conexión a un hub que es 5x más central
        if degree == 1 and max_neighbor_degree >= degree * 5:
            discarded[node] = "city_satellite"
            continue

        kept.append(node)

    kept_set = set(kept)

    filtered_relations = [
        r for r in final_relations
        if r["origen"] in kept_set and r["destino"] in kept_set
    ]

    return kept, filtered_relations, discarded


def collapse_intraurban_microplaces(final_places, final_relations, geo_scores):
    G = nx.Graph()

    for p in final_places:
        G.add_node(p)

    for r in final_relations:
        o = r["origen"]
        d = r["destino"]
        if o != d:
            G.add_edge(o, d)

    if len(G.nodes) == 0:
        return final_places, final_relations, {}

    degree_cent = nx.degree_centrality(G)
    between_cent = nx.betweenness_centrality(G)

    kept = []
    discarded = {}

    for node in G.nodes:
        neighbors = list(G.neighbors(node))
        degree = len(neighbors)

        if degree == 0:
            kept.append(node)
            continue

        dominant_neighbors = 0

        for nb in neighbors:
            if (
                degree_cent.get(nb, 0) > degree_cent.get(node, 0) * 2
                and between_cent.get(nb, 0) > between_cent.get(node, 0)
            ):
                dominant_neighbors += 1

        dominance_ratio = dominant_neighbors / degree

        if degree == 1 and dominance_ratio >= 0.95:
            discarded[node] = {
                "reason": "intraurban_microplace",
                "dominance_ratio": round(dominance_ratio, 3),
                "degree": degree
            }
            continue

        kept.append(node)

    kept_set = set(kept)

    filtered_relations = [
        r for r in final_relations
        if r["origen"] in kept_set and r["destino"] in kept_set
    ]

    return kept, filtered_relations, discarded


def select_pivots(filtered_places, geo_scores, filtered_relations):
    if not filtered_places:
        return []

    ranked = sorted(
        filtered_places,
        key=lambda p: (
            geo_scores[p]["score_total"],
            geo_scores[p]["relation_diversity"],
            geo_scores[p]["degree"],
        ),
        reverse=True,
    )

    pivots = [ranked[0]]
    connected_to_first = set()

    for r in filtered_relations:
        if r["origen"] == pivots[0]:
            connected_to_first.add(r["destino"])
        elif r["destino"] == pivots[0]:
            connected_to_first.add(r["origen"])

    for place in ranked[1:]:
        if len(pivots) >= MAX_PIVOTES:
            break
        if place not in connected_to_first:
            pivots.append(place)

    for place in ranked:
        if len(pivots) >= MAX_PIVOTES:
            break
        if place not in pivots:
            pivots.append(place)

    return pivots


def build_seed_layout(pivots):
    if not pivots:
        return {}

    return {
        pivots[0]: {"x": 500, "y": 500}
    }


def build_spatial_topology_graph(final_places, final_relations, geo_scores):
    G = nx.Graph()

    for place in final_places:
        G.add_node(
            place,
            score=geo_scores[place]["score_total"],
            degree_hint=geo_scores[place]["degree"]
        )

    for rel in final_relations:
        o = rel["origen"]
        d = rel["destino"]

        if o == d:
            continue

        G.add_edge(o, d, tipo=rel["tipo"])

    if len(G.nodes) == 0:
        return {
            "graph_meta": {
                "num_nodes": 0,
                "num_edges": 0,
                "density": 0.0,
                "connected_components": 0
            },
            "hub_nodes": [],
            "bridge_nodes": [],
            "clusters": []
        }

    degree_cent = nx.degree_centrality(G)
    between_cent = nx.betweenness_centrality(G)

    hub_nodes = sorted(
        G.nodes,
        key=lambda n: (degree_cent.get(n, 0), geo_scores[n]["score_total"]),
        reverse=True
    )[:5]

    bridge_nodes = sorted(
        G.nodes,
        key=lambda n: between_cent.get(n, 0),
        reverse=True
    )[:5]

    components = list(nx.connected_components(G))

    clusters = {
        f"cluster_{i}": sorted(list(comp))
        for i, comp in enumerate(components)
        if len(comp) >= 2
    }

    density = nx.density(G)

    graph_meta = {
        "num_nodes": G.number_of_nodes(),
        "num_edges": G.number_of_edges(),
        "density": round(density, 4),
        "connected_components": len(components)
    }

    return {
        "graph_meta": graph_meta,
        "hub_nodes": hub_nodes,
        "bridge_nodes": bridge_nodes,
        "clusters": clusters
    }


MACRO_REGION_KEYWORDS = {
    "europa", "asia", "africa",
    "italia", "grecia", "hispania",
    "iberia", "galia", "etruria",
    "latium", "latio"
}

MACRO_SUFFIXES = {
    "mar", "mare", "sea",
    "territorio", "region", "región",
    "provincia", "campo", "llanura"
}

WORLD_LEVEL_WORDS = {
    "media", "medio", "mundo", "universo",
    "creacion", "existencia", "cosmos", "cielo",
    "primera", "segunda", "tercera", "edad"
}


def is_macro_region(place):
    norm = normalize_for_matching(place)
    toks = norm.split()

    if len(toks) == 2 and toks[1] in WORLD_LEVEL_WORDS:
        return True

    if not toks:
        return False

    if norm in MACRO_REGION_KEYWORDS:
        return True

    if len(toks) >= 4:
        return True

    if any(w in toks for w in ["entre", "cerca", "zona", "parte"]):
        return True

    if any(t in MACRO_SUFFIXES for t in toks):
        return True

    return False


def remove_macro_regions(final_places, final_relations, geo_scores):
    G = nx.Graph()

    for p in final_places:
        G.add_node(p)

    for r in final_relations:
        o = r["origen"]
        d = r["destino"]
        if o != d:
            G.add_edge(o, d)

    if len(G.nodes) == 0:
        return final_places, final_relations, {}

    clustering = nx.clustering(G)
    bet = nx.betweenness_centrality(G)

    kept = []
    discarded = {}

    for node in G.nodes:
        degree = G.degree(node)
        local_cluster = clustering.get(node, 0)
        between = bet.get(node, 0)

        region_score = 0

        if degree >= 3:
            region_score += 2
        if local_cluster <= 0.05:
            region_score += 2
        if between >= 0.08:
            region_score += 1

        if region_score >= 4:
            discarded[node] = {
                "reason": "macro_region",
                "degree": degree,
                "clustering": round(local_cluster, 3),
                "betweenness": round(between, 3)
            }
            continue

        kept.append(node)

    kept_set = set(kept)

    filtered_relations = [
        r for r in final_relations
        if r["origen"] in kept_set and r["destino"] in kept_set
    ]

    return kept, filtered_relations, discarded


def remove_explicit_macro_regions(final_places, final_relations):
    kept = []
    discarded = {}

    for p in final_places:
        if is_macro_region(p):
            discarded[p] = "explicit_macro_region"
        else:
            kept.append(p)

    kept_set = set(kept)

    filtered_relations = [
        r for r in final_relations
        if r["origen"] in kept_set and r["destino"] in kept_set
    ]

    return kept, filtered_relations, discarded


def remove_isolated_nodes(final_places, final_relations):
    G = nx.Graph()
    for p in final_places:
        G.add_node(p)
    for r in final_relations:
        if r["origen"] != r["destino"]:
            G.add_edge(r["origen"], r["destino"])

    kept = [p for p in final_places if G.degree(p) > 0]
    kept_set = set(kept)
    filtered_rels = [r for r in final_relations
                     if r["origen"] in kept_set and r["destino"] in kept_set]
    return kept, filtered_rels


def run_pipeline_until_step5():
    text = ""
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"

    chunks = split_text_by_chapters(text)
    relevant_chunks = [c for c in chunks if is_relevant(c)][:MAX_CHUNKS]

    print(f"DEBUG: Se generaron {len(chunks)} chunks en total.")
    print(f"DEBUG: {len(relevant_chunks)} chunks pasaron el filtro de relevancia.")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    results = []

    for i, chunk in enumerate(relevant_chunks):
        print(f"Procesando {i+1}/{len(relevant_chunks)}...")
        try:
            resp = client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chunk},
                ],
                response_format={"type": "json_object"},
            )
            results.append(json.loads(resp.choices[0].message.content))
        except Exception as e:
            print("Error:", e)

        time.sleep(0.5)

    raw_places, raw_relations = [], []
    raw_traducciones = {}

    for r in results:
        raw_places.extend(r.get("lugares", []))
        raw_relations.extend(r.get("relaciones", []))

        chunk_trad = r.get("traducciones_pleiades", {})
        if isinstance(chunk_trad, dict):
            raw_traducciones.update(chunk_trad)

    canonical_places, alias_map, canonical_groups = canonicalize_places(raw_places)
    remapped = remap_relations(raw_relations, alias_map)
    geo_scores = build_geo_scores(canonical_places, remapped, text)

    step3_places, step3_relations, discarded_step3 = filter_places_step3(
        canonical_places, geo_scores, remapped
    )

    final_places_35, final_relations_35, discarded_step35 = semantic_validation_step35(
        step3_places, step3_relations, geo_scores, canonical_groups
    )

    final_places_38, final_relations_38, discarded_step38 = city_filter_step38(
        final_places_35,
        final_relations_35,
        geo_scores
    )

    # primero colapsar intraurbano
    final_places_395, final_relations_395, discarded_step395 = collapse_intraurban_microplaces(
        final_places_38,
        final_relations_38,
        geo_scores
    )

    # después limpiar satélites residuales
    final_places, final_relations, discarded_micro = remove_microtoponyms_by_neighborhood(
        final_places_395,
        final_relations_395
    )

    final_places, final_relations, discarded_macro_explicit = remove_explicit_macro_regions(
        final_places,
        final_relations
    )

    final_places, final_relations, discarded_regions = remove_macro_regions(
        final_places,
        final_relations,
        geo_scores
    )

    final_places, final_relations = remove_isolated_nodes(final_places, final_relations)

    pivots = select_pivots(final_places, geo_scores, final_relations)
    seed_layout = build_seed_layout(pivots)

    topology = build_spatial_topology_graph(
        final_places,
        final_relations,
        geo_scores
    )

    final_translations = {}
    for place in final_places:
        core = semantic_core(place)
        variantes = canonical_groups.get(core, {place})
        trad_encontrada = place

        for var in variantes:
            if var in raw_traducciones and raw_traducciones[var]:
                trad_encontrada = raw_traducciones[var]
                break

        final_translations[place] = trad_encontrada

    return {
        "lugares": final_places,
        "relaciones": final_relations,
        "traducciones_pleiades": final_translations,
        "geo_scores": geo_scores,
        "canonical_groups": {
            k: sorted(v) for k, v in canonical_groups.items()
        },
        "discarded_step3": discarded_step3,
        "discarded_step35": discarded_step35,
        "discarded_step38": discarded_step38,
        "discarded_microtoponyms": discarded_micro,
        "pivotes": pivots,
        "seed_layout": seed_layout,
        "discarded_micro": discarded_micro,
        **topology
    }


if __name__ == "__main__":
    data = run_pipeline_until_step5()

    _JSON_DIR.mkdir(parents=True, exist_ok=True)
    out = _JSON_DIR / "map_relations.json"

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nResultado guardado en {out}")
    print(f"Lugares finales: {len(data['lugares'])}")
    print(f"Lugares finales: {data['lugares']}")
    print(f"Relaciones finales: {len(data['relaciones'])}")
    print(f"Pivotes: {data['pivotes']}")
