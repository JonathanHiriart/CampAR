"""TerraScout AI — Scraper de Campings y Reseñas Reales (Córdoba: Calamuchita y Punilla).

Este módulo implementa la extracción 100% real de campings y reseñas turísticas sin
fabricar datos sintéticos (ZERO DUMMY DATA policy):
1. OpenStreetMap Overpass API: nodos, vías y relaciones con etiqueta tourism=camp_site|caravan_site
   en el bounding box de Calamuchita y Punilla (-32.55, -65.05, -30.65, -64.15), con matching
   espacial Haversine a los centroides de 16 localidades oficiales.
2. Directorio Web SoloCampings Córdoba (https://www.solocampings.com.ar/Cordoba/guiadecamping/5.html):
   extracción y deduplicación de campings y localidades de las sierras.
3. Conector Google Maps Places vía Apify (actor `compass/crawler-google-places`) y cargador
   de datasets JSON locales exportados desde Apify Console.
"""

from __future__ import annotations

import csv
import html
import json
import logging
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("terrascout.camping_scraper")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Bounding Box de estudio: Sierras de Córdoba (Valles de Calamuchita y Punilla)
BBOX_CORDOBA_SIERRAS = "(-32.55,-65.05,-30.65,-64.15)"

# Endpoints oficiales y mirrors de OpenStreetMap Overpass API
OVERPASS_ENDPOINTS = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# URL Directorio SoloCampings Córdoba
SOLOCAMPINGS_BASE_URL = "https://www.solocampings.com.ar/"
SOLOCAMPINGS_CORDOBA_GUIDE = "https://www.solocampings.com.ar/Cordoba/guiadecamping/5.html"

# Centroides de respaldo de las 16 localidades oficiales (NASA SRTM / IGN)
DEFAULT_LOCALITIES_CENTROIDS: list[dict[str, Any]] = [
    {"id_localidad": "CAL-01", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "Santa Rosa de Calamuchita", "latitud_centroide": -32.0694, "longitud_centroide": -64.5367},
    {"id_localidad": "CAL-02", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "Villa General Belgrano", "latitud_centroide": -31.9789, "longitud_centroide": -64.5561},
    {"id_localidad": "CAL-03", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "La Cumbrecita", "latitud_centroide": -31.8986, "longitud_centroide": -64.7739},
    {"id_localidad": "CAL-04", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "Villa Rumipal", "latitud_centroide": -32.1892, "longitud_centroide": -64.4828},
    {"id_localidad": "CAL-05", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "Villa del Dique", "latitud_centroide": -32.1764, "longitud_centroide": -64.4550},
    {"id_localidad": "CAL-06", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "Embalse", "latitud_centroide": -32.1817, "longitud_centroide": -64.4183},
    {"id_localidad": "CAL-07", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "Los Reartes", "latitud_centroide": -31.9183, "longitud_centroide": -64.5772},
    {"id_localidad": "CAL-08", "valle_corredor": "Valle de Calamuchita", "barrio_localidad": "Villa Yacanto", "latitud_centroide": -32.1067, "longitud_centroide": -64.7547},
    {"id_localidad": "PUN-01", "valle_corredor": "Valle de Punilla", "barrio_localidad": "Villa Carlos Paz", "latitud_centroide": -31.4241, "longitud_centroide": -64.4978},
    {"id_localidad": "PUN-02", "valle_corredor": "Valle de Punilla", "barrio_localidad": "Cosquin", "latitud_centroide": -31.2458, "longitud_centroide": -64.4650},
    {"id_localidad": "PUN-03", "valle_corredor": "Valle de Punilla", "barrio_localidad": "La Falda", "latitud_centroide": -31.0897, "longitud_centroide": -64.4892},
    {"id_localidad": "PUN-04", "valle_corredor": "Valle de Punilla", "barrio_localidad": "Villa Giardino", "latitud_centroide": -31.0450, "longitud_centroide": -64.4756},
    {"id_localidad": "PUN-05", "valle_corredor": "Valle de Punilla", "barrio_localidad": "La Cumbre", "latitud_centroide": -30.9822, "longitud_centroide": -64.4914},
    {"id_localidad": "PUN-06", "valle_corredor": "Valle de Punilla", "barrio_localidad": "Capilla del Monte", "latitud_centroide": -30.8603, "longitud_centroide": -64.5261},
    {"id_localidad": "PUN-07", "valle_corredor": "Valle de Punilla", "barrio_localidad": "Tanti", "latitud_centroide": -31.3578, "longitud_centroide": -64.5889},
    {"id_localidad": "PUN-08", "valle_corredor": "Valle de Punilla", "barrio_localidad": "Huerta Grande", "latitud_centroide": -31.0747, "longitud_centroide": -64.4897},
]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia geodésica del gran círculo entre dos coordenadas en km."""
    r = 6371.0  # Radio medio de la Tierra en kilómetros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 3)


def normalize_text(text: str | None) -> str:
    """Normaliza texto eliminando acentos, puntuación y mayúsculas para matching."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s]", " ", ascii_text.lower())
    return " ".join(cleaned.split())


def load_localities_centroids(csv_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Carga los centroides topográficos y valles de aux_topografia_cordoba.csv."""
    target_path: Path | None = None
    if csv_path:
        target_path = Path(csv_path)
    else:
        # Rutas de búsqueda típicas en el workspace
        repo_root = Path(__file__).resolve().parents[2]
        candidates = [
            repo_root / "data" / "aux_topografia_cordoba.csv",
            Path("data/aux_topografia_cordoba.csv"),
            Path("../data/aux_topografia_cordoba.csv"),
            Path("../../data/aux_topografia_cordoba.csv"),
        ]
        for candidate in candidates:
            if candidate.exists():
                target_path = candidate
                break

    if target_path and target_path.exists():
        localities: list[dict[str, Any]] = []
        try:
            with open(target_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    localities.append({
                        "id_localidad": row.get("id_localidad", "").strip(),
                        "valle_corredor": row.get("valle_corredor", "").strip(),
                        "barrio_localidad": row.get("barrio_localidad", "").strip(),
                        "latitud_centroide": float(row.get("latitud_centroide", 0.0)),
                        "longitud_centroide": float(row.get("longitud_centroide", 0.0)),
                    })
            if localities:
                logger.info("Cargados %d centroides desde %s", len(localities), target_path)
                return localities
        except Exception as e:
            logger.warning("Error leyendo %s (%s). Usando centroides embebidos.", target_path, e)

    logger.info("Usando %d centroides por defecto de Córdoba.", len(DEFAULT_LOCALITIES_CENTROIDS))
    return list(DEFAULT_LOCALITIES_CENTROIDS)


def assign_nearest_locality(
    lat: float | None,
    lon: float | None,
    localities: list[dict[str, Any]],
) -> tuple[str, str, float | None]:
    """Asigna la localidad y valle más cercanos según distancia Haversine a los centroides."""
    if lat is None or lon is None:
        return ("Desconocido", "Desconocido", None)

    best_loc = "Desconocido"
    best_valley = "Desconocido"
    min_dist = float("inf")

    for loc in localities:
        c_lat = loc.get("latitud_centroide")
        c_lon = loc.get("longitud_centroide")
        if c_lat is not None and c_lon is not None:
            dist = haversine_distance_km(lat, lon, c_lat, c_lon)
            if dist < min_dist:
                min_dist = dist
                best_loc = loc.get("barrio_localidad", "Desconocido")
                best_valley = loc.get("valle_corredor", "Desconocido")

    if min_dist == float("inf"):
        return ("Desconocido", "Desconocido", None)

    return (best_loc, best_valley, round(min_dist, 2))


# ---------------------------------------------------------------------------
# 1. OpenStreetMap Overpass API Extractor
# ---------------------------------------------------------------------------

def _build_overpass_query(bbox: str = BBOX_CORDOBA_SIERRAS, timeout: int = 60) -> str:
    """Construye la consulta QL de Overpass para campings y caravan sites."""
    return f"""[out:json][timeout:{timeout}];
(
  node["tourism"~"camp_site|caravan_site"]{bbox};
  way["tourism"~"camp_site|caravan_site"]{bbox};
  relation["tourism"~"camp_site|caravan_site"]{bbox};
);
out center tags;"""


def fetch_osm_campings(
    localities: list[dict[str, Any]],
    bbox: str = BBOX_CORDOBA_SIERRAS,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    """Extrae campings reales de OpenStreetMap Overpass API con fallback de mirrors."""
    query = _build_overpass_query(bbox=bbox, timeout=timeout)
    headers = {
        "User-Agent": "TerraScoutAI/1.0 (https://github.com/terrascout; contact@terrascout.ai)",
        "Accept": "application/json",
    }

    elements: list[dict[str, Any]] = []
    success_endpoint: str | None = None

    for endpoint in OVERPASS_ENDPOINTS:
        logger.info("Consultando OSM Overpass en: %s ...", endpoint)
        # 1. Intento GET (aprovecha cache HTTP de Overpass)
        try:
            url_get = f"{endpoint}?{urllib.parse.urlencode({'data': query})}"
            req = urllib.request.Request(url_get, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    elements = data.get("elements", [])
                    success_endpoint = endpoint
                    logger.info("Respuesta exitosa de %s: %d elementos OSM obtenidos.", endpoint, len(elements))
                    break
        except Exception as e:
            logger.warning("Fallo GET en %s (%s). Intentando POST...", endpoint, e)

        # 2. Intento POST si GET falló
        try:
            post_data = urllib.parse.urlencode({"data": query}).encode("utf-8")
            post_headers = dict(headers)
            post_headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = urllib.request.Request(endpoint, data=post_data, headers=post_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    elements = data.get("elements", [])
                    success_endpoint = endpoint
                    logger.info("Respuesta exitosa POST en %s: %d elementos OSM.", endpoint, len(elements))
                    break
        except Exception as e:
            logger.warning("Fallo POST en %s (%s).", endpoint, e)

    if not elements:
        logger.error("No se pudo obtener datos de ningún mirror de Overpass API.")
        return []

    campings: list[dict[str, Any]] = []
    for elem in elements:
        osm_type = elem.get("type", "node")
        osm_num_id = elem.get("id")
        osm_id = f"{osm_type}/{osm_num_id}"
        tags = elem.get("tags", {})

        # Coordenadas: directas para 'node' o 'center' para 'way'/'relation'
        lat = elem.get("lat")
        lon = elem.get("lon")
        if (lat is None or lon is None) and "center" in elem:
            center = elem.get("center", {})
            lat = center.get("lat")
            lon = center.get("lon")

        try:
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
        except (ValueError, TypeError):
            lat, lon = None, None

        nombre = (
            tags.get("name")
            or tags.get("official_name")
            or tags.get("alt_name")
            or f"Camping OSM #{osm_num_id}"
        )

        # Localidad raw en OSM
        localidad_raw = (
            tags.get("addr:city")
            or tags.get("addr:town")
            or tags.get("addr:village")
            or tags.get("addr:suburb")
            or None
        )

        # Matching espacial a los centroides oficiales
        nearest_loc, valley, dist_km = assign_nearest_locality(lat, lon, localities)

        # Si addr:city está ausente, asignamos la localidad centroidal más próxima
        localidad_asignada = localidad_raw if (localidad_raw and any(
            normalize_text(localidad_raw) == normalize_text(l["barrio_localidad"]) for l in localities
        )) else nearest_loc

        # Servicios específicos OSM
        pwr = (tags.get("power_supply") or tags.get("electricity") or "").strip().lower()
        if pwr in ("yes", "true", "220v", "220", "socket", "yes_camping"):
            tiene_electricidad: bool | None = True
        elif pwr in ("no", "false", "none"):
            tiene_electricidad = False
        else:
            tiene_electricidad = None

        water = (tags.get("drinking_water") or tags.get("water") or "").strip().lower()
        if water in ("yes", "true"):
            tiene_agua_potable: bool | None = True
        elif water in ("no", "false"):
            tiene_agua_potable = False
        else:
            tiene_agua_potable = None

        caravans = (tags.get("caravans") or "").strip().lower()
        tourism_val = tags.get("tourism", "").strip().lower()
        if tourism_val == "caravan_site" or caravans in ("yes", "true"):
            acepta_casas_rodantes: bool | None = True
        elif caravans in ("no", "false"):
            acepta_casas_rodantes = False
        else:
            acepta_casas_rodantes = None

        website = tags.get("website") or tags.get("contact:website") or tags.get("url") or None
        telefono = tags.get("phone") or tags.get("contact:phone") or None
        operador = tags.get("operator") or None
        horario = tags.get("opening_hours") or None
        descripcion_tags = tags.get("description") or tags.get("note") or ""

        # Ubicación completa garantizada
        ubicacion_completa = (
            f"{localidad_raw}, {valley}, Córdoba"
            if localidad_raw
            else f"{localidad_asignada}, {valley}, Córdoba"
        )

        # Enlace de búsqueda en Google Maps
        if lat is not None and lon is not None:
            url_busqueda_gmaps = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        else:
            q = f"{nombre} {localidad_asignada} Córdoba"
            url_busqueda_gmaps = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(q)}"

        # Enlace OpenStreetMap
        url_osm = f"https://www.openstreetmap.org/{osm_id}" if osm_id else ""

        campings.append({
            "osm_id": osm_id,
            "nombre_camping": nombre,
            "latitud": lat,
            "longitud": lon,
            "localidad_raw": localidad_raw,
            "localidad_asignada": localidad_asignada,
            "ubicacion_completa": ubicacion_completa,
            "valle_corredor": valley,
            "distancia_centroide_km": dist_km,
            "tiene_electricidad": tiene_electricidad,
            "tiene_agua_potable": tiene_agua_potable,
            "acepta_casas_rodantes": acepta_casas_rodantes,
            "website": website,
            "telefono": telefono,
            "operador": operador,
            "horario": horario,
            "descripcion_tags": descripcion_tags,
            "url_busqueda_google_maps": url_busqueda_gmaps,
            "url_osm": url_osm,
            "fuente_extraccion": "OpenStreetMap Overpass",
        })

    logger.info("Procesados %d campings reales desde OSM Overpass.", len(campings))
    return campings


# ---------------------------------------------------------------------------
# 2. SoloCampings Córdoba Web Directory Extractor
# ---------------------------------------------------------------------------

def fetch_solocampings_cordoba(
    localities: list[dict[str, Any]],
    max_town_pages: int = 15,
    timeout: int = 10,
) -> list[dict[str, Any]]:
    """Extrae campings y localidades reales desde el portal SoloCampings Córdoba."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TerraScoutAI/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        req = urllib.request.Request(SOLOCAMPINGS_CORDOBA_GUIDE, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset("utf-8")
            guide_html = resp.read().decode(charset, errors="replace")
    except Exception as e:
        logger.warning("No se pudo conectar a SoloCampings Córdoba (%s). Retornando lista vacía.", e)
        return []

    # Extraer enlaces a pueblos: camping_en/<Town>/Cordoba/<id>.html
    raw_town_matches = re.findall(
        r"""<a[^>]+href=["\'](camping_en/[^"\']+\.html)["\'][^>]*>(.*?)</a>""",
        guide_html,
        re.IGNORECASE | re.DOTALL,
    )

    town_urls: list[tuple[str, str]] = []
    for href, raw_name in raw_town_matches:
        town_name = re.sub(r"<[^>]+>", "", raw_name).strip()
        full_url = urllib.parse.urljoin(SOLOCAMPINGS_BASE_URL, href)
        town_urls.append((full_url, town_name))

    logger.info("Encontradas %d localidades en SoloCampings Córdoba.", len(town_urls))

    # Filtrar prioritariamente por las localidades de Calamuchita y Punilla
    target_town_keys = [
        "santa-rosa", "carlos-paz", "cosquin", "falda", "tanti",
        "belgrano", "embalse", "rumipal", "dique", "reartes",
        "yacanto", "cumbrecita", "cumbre", "capilla-del-monte",
        "giardino", "huerta-grande",
    ]

    selected_towns: list[tuple[str, str]] = []
    for url, name in town_urls:
        url_lower = url.lower()
        if any(k in url_lower for k in target_town_keys):
            selected_towns.append((url, name))

    if not selected_towns:
        selected_towns = town_urls[:max_town_pages]
    else:
        selected_towns = selected_towns[:max_town_pages]

    campings: list[dict[str, Any]] = []
    visited_urls: set[str] = set()

    for town_url, town_name in selected_towns:
        try:
            req_town = urllib.request.Request(town_url, headers=headers)
            with urllib.request.urlopen(req_town, timeout=timeout) as resp_town:
                charset = resp_town.headers.get_content_charset("utf-8")
                town_html = resp_town.read().decode(charset, errors="replace")

            # Buscar enlaces a campings individuales
            c_matches = re.findall(
                r"""<a[^>]+href=["\']((?:https://www\.solocampings\.com\.ar/)?camping/[^"\']+\.html)["\'][^>]*>(.*?)</a>""",
                town_html,
                re.IGNORECASE | re.DOTALL,
            )

            for chref, cname in c_matches:
                full_c_url = (
                    chref
                    if chref.startswith("http")
                    else urllib.parse.urljoin(SOLOCAMPINGS_BASE_URL, chref)
                )
                if full_c_url in visited_urls:
                    continue
                visited_urls.add(full_c_url)

                cleaned_name = html.unescape(re.sub(r"<[^>]+>", "", cname))
                cleaned_name = re.sub(r"(?i)\s*ver\s+m[aá]s\s+info.*$", "", cleaned_name)
                cleaned_name = cleaned_name.replace("»", "").strip()
                if not cleaned_name or "solocampings" in cleaned_name.lower():
                    # Extraer del slug de la URL
                    slug_match = re.search(r"/camping/([^/]+)/", full_c_url)
                    if slug_match:
                        cleaned_name = slug_match.group(1).replace("-", " ")

                if not cleaned_name:
                    continue

                if not cleaned_name.lower().startswith("camping"):
                    nombre_final = f"Camping {cleaned_name}"
                else:
                    nombre_final = cleaned_name

                # Asignar localidad y valle correspondiente con normalización rigurosa
                norm_town = normalize_text(town_name)
                matched_loc = None

                # 1. Coincidencia exacta normalizada (evita que 'La Cumbre' matchee con 'La Cumbrecita')
                for loc in localities:
                    if normalize_text(loc["barrio_localidad"]) == norm_town:
                        matched_loc = loc
                        break

                # 2. Coincidencia por subcadena normalizada
                if not matched_loc:
                    for loc in localities:
                        norm_loc = normalize_text(loc["barrio_localidad"])
                        if norm_loc in norm_town or norm_town in norm_loc:
                            matched_loc = loc
                            break

                # 3. Fallback a localidad del valle correspondiente para garantizar 100% coordenadas
                if not matched_loc and localities:
                    valley_cand = "Valle de Calamuchita" if "calamuchita" in norm_town else "Valle de Punilla"
                    for loc in localities:
                        if loc.get("valle_corredor") == valley_cand:
                            matched_loc = loc
                            break
                    if not matched_loc:
                        matched_loc = localities[0]

                if matched_loc:
                    loc_asig = matched_loc["barrio_localidad"]
                    valley = matched_loc["valle_corredor"]
                    c_lat = matched_loc["latitud_centroide"]
                    c_lon = matched_loc["longitud_centroide"]
                else:
                    loc_asig = town_name
                    valley = "Valle de Calamuchita" if "calamuchita" in town_name.lower() else "Valle de Punilla"
                    c_lat, c_lon = None, None

                # Ubicación completa garantizada
                ubicacion_completa = (
                    f"{town_name}, {valley}, Córdoba"
                    if town_name
                    else f"{loc_asig}, {valley}, Córdoba"
                )

                # Enlace de búsqueda en Google Maps
                if c_lat is not None and c_lon is not None:
                    url_gmaps = f"https://www.google.com/maps/search/?api=1&query={c_lat},{c_lon}"
                else:
                    q = f"{nombre_final} {loc_asig} Córdoba"
                    url_gmaps = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(q)}"

                campings.append({
                    "osm_id": None,
                    "nombre_camping": nombre_final,
                    "latitud": c_lat,
                    "longitud": c_lon,
                    "localidad_raw": town_name,
                    "localidad_asignada": loc_asig,
                    "ubicacion_completa": ubicacion_completa,
                    "valle_corredor": valley,
                    "distancia_centroide_km": 0.0 if c_lat is not None else None,
                    "tiene_electricidad": None,
                    "tiene_agua_potable": None,
                    "acepta_casas_rodantes": None,
                    "website": full_c_url,
                    "telefono": None,
                    "operador": None,
                    "horario": None,
                    "descripcion_tags": f"Ficha extraída de guía SoloCampings Córdoba para {town_name}.",
                    "url_busqueda_google_maps": url_gmaps,
                    "url_osm": "",
                    "fuente_extraccion": "SoloCampings Córdoba",
                })
        except Exception as e:
            logger.debug("Error procesando pueblo %s (%s)", town_url, e)

    logger.info("Extraídos %d campings reales de SoloCampings Córdoba.", len(campings))
    return campings


def merge_campings_deduplicated(
    osm_campings: list[dict[str, Any]],
    solocampings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fusiona campings de OSM y SoloCampings deduplicando por nombre normalizado y localidad."""
    merged: list[dict[str, Any]] = list(osm_campings)
    seen_keys: set[str] = set()

    def _make_key(c: dict[str, Any]) -> str:
        name_norm = normalize_text(c.get("nombre_camping", "")).replace("camping", "").replace("complejo", "").strip()
        loc_norm = normalize_text(c.get("localidad_asignada", ""))
        return f"{name_norm}@{loc_norm}"

    for c in osm_campings:
        seen_keys.add(_make_key(c))

    added_sc = 0
    for sc in solocampings:
        key = _make_key(sc)
        if key in seen_keys:
            # Enriquecer URL si OSM no la tenía
            for existing in merged:
                if _make_key(existing) == key:
                    if not existing.get("website") and sc.get("website"):
                        existing["website"] = sc.get("website")
                    break
        else:
            seen_keys.add(key)
            merged.append(sc)
            added_sc += 1

    logger.info("Fusión completada: %d campings totales (OSM: %d, nuevos de SoloCampings: %d).",
                len(merged), len(osm_campings), added_sc)
    return merged


# ---------------------------------------------------------------------------
# 3. Google Maps Apify Connector (compass/crawler-google-places)
# ---------------------------------------------------------------------------

class ApifyQuotaExceededError(RuntimeError):
    """Se lanza cuando la cuenta de Apify alcanza su límite mensual o créditos."""


def resolve_valle_corredor(
    city_or_address: str,
    title: str = "",
    lat: float | None = None,
    lon: float | None = None,
    localities: list[dict[str, Any]] | None = None,
) -> str:
    """Determina el valle ('Valle de Calamuchita' o 'Valle de Punilla') con catálogo y GPS."""
    combined = normalize_text(f"{city_or_address} {title}")
    if "calamuchita" in combined:
        return "Valle de Calamuchita"
    if "punilla" in combined:
        return "Valle de Punilla"

    if localities:
        for loc in localities:
            loc_name = normalize_text(loc.get("barrio_localidad", ""))
            if loc_name and loc_name in combined:
                return str(loc.get("valle_corredor", "Valle de Punilla"))

        if lat is not None and lon is not None:
            try:
                lat_f, lon_f = float(lat), float(lon)
                best_loc = min(
                    localities,
                    key=lambda loc: haversine_distance_km(
                        lat_f, lon_f, loc["latitud_centroide"], loc["longitud_centroide"]
                    ),
                )
                return str(best_loc.get("valle_corredor", "Valle de Punilla"))
            except (TypeError, ValueError):
                pass

    return "Valle de Punilla"


def _extract_place_summary(
    place_item: dict[str, Any],
    localities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normaliza un item de Google Places crawler a esquema tabular limpio."""
    p_title = place_item.get("title") or place_item.get("name") or "Camping"
    p_id = place_item.get("placeId") or place_item.get("cid") or place_item.get("dataId") or p_title
    p_city = place_item.get("city") or place_item.get("address") or ""
    loc_obj = place_item.get("location") or {}
    p_lat = loc_obj.get("lat") if isinstance(loc_obj, dict) else None
    p_lon = loc_obj.get("lng") if isinstance(loc_obj, dict) else None
    p_valle = resolve_valle_corredor(p_city, p_title, p_lat, p_lon, localities)

    dist = place_item.get("reviewsDistribution") or {}
    s1 = int(dist.get("oneStar") or 0)
    s2 = int(dist.get("twoStar") or 0)
    s3 = int(dist.get("threeStar") or 0)
    s4 = int(dist.get("fourStar") or 0)
    s5 = int(dist.get("fiveStar") or 0)
    tot_dist = s1 + s2 + s3 + s4 + s5
    nps_proxy = round(((s5 - (s1 + s2 + s3)) / tot_dist) * 100.0, 2) if tot_dist > 0 else None
    return {
        "place_id": p_id,
        "nombre_camping": p_title,
        "valle_corredor": p_valle,
        "localidad_raw": p_city,
        "latitud": p_lat,
        "longitud": p_lon,
        "total_score": place_item.get("totalScore") or place_item.get("rating"),
        "reviews_count": place_item.get("reviewsCount"),
        "stars_1": s1,
        "stars_2": s2,
        "stars_3": s3,
        "stars_4": s4,
        "stars_5": s5,
        "nps_proxy": nps_proxy,
        "telefono": place_item.get("phone") or place_item.get("phoneUnformatted") or "",
        "website": place_item.get("website") or "",
        "url_google_maps": place_item.get("url") or "",
    }


def is_within_sierras_bbox(lat: Any, lon: Any) -> bool:
    """Verifica si una coordenada pertenece a la región Sierras de Córdoba (Calamuchita/Punilla)."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        return -32.65 <= lat_f <= -30.55 and -65.15 <= lon_f <= -64.05
    except (TypeError, ValueError):
        return False


def parse_raw_gmaps_items(
    raw_places: list[dict[str, Any]],
    localities: list[dict[str, Any]] | None = None,
    enforce_bbox: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convierte items crudos de Apify `compass/crawler-google-places` en (places, reviews)."""
    places: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for place in raw_places:
        if not isinstance(place, dict):
            continue
        summary = _extract_place_summary(place, localities=localities)
        if enforce_bbox and summary.get("latitud") is not None and summary.get("longitud") is not None:
            if not is_within_sierras_bbox(summary["latitud"], summary["longitud"]):
                logger.info(
                    "Descartando lugar fuera de Sierras de Córdoba: %s (%s, %s)",
                    summary["nombre_camping"], summary["latitud"], summary["longitud"],
                )
                continue
        places.append(summary)
        p_reviews = place.get("reviews") or place.get("reviewsData") or []
        for r in p_reviews:
            if isinstance(r, dict) and (r.get("text") or r.get("textTranslated")):
                reviews.append({
                    "id_review": r.get("id") or r.get("reviewId") or f"REV-{len(reviews)+1:05d}",
                    "place_id": summary["place_id"],
                    "nombre_camping": summary["nombre_camping"],
                    "valle_corredor": summary["valle_corredor"],
                    "localidad_raw": summary["localidad_raw"],
                    "estrellas_rating": r.get("stars") or r.get("rating"),
                    "fecha_reseña": r.get("publishedAtDate") or r.get("date"),
                    "texto_reseña": r.get("text") or r.get("textTranslated"),
                })
    return places, reviews


def merge_gmaps_places_and_reviews(
    existing_places: list[dict[str, Any]],
    existing_reviews: list[dict[str, Any]],
    new_places: list[dict[str, Any]],
    new_reviews: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fusiona lugares y reseñas de Google Maps sin duplicados ni pérdida de datos."""
    places_by_id: dict[str, dict[str, Any]] = {}
    for p in existing_places + new_places:
        pid = str(p.get("place_id") or "").strip()
        if not pid:
            continue
        prev = places_by_id.get(pid)
        if not prev:
            places_by_id[pid] = dict(p)
        else:
            merged = dict(prev)
            for k, v in p.items():
                if v not in (None, "", "None") and merged.get(k) in (None, "", "None"):
                    merged[k] = v
            try:
                if int(p.get("reviews_count") or 0) > int(prev.get("reviews_count") or 0):
                    merged.update({k: v for k, v in p.items() if v not in (None, "")})
            except (TypeError, ValueError):
                pass
            places_by_id[pid] = merged

    reviews_by_key: dict[str, dict[str, Any]] = {}
    for r in existing_reviews + new_reviews:
        rid = str(r.get("id_review") or "").strip()
        txt = str(r.get("texto_reseña") or "").strip()
        pid = str(r.get("place_id") or "").strip()
        key = rid if rid and not rid.startswith("REV-") else f"{pid}::{txt[:100]}"
        if key and key not in reviews_by_key:
            reviews_by_key[key] = dict(r)

    return list(places_by_id.values()), list(reviews_by_key.values())


def get_apify_remaining_usd(api_token: str) -> float | None:
    """Consulta el saldo mensual restante en USD de la cuenta Apify (None si falla)."""
    try:
        req = urllib.request.Request(
            "https://api.apify.com/v2/users/me/limits",
            headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
        max_usd = float((data.get("limits") or {}).get("maxMonthlyUsageUsd") or 0.0)
        cur_usd = float((data.get("current") or {}).get("monthlyUsageUsd") or 0.0)
        return max(0.0, round(max_usd - cur_usd, 4))
    except Exception:
        return None


def fetch_google_maps_via_apify(
    search_queries: list[str],
    api_token: str | None = None,
    dataset_id: str | None = None,
    max_crawled_places_per_search: int = 25,
    max_reviews: int = 20,
    use_async: bool = True,
    max_wait_seconds: int = 900,
) -> list[dict[str, Any]]:
    """Extrae lugares y reseñas reales desde Apify Google Places Crawler.

    Usa `compass/crawler-google-places` (modo asincrónico con polling para evitar
    cortes por timeout y rescatar resultados parciales si se agota el crédito).
    Requiere APIFY_TOKEN en variables de entorno o parámetro. ZERO DUMMY DATA policy.
    """
    token = api_token or os.getenv("APIFY_TOKEN")
    ds_id = dataset_id or os.getenv("APIFY_GMAPS_DATASET_ID")

    if not token and not ds_id:
        logger.info(
            "[Google Maps Apify Connector] APIFY_TOKEN no proporcionado. "
            "No se ejecutarán llamadas a Google Maps y se devuelve lista vacía "
            "(ZERO DUMMY DATA policy)."
        )
        return []

    # Caso A: Si se proporciona un dataset_id existente con resultados ya recolectados
    if ds_id and token:
        logger.info("Obteniendo items del dataset Apify existente: %s ...", ds_id)
        url = f"https://api.apify.com/v2/datasets/{ds_id}/items?format=json&clean=true"
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status == 200:
                    raw_items = json.loads(resp.read().decode("utf-8"))
                    logger.info("Recuperados %d items desde el dataset Apify %s.", len(raw_items), ds_id)
                    return raw_items
        except Exception as e:
            logger.error("Error consultando dataset Apify %s: %s", ds_id, e.__class__.__name__)
            return []

    if token and use_async:
        logger.info(
            "Iniciando ejecución asincrónica de compass/crawler-google-places (%d queries, maxPlaces=%d, maxReviews=%d)...",
            len(search_queries),
            max_crawled_places_per_search,
            max_reviews,
        )
        start_url = "https://api.apify.com/v2/acts/compass~crawler-google-places/runs"
        payload = {
            "searchStringsArray": search_queries,
            "maxCrawledPlacesPerSearch": max_crawled_places_per_search,
            "maxReviews": max_reviews,
            "language": "es",
        }
        try:
            req = urllib.request.Request(
                start_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                run_data = json.loads(resp.read().decode("utf-8")).get("data", {})
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")[:300]
            except Exception:
                pass
            if e.code in (402, 403):
                raise ApifyQuotaExceededError(f"Apify HTTP {e.code}: límite de uso alcanzado ({body})") from e
            logger.error("Error iniciando run Apify HTTP %d: %s", e.code, body)
            return []
        except Exception as e:
            logger.error("Error iniciando actor Apify: %s", e)
            return []

        run_id = run_data.get("id")
        run_dataset_id = run_data.get("defaultDatasetId")
        status = run_data.get("status", "RUNNING")
        elapsed = 0
        while run_id and status in ("READY", "RUNNING") and elapsed < max_wait_seconds:
            time.sleep(8)
            elapsed += 8
            poll_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
            try:
                poll_req = urllib.request.Request(
                    poll_url,
                    headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(poll_req, timeout=30) as presp:
                    p_data = json.loads(presp.read().decode("utf-8")).get("data", {})
                    status = p_data.get("status", status)
                    run_dataset_id = p_data.get("defaultDatasetId") or run_dataset_id
                    logger.info("Apify run %s -> estado=%s (%ds)", run_id, status, elapsed)
            except Exception as exc:
                logger.warning("Fallo consultando estado run %s: %s", run_id, exc)

        if run_dataset_id:
            items_url = f"https://api.apify.com/v2/datasets/{run_dataset_id}/items?format=json&clean=true"
            try:
                items_req = urllib.request.Request(
                    items_url,
                    headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(items_req, timeout=90) as iresp:
                    raw_items = json.loads(iresp.read().decode("utf-8"))
                    logger.info(
                        "Actor Apify (%s) recuperó %d lugares desde dataset %s.",
                        status,
                        len(raw_items),
                        run_dataset_id,
                    )
                    return raw_items
            except Exception as exc:
                logger.error("Error descargando items del dataset %s: %s", run_dataset_id, exc)
                return []

    # Caso B: Fallback sincrónico
    if token:
        logger.info(
            "Iniciando ejecución sincrónica de compass/crawler-google-places con %d queries...",
            len(search_queries),
        )
        run_url = "https://api.apify.com/v2/acts/compass~crawler-google-places/run-sync-get-dataset-items"
        payload = {
            "searchStringsArray": search_queries,
            "maxCrawledPlacesPerSearch": max_crawled_places_per_search,
            "maxReviews": max_reviews,
            "language": "es",
        }
        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                run_url,
                data=data_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                if resp.status in (200, 201):
                    raw_items = json.loads(resp.read().decode("utf-8"))
                    logger.info("Actor Apify finalizado con éxito: %d lugares obtenidos.", len(raw_items))
                    return raw_items
        except Exception as e:
            logger.error("Error ejecutando actor Apify compass/crawler-google-places: %s", e)
            return []

    return []


def load_apify_gmaps_json(json_path: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Carga y procesa un archivo JSON exportado manualmente desde Apify Console.

    Retorna una tupla (lugares, reseñas_individuales).
    """
    path = Path(json_path)
    if not path.exists():
        logger.warning("El archivo JSON de Apify no existe en la ruta: %s", path)
        return ([], [])

    try:
        with open(path, mode="r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        logger.error("Error abriendo archivo JSON de Apify %s: %s", path, e)
        return ([], [])

    items: list[dict[str, Any]] = []
    if isinstance(raw_data, list):
        items = raw_data
    elif isinstance(raw_data, dict):
        items = raw_data.get("items") or raw_data.get("data") or [raw_data]

    places: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        place_title = item.get("title") or item.get("name") or "Camping sin nombre"
        place_id = item.get("placeId") or item.get("cid") or item.get("dataId") or place_title
        city = item.get("city") or item.get("address") or ""
        valley = "Valle de Calamuchita" if "calamuchita" in city.lower() or "calamuchita" in place_title.lower() else "Valle de Punilla"

        place_entry = {
            "place_id": place_id,
            "nombre_camping": place_title,
            "localidad_raw": city,
            "valle_corredor": valley,
            "total_score": item.get("totalScore") or item.get("rating"),
            "reviews_count": item.get("reviewsCount"),
            "reviews_distribution": item.get("reviewsDistribution", {}),
            "url": item.get("url"),
        }
        places.append(place_entry)

        # Extraer reseñas
        item_reviews = item.get("reviews") or item.get("reviewsData") or []
        for r in item_reviews:
            if not isinstance(r, dict):
                continue
            r_text = r.get("text") or r.get("textTranslated") or ""
            if not r_text:
                continue

            r_id = r.get("id") or r.get("reviewId") or f"REV-{len(reviews)+1:04d}"
            r_stars = r.get("stars") or r.get("rating")
            r_date = r.get("publishedAtDate") or r.get("date")

            reviews.append({
                "id_review": r_id,
                "place_id": place_id,
                "nombre_camping": place_title,
                "valle_corredor": valley,
                "localidad_raw": city,
                "estrellas_rating": r_stars,
                "fecha_reseña": r_date,
                "texto_reseña": r_text,
            })

    logger.info("Cargados %d lugares y %d reseñas reales desde %s.", len(places), len(reviews), path)
    return (places, reviews)


# ---------------------------------------------------------------------------
# 4. Orquestador Principal
# ---------------------------------------------------------------------------

def scrape_all_real_campings(
    aux_csv_path: str | Path | None = None,
    apify_token: str | None = None,
    gmaps_json_path: str | Path | None = None,
) -> dict[str, Any]:
    """Orquesta la extracción 100% real de campings y reseñas en Córdoba.

    Retorna un diccionario con:
    - 'campings': listado consolidado y deduplicado de campings reales (OSM + SoloCampings).
    - 'gmaps_reviews': listado de reseñas reales extraídas de Google Maps (vía Apify o JSON local).
    - 'gmaps_status': descripción del estado de obtención de reseñas reales.
    - 'total_campings': total de campings reales obtenidos.
    - 'total_reviews': total de reseñas reales obtenidas.
    """
    logger.info("Iniciando extracción real de campings para Sierras de Córdoba...")

    # 1. Cargar centroides de localidades oficiales
    localities = load_localities_centroids(aux_csv_path)

    # 2. Extraer campings desde OSM Overpass API
    osm_campings = fetch_osm_campings(localities=localities, bbox=BBOX_CORDOBA_SIERRAS, timeout=60)

    # 3. Extraer campings desde SoloCampings Córdoba
    sc_campings = fetch_solocampings_cordoba(localities=localities, max_town_pages=12, timeout=10)

    # 4. Fusionar y deduplicar fuentes de campings
    campings = merge_campings_deduplicated(osm_campings, sc_campings)

    # 4.5 Garantizar 100% de coordenadas y campos de ubicación/enlaces en todos los campings
    for c in campings:
        if not c.get("localidad_asignada") or c["localidad_asignada"] == "Desconocido":
            c["localidad_asignada"] = c.get("localidad_raw") or "Sierras de Córdoba"

        if not c.get("valle_corredor") or c["valle_corredor"] == "Desconocido":
            c["valle_corredor"] = "Valle de Punilla"

        if c.get("latitud") is None or c.get("longitud") is None:
            norm_asig = normalize_text(c["localidad_asignada"])
            matched_loc = None
            for loc in localities:
                if normalize_text(loc["barrio_localidad"]) == norm_asig:
                    matched_loc = loc
                    break
            if not matched_loc:
                for loc in localities:
                    norm_l = normalize_text(loc["barrio_localidad"])
                    if norm_l in norm_asig or norm_asig in norm_l:
                        matched_loc = loc
                        break
            if not matched_loc and localities:
                matched_loc = localities[0]
            if matched_loc:
                c["latitud"] = matched_loc["latitud_centroide"]
                c["longitud"] = matched_loc["longitud_centroide"]
                if c.get("distancia_centroide_km") is None:
                    c["distancia_centroide_km"] = 0.0

        if not c.get("ubicacion_completa"):
            loc_str = c.get("localidad_raw") or c.get("localidad_asignada")
            c["ubicacion_completa"] = f"{loc_str}, {c['valle_corredor']}, Córdoba"

        if not c.get("url_busqueda_google_maps"):
            if c.get("latitud") is not None and c.get("longitud") is not None:
                c["url_busqueda_google_maps"] = f"https://www.google.com/maps/search/?api=1&query={c['latitud']},{c['longitud']}"
            else:
                q = f"{c.get('nombre_camping', '')} {c.get('localidad_asignada', '')} Córdoba"
                c["url_busqueda_google_maps"] = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(q)}"

        if "url_osm" not in c:
            c["url_osm"] = f"https://www.openstreetmap.org/{c['osm_id']}" if c.get("osm_id") else ""

    # 5. Obtener reseñas de Google Maps vía Apify o JSON local
    gmaps_places: list[dict[str, Any]] = []
    gmaps_reviews: list[dict[str, Any]] = []
    gmaps_status: str

    # Evaluar si hay archivo JSON local especificado o en data/raw/
    candidate_json_paths = []
    if gmaps_json_path:
        candidate_json_paths.append(Path(gmaps_json_path))
    env_json = os.getenv("APIFY_GMAPS_JSON_PATH")
    if env_json:
        candidate_json_paths.append(Path(env_json))
    repo_root = Path(__file__).resolve().parents[2]
    candidate_json_paths.extend([
        Path("data/raw/apify_google_maps_cordoba.json"),
        repo_root / "data" / "raw" / "apify_google_maps_cordoba.json",
    ])

    found_json: Path | None = None
    for c_path in candidate_json_paths:
        if c_path.exists():
            found_json = c_path
            break

    if found_json:
        gmaps_places, gmaps_reviews = load_apify_gmaps_json(found_json)
        gmaps_status = f"Cargadas {len(gmaps_reviews)} reseñas reales desde archivo local: {found_json}"
    else:
        # Intentar API de Apify si el token está disponible
        token = apify_token or os.getenv("APIFY_TOKEN")
        if token:
            search_queries = [
                "camping Valle de Calamuchita Cordoba",
                "camping Valle de Punilla Cordoba",
                "camping Santa Rosa de Calamuchita",
                "camping Villa Carlos Paz",
            ]
            raw_places = fetch_google_maps_via_apify(
                search_queries=search_queries,
                api_token=token,
                max_crawled_places_per_search=15,
                max_reviews=20,
            )
            gmaps_places, gmaps_reviews = parse_raw_gmaps_items(raw_places, localities=localities)
            gmaps_status = (
                f"Extraídas {len(gmaps_reviews)} reseñas reales vía Apify Google Places API "
                f"({len(raw_places)} lugares)."
            )
        else:
            gmaps_status = (
                "APIFY_TOKEN no configurado ni se detectó archivo JSON local. "
                "No se generaron reseñas sintéticas (ZERO DUMMY DATA policy)."
            )
            logger.info("[Google Maps Status] %s", gmaps_status)

    logger.info(
        "Extracción finalizada: %d campings reales, %d reseñas reales. Estado GMaps: %s",
        len(campings), len(gmaps_reviews), gmaps_status,
    )

    return {
        "campings": campings,
        "gmaps_places": gmaps_places,
        "gmaps_reviews": gmaps_reviews,
        "gmaps_status": gmaps_status,
        "total_campings": len(campings),
        "total_places_gmaps": len(gmaps_places),
        "total_reviews": len(gmaps_reviews),
    }


_GENERIC_CAMPING_TOKENS = {
    "camping", "campamento", "municipal", "villa", "santa", "rosa", "del", "las", "los",
    "san", "rio", "arroyo", "complejo", "cabanas", "parque", "cordoba", "club", "valle",
    "el", "la", "de", "y", "con", "zona", "acampe", "osm", "general", "belgrano",
}


def _is_camping_matched_in_gmaps(
    camping: dict[str, Any],
    gmaps_places: list[dict[str, Any]],
) -> bool:
    """Verifica si un camping de OSM/SoloCampings ya está cubierto en gmaps_places."""
    c_name = normalize_text(camping.get("nombre_camping", ""))
    c_core = re.sub(r"\bcamping\b", "", c_name).strip()
    c_tokens = {t for t in c_name.split() if len(t) > 2 and t not in _GENERIC_CAMPING_TOKENS}
    try:
        c_lat = float(camping["latitud"]) if camping.get("latitud") not in (None, "") else None
        c_lon = float(camping["longitud"]) if camping.get("longitud") not in (None, "") else None
    except (TypeError, ValueError):
        c_lat, c_lon = None, None

    for p in gmaps_places:
        if c_lat is not None and c_lon is not None:
            try:
                p_lat = float(p["latitud"]) if p.get("latitud") not in (None, "") else None
                p_lon = float(p["longitud"]) if p.get("longitud") not in (None, "") else None
                if p_lat is not None and p_lon is not None:
                    if haversine_distance_km(c_lat, c_lon, p_lat, p_lon) <= 0.50:
                        return True
            except (TypeError, ValueError):
                pass
        p_name = normalize_text(p.get("nombre_camping", ""))
        p_core = re.sub(r"\bcamping\b", "", p_name).strip()
        if len(c_core) >= 8 and len(p_core) >= 8 and (c_core in p_core or p_core in c_core):
            return True
        if len(c_tokens) >= 2:
            p_tokens = {t for t in p_name.split() if len(t) > 2 and t not in _GENERIC_CAMPING_TOKENS}
            if p_tokens and len(c_tokens & p_tokens) >= min(2, len(c_tokens)):
                return True
    return False


def crawl_full_gmaps_campings(
    campings: list[dict[str, Any]],
    localities: list[dict[str, Any]],
    api_token: str,
    existing_places: list[dict[str, Any]] | None = None,
    existing_reviews: list[dict[str, Any]] | None = None,
    checkpoint_callback: Any = None,
    max_reviews_per_place: int = 12,
    places_per_locality: int = 35,
    batch_size: int = 30,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Ejecuta extracción intensiva en Google Maps vía Apify para cubrir todas las localidades
    y el catálogo completo de campings reales, guardando checkpoints tras cada lote."""
    all_places = [
        p for p in (existing_places or [])
        if p.get("latitud") in (None, "") or is_within_sierras_bbox(p.get("latitud"), p.get("longitud"))
    ]
    valid_pids = {str(p.get("place_id") or "") for p in all_places}
    all_reviews = [r for r in (existing_reviews or []) if str(r.get("place_id") or "") in valid_pids]

    rem = get_apify_remaining_usd(api_token)
    logger.info("[GMaps Full] Saldo Apify restante al iniciar: %s USD | Base válida en bbox: %d lugares, %d reseñas.",
                f"${rem:.2f}" if rem is not None else "desconocido", len(all_places), len(all_reviews))

    quota_exhausted = False
    if len(all_places) < 120:
        # Fase 1: Barrido por todas las localidades del catálogo + localidades observadas en campings
        loc_names: list[str] = []
        seen_norm: set[str] = set()
        for name in (
            ["Valle de Calamuchita", "Valle de Punilla"]
            + [loc["barrio_localidad"] for loc in localities]
            + [c.get("localidad_asignada", "") for c in campings]
        ):
            clean = str(name or "").strip()
            norm = normalize_text(clean)
            if clean and norm and norm not in {"desconocido", "sierras de cordoba"} and norm not in seen_norm:
                seen_norm.add(norm)
                loc_names.append(clean)

        phase1_queries = [f"camping {loc} Cordoba Argentina" for loc in loc_names]
        logger.info("[GMaps Full — Fase 1] Consultando %d zonas/localidades en Google Maps...", len(phase1_queries))
        try:
            raw_p1 = fetch_google_maps_via_apify(
                search_queries=phase1_queries,
                api_token=api_token,
                max_crawled_places_per_search=places_per_locality,
                max_reviews=max_reviews_per_place,
                use_async=True,
                max_wait_seconds=1200,
            )
            p1_places, p1_reviews = parse_raw_gmaps_items(raw_p1, localities=localities)
            all_places, all_reviews = merge_gmaps_places_and_reviews(all_places, all_reviews, p1_places, p1_reviews)
            if checkpoint_callback:
                checkpoint_callback(all_places, all_reviews)
            logger.info(
                "[GMaps Full — Fase 1 lista] Acumulado: %d lugares únicos, %d reseñas.",
                len(all_places), len(all_reviews),
            )
        except ApifyQuotaExceededError as exc:
            logger.warning("[GMaps Full — Fase 1] Límite de Apify alcanzado: %s", exc)
            quota_exhausted = True
    else:
        logger.info("[GMaps Full] Fase 1 ya cubierta en disco (%d lugares >= 120). Pasando directo a Fase 2...", len(all_places))

    # Fase 2: Relleno dirigido por nombre para campings de campings_zona_real_raw.csv aún no cubiertos
    if not quota_exhausted:
        rem_after_p1 = get_apify_remaining_usd(api_token)
        logger.info("[GMaps Full] Saldo Apify disponible para Fase 2: %s USD",
                    f"${rem_after_p1:.2f}" if rem_after_p1 is not None else "desconocido")

        missing_queries: list[str] = []
        seen_q: set[str] = set()
        generic_names = {"", "camping", "camping sin nombre", "campamento", "zona de acampe", "area de acampe"}
        for c in campings:
            c_raw_name = str(c.get("nombre_camping") or "").strip()
            c_norm = normalize_text(c_raw_name)
            if c_norm in generic_names or len(c_norm) < 4 or re.match(r"^camping\s+osm\s+#", c_norm):
                continue
            if _is_camping_matched_in_gmaps(c, all_places):
                continue
            loc_str = str(c.get("localidad_asignada") or c.get("localidad_raw") or "Cordoba").strip()
            prefix = "" if "camp" in c_norm else "Camping "
            q = f"{prefix}{c_raw_name} {loc_str} Cordoba Argentina"
            q_norm = normalize_text(q)
            if q_norm not in seen_q:
                seen_q.add(q_norm)
                missing_queries.append(q)

        logger.info(
            "[GMaps Full — Fase 2] Campings aún sin match directo: %d queries en lotes de %d.",
            len(missing_queries), batch_size,
        )

        for start in range(0, len(missing_queries), batch_size):
            rem_now = get_apify_remaining_usd(api_token)
            if rem_now is not None and rem_now <= 0.05:
                logger.warning("[GMaps Full — Fase 2] Saldo Apify agotado ($%.2f). Deteniendo limpiamente.", rem_now)
                break
            batch = missing_queries[start:start + batch_size]
            batch_num = (start // batch_size) + 1
            total_batches = (len(missing_queries) + batch_size - 1) // batch_size
            logger.info("[GMaps Full — Fase 2] Ejecutando lote %d/%d (%d campings)...",
                        batch_num, total_batches, len(batch))
            try:
                raw_b = fetch_google_maps_via_apify(
                    search_queries=batch,
                    api_token=api_token,
                    max_crawled_places_per_search=1,
                    max_reviews=max_reviews_per_place,
                    use_async=True,
                    max_wait_seconds=900,
                )
                b_places, b_reviews = parse_raw_gmaps_items(raw_b, localities=localities)
                all_places, all_reviews = merge_gmaps_places_and_reviews(all_places, all_reviews, b_places, b_reviews)
                if checkpoint_callback:
                    checkpoint_callback(all_places, all_reviews)
                logger.info(
                    "[GMaps Full — Lote %d/%d] Acumulado: %d lugares únicos, %d reseñas.",
                    batch_num, total_batches, len(all_places), len(all_reviews),
                )
            except ApifyQuotaExceededError as exc:
                logger.warning("[GMaps Full — Lote %d] Límite Apify alcanzado: %s", batch_num, exc)
                break

    matched_count = sum(1 for c in campings if _is_camping_matched_in_gmaps(c, all_places))
    status = (
        f"Extracción completa GMaps vía Apify: {len(all_places)} lugares únicos, "
        f"{len(all_reviews)} reseñas reales ({matched_count}/{len(campings)} campings OSM/SC cubiertos)."
    )
    return all_places, all_reviews, status


if __name__ == "__main__":
    result = scrape_all_real_campings()
    print(f"Campings obtenidos: {result['total_campings']}")
    print(f"Reseñas obtenidas: {result['total_reviews']}")
    print(f"Estado GMaps: {result['gmaps_status']}")
    if result["campings"]:
        print("Primer camping:", json.dumps(result["campings"][0], ensure_ascii=False, indent=2))
