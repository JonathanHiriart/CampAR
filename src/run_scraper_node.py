#!/usr/bin/env python3
"""CampAR — Scraper Node & Real Raw Pipeline.

Orquesta la extracción 100% real de datos de Mercado Libre y campings de Córdoba:
1. Carga variables de entorno (.env) de forma nativa sin dependencias externas.
2. Extrae publicaciones reales de Mercado Libre Inmuebles para los valles de Calamuchita y Punilla.
3. Extrae campings y reseñas reales (OpenStreetMap Overpass + SoloCampings + Apify Google Maps).
4. Ejecuta análisis de NLP no supervisado (TF-IDF + KMeans) y conteo difuso (SentenceIndex) sobre el corpus real.
5. Exporta los datasets reales crudos a data/raw/ cumpliendo con la política ZERO DUMMY DATA.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

# Asegurar path para importar terrascout_actor y librerías del repo
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "terrascout_actor"))

# Auto-detectar entorno virtual local (.venv en repo o carpeta padre) si falta scikit-learn
try:
    import sklearn  # noqa: F401
except ImportError:
    for venv_root in (REPO_ROOT / ".venv", REPO_ROOT.parent / ".venv"):
        for sp in venv_root.glob("lib/python*/site-packages"):
            if sp.is_dir():
                sys.path.append(str(sp))

from terrascout_actor.my_actor.camping_scraper import (
    crawl_full_gmaps_campings,
    load_localities_centroids,
    scrape_all_real_campings,
)
from terrascout_actor.my_actor.nlp_analysis import (
    SentenceIndex,
    find_topics,
    fuzzy_count,
    split_sentences,
)
from terrascout_actor.my_actor.ml_scraper import (
    enrich_listings_with_details,
    scrape_all_mercadolibre_valleys,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_scraper_node")

# Rutas estándar del proyecto
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
ML_CSV_PATH = DATA_RAW_DIR / "mercadolibre_terrenos_calamuchita_punilla_raw.csv"
CAMPINGS_CSV_PATH = DATA_RAW_DIR / "campings_zona_real_raw.csv"
GMAPS_PLACES_CSV_PATH = DATA_RAW_DIR / "google_maps_campings_places_raw.csv"
GMAPS_CSV_PATH = DATA_RAW_DIR / "google_maps_campings_reviews_raw.csv"
TOPICOS_JSON_PATH = DATA_RAW_DIR / "topicos_nlp_real_raw.json"
CONFIG_RULES_PATH = REPO_ROOT / "config" / "business_rules.json"
AUX_TOPO_PATH = REPO_ROOT / "data" / "aux_topografia_cordoba.csv"


def load_env_file(env_path: Path | None = None) -> None:
    """Carga variables desde un archivo .env si existe, sin requerir python-dotenv."""
    path = env_path or (REPO_ROOT / ".env")
    if not path.is_file():
        return

    logger.info("Cargando variables de entorno desde: %s", path)
    try:
        with open(path, mode="r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception as exc:
        logger.warning("No se pudo leer .env (%s): %s", path, exc)


def load_business_rules() -> dict[str, Any]:
    """Carga la configuración y reglas de negocio desde config/business_rules.json."""
    if not CONFIG_RULES_PATH.is_file():
        logger.warning("No se encontró %s. Se usarán valores por defecto.", CONFIG_RULES_PATH)
        return {}

    try:
        with open(CONFIG_RULES_PATH, mode="r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Error leyendo %s: %s", CONFIG_RULES_PATH, exc)
        return {}


def clean_stale_dummy_files() -> None:
    """Elimina archivos de dummy data antiguos para asegurar integridad del workspace."""
    stale_files = [
        DATA_RAW_DIR / "topicos_quejas_kmeans_raw.json",
        DATA_RAW_DIR / ".~lock.google_maps_campings_reviews_raw.csv#",
        DATA_RAW_DIR / ".~lock.mercadolibre_terrenos_calamuchita_punilla_raw.csv#",
    ]
    for p in stale_files:
        if p.exists():
            try:
                p.unlink()
                logger.info("Archivo antiguo eliminado: %s", p)
            except Exception as exc:
                logger.warning("No se pudo eliminar %s: %s", p, exc)


GMAPS_PLACES_FIELDNAMES = [
    "place_id",
    "nombre_camping",
    "valle_corredor",
    "localidad_raw",
    "latitud",
    "longitud",
    "total_score",
    "reviews_count",
    "stars_1",
    "stars_2",
    "stars_3",
    "stars_4",
    "stars_5",
    "nps_proxy",
    "telefono",
    "website",
    "url_google_maps",
]

GMAPS_REVIEWS_FIELDNAMES = [
    "id_review",
    "place_id",
    "nombre_camping",
    "valle_corredor",
    "localidad_raw",
    "estrellas_rating",
    "fecha_reseña",
    "texto_reseña",
]


def write_gmaps_csvs(
    gmaps_places: list[dict[str, Any]],
    gmaps_reviews: list[dict[str, Any]],
) -> None:
    """Escribe/actualiza en disco los CSVs de lugares y reseñas reales de Google Maps."""
    if gmaps_places:
        with open(GMAPS_PLACES_CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=GMAPS_PLACES_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(gmaps_places)
        logger.info("Archivo escrito: %s (%d lugares reales)", GMAPS_PLACES_CSV_PATH, len(gmaps_places))

    if gmaps_reviews:
        with open(GMAPS_CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=GMAPS_REVIEWS_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(gmaps_reviews)
        logger.info("Archivo escrito: %s (%d reseñas reales)", GMAPS_CSV_PATH, len(gmaps_reviews))


def run_scraper_pipeline(
    max_items_per_valley: int = 600,
    max_pages_per_valley: int = 15,
    gmaps_json_path: str | Path | None = None,
    apify_token: str | None = None,
    skip_ml_details: bool = False,
    gmaps_only: bool = False,
    nlp_only: bool = False,
    gmaps_full: bool = False,
) -> dict[str, Any]:
    """Ejecuta el pipeline completo de extracción real y NLP sin datos sintéticos."""
    os.makedirs(DATA_RAW_DIR, exist_ok=True)
    clean_stale_dummy_files()

    rules = load_business_rules()
    token = apify_token or os.getenv("APIFY_TOKEN")

    logger.info("=================================================================")
    logger.info("   CampAR — Scraper Node (Extracción 100% Real)                 ")
    logger.info("=================================================================")
    logger.info("Parámetros: max_items_per_valley=%d, max_pages_per_valley=%d", max_items_per_valley, max_pages_per_valley)
    logger.info("Apify Token configurado: %s", "SÍ" if bool(token) else "NO (Modo OSM/SoloCampings)")
    if gmaps_json_path:
        logger.info("Ruta JSON local Google Maps: %s", gmaps_json_path)

    # 1. Extracción de Publicaciones Reales de Mercado Libre
    if (gmaps_only or nlp_only or gmaps_full) and ML_CSV_PATH.exists():
        logger.info(">>> Paso 1: Reutilizando %s existente (--gmaps-only/--nlp-only/--gmaps-full activo)...", ML_CSV_PATH)
        with open(ML_CSV_PATH, mode="r", encoding="utf-8") as f:
            ml_listings = list(csv.DictReader(f))
        logger.info("Mercado Libre cargado desde disco: %d publicaciones.", len(ml_listings))
    else:
        logger.info(">>> Paso 1: Scrapeando Mercado Libre Inmuebles Córdoba...")
        ml_listings = scrape_all_mercadolibre_valleys(
            max_items_per_valley=max_items_per_valley,
            max_pages_per_valley=max_pages_per_valley,
        )
        logger.info("Mercado Libre: %d publicaciones base extraídas.", len(ml_listings))

        if not skip_ml_details:
            logger.info(">>> Paso 1.5: Enriqueciendo %d publicaciones con detalles individuales...", len(ml_listings))
            ml_listings = enrich_listings_with_details(ml_listings, max_workers=10)
        else:
            logger.info(">>> Paso 1.5: Omitiendo enriquecimiento de detalles ML (--skip-ml-details activo).")
            for item in ml_listings:
                if not item.get("localidad_raw"):
                    item["localidad_raw"] = f"{item.get('valle_corredor', 'Sierras')}, Córdoba"
                item.setdefault("latitud", None)
                item.setdefault("longitud", None)
                item.setdefault("descripcion_completa", "")
                item.setdefault("telefono_en_descripcion", "")
                item.setdefault("url_vendedor", "")
                item.setdefault("url_busqueda", "")
                if not item.get("url_google_maps"):
                    loc = item["localidad_raw"]
                    item["url_google_maps"] = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(loc + ', Córdoba, Argentina')}"

        # Guardar CSV de Mercado Libre
        ml_fieldnames = [
            "id_publicacion",
            "fecha_extraccion",
            "valle_corredor",
            "localidad_raw",
            "titulo_publicacion",
            "moneda_raw",
            "precio_raw",
            "superficie_raw_texto",
            "superficie_m2_extraida",
            "latitud",
            "longitud",
            "descripcion_completa",
            "telefono_en_descripcion",
            "vendedor_nombre",
            "url_vendedor",
            "es_tienda_oficial",
            "tipo_aviso",
            "url_busqueda",
            "url_publicacion",
            "url_google_maps",
            "fuente_extraccion",
        ]
        with open(ML_CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ml_fieldnames)
            writer.writeheader()
            writer.writerows(ml_listings)
        logger.info("Archivo escrito: %s (%d filas)", ML_CSV_PATH, len(ml_listings))

    # 2. Extracción de Campings y Reseñas Reales
    if nlp_only and CAMPINGS_CSV_PATH.exists():
        logger.info(">>> Paso 2: Reutilizando campings y reseñas existentes en disco (--nlp-only activo)...")
        with open(CAMPINGS_CSV_PATH, mode="r", encoding="utf-8") as f:
            campings = list(csv.DictReader(f))
        gmaps_places = []
        if GMAPS_PLACES_CSV_PATH.exists():
            with open(GMAPS_PLACES_CSV_PATH, mode="r", encoding="utf-8") as f:
                gmaps_places = list(csv.DictReader(f))
        gmaps_reviews = []
        if GMAPS_CSV_PATH.exists():
            with open(GMAPS_CSV_PATH, mode="r", encoding="utf-8") as f:
                gmaps_reviews = list(csv.DictReader(f))
        gmaps_status = f"Cargadas {len(gmaps_reviews)} reseñas reales desde disco ({len(gmaps_places)} lugares)."
    elif gmaps_full and CAMPINGS_CSV_PATH.exists() and token:
        logger.info(">>> Paso 2 (--gmaps-full): Reutilizando %s y lanzando extracción completa Google Maps vía Apify...", CAMPINGS_CSV_PATH)
        with open(CAMPINGS_CSV_PATH, mode="r", encoding="utf-8") as f:
            campings = list(csv.DictReader(f))
        existing_places: list[dict[str, Any]] = []
        if GMAPS_PLACES_CSV_PATH.exists():
            with open(GMAPS_PLACES_CSV_PATH, mode="r", encoding="utf-8") as f:
                existing_places = list(csv.DictReader(f))
        existing_reviews: list[dict[str, Any]] = []
        if GMAPS_CSV_PATH.exists():
            with open(GMAPS_CSV_PATH, mode="r", encoding="utf-8") as f:
                existing_reviews = list(csv.DictReader(f))

        localities = load_localities_centroids(AUX_TOPO_PATH if AUX_TOPO_PATH.exists() else None)
        gmaps_places, gmaps_reviews, gmaps_status = crawl_full_gmaps_campings(
            campings=campings,
            localities=localities,
            api_token=token,
            existing_places=existing_places,
            existing_reviews=existing_reviews,
            checkpoint_callback=write_gmaps_csvs,
        )
        write_gmaps_csvs(gmaps_places, gmaps_reviews)
        logger.info("Extracción completa GMaps finalizada: %s", gmaps_status)
    else:
        logger.info(">>> Paso 2: Scrapeando Campings Reales (OSM + SoloCampings + Apify GMaps)...")
        campings_res = scrape_all_real_campings(
            aux_csv_path=AUX_TOPO_PATH if AUX_TOPO_PATH.exists() else None,
            apify_token=token,
            gmaps_json_path=gmaps_json_path,
        )
        campings = campings_res.get("campings", [])
        gmaps_places = campings_res.get("gmaps_places", [])
        gmaps_reviews = campings_res.get("gmaps_reviews", [])
        gmaps_status = campings_res.get("gmaps_status", "")
        logger.info("Campings reales obtenidos: %d", len(campings))
        logger.info("Reseñas reales Google Maps obtenidas: %d (%s)", len(gmaps_reviews), gmaps_status)

        # Resiliencia ante caída temporal de OSM Overpass: no perder filas OSM ya validadas
        osm_now = sum(1 for c in campings if "Overpass" in str(c.get("fuente_extraccion", "")))
        if osm_now == 0 and CAMPINGS_CSV_PATH.exists():
            try:
                with open(CAMPINGS_CSV_PATH, mode="r", encoding="utf-8") as f:
                    prev_campings = list(csv.DictReader(f))
                prev_osm = [c for c in prev_campings if "Overpass" in str(c.get("fuente_extraccion", ""))]
                if prev_osm:
                    from terrascout_actor.my_actor.camping_scraper import merge_campings_deduplicated
                    logger.warning(
                        "OSM Overpass falló (0 items). Conservando %d campings OSM previos para no perder datos.",
                        len(prev_osm),
                    )
                    campings = merge_campings_deduplicated(prev_osm, campings)
            except Exception as exc:
                logger.warning("No se pudo fusionar respaldo OSM previo: %s", exc)

        # Guardar CSV de Campings Reales
        camping_fieldnames = [
            "osm_id",
            "nombre_camping",
            "latitud",
            "longitud",
            "localidad_raw",
            "localidad_asignada",
            "ubicacion_completa",
            "valle_corredor",
            "distancia_centroide_km",
            "tiene_electricidad",
            "tiene_agua_potable",
            "acepta_casas_rodantes",
            "website",
            "telefono",
            "operador",
            "horario",
            "descripcion_tags",
            "url_busqueda_google_maps",
            "url_osm",
            "fuente_extraccion",
        ]
        with open(CAMPINGS_CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=camping_fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(campings)
        logger.info("Archivo escrito: %s (%d filas)", CAMPINGS_CSV_PATH, len(campings))

        write_gmaps_csvs(gmaps_places, gmaps_reviews)
        if not gmaps_reviews:
            # Si no hay reseñas reales, limpiar archivo dummy si existía
            if GMAPS_CSV_PATH.exists():
                try:
                    GMAPS_CSV_PATH.unlink()
                    logger.info("Eliminado archivo dummy previo de reseñas Google Maps: %s", GMAPS_CSV_PATH)
                except Exception as exc:
                    logger.warning("No se pudo eliminar archivo dummy previo: %s", exc)
            logger.info(
                "[AVISO GMAPS] Para activar reseñas reales de Google Maps:\n"
                "  1. Exportar JSON de Apify compass/crawler-google-places y pasar '--gmaps-json <ruta.json>'\n"
                "  2. O agregar 'APIFY_TOKEN=tu_token' en el archivo .env o variable de entorno."
            )

    # 3. Procesamiento de NLP y Conteo Difuso sobre Corpus 100% Real
    logger.info(">>> Paso 3: Análisis NLP no supervisado sobre el corpus real...")
    corpus_sentences: list[str] = []
    ml_sentences: list[str] = []

    # Textos de publicaciones de Mercado Libre (título y descripción completa)
    for item in ml_listings:
        title = item.get("titulo_publicacion")
        if title:
            s_t = split_sentences([title])
            corpus_sentences.extend(s_t)
            ml_sentences.extend(s_t)
        desc = item.get("descripcion_completa")
        if desc:
            s_d = split_sentences([desc])
            corpus_sentences.extend(s_d)
            ml_sentences.extend(s_d)

    # Textos de campings (nombres y descripciones)
    for c in campings:
        c_name = c.get("nombre_camping")
        if c_name:
            corpus_sentences.append(c_name)
        c_desc = c.get("descripcion_tags")
        if c_desc:
            corpus_sentences.extend(split_sentences([c_desc]))

    # Textos de reseñas reales de Google Maps si existen
    for r in gmaps_reviews:
        r_text = r.get("texto_reseña")
        if r_text:
            corpus_sentences.extend(split_sentences([r_text]))

    logger.info("Corpus de texto real consolidado: %d oraciones.", len(corpus_sentences))

    # Parámetros desde config/business_rules.json
    nlp_cfg = rules.get("nlp_params", {})
    top_topics = int(nlp_cfg.get("top_topics", 4))
    n_clusters = int(nlp_cfg.get("n_clusters", 0))
    n_terms = int(nlp_cfg.get("n_terms", 5))
    n_examples = int(nlp_cfg.get("n_examples", 3))
    fuzzy_thresh = float(nlp_cfg.get("fuzzy_threshold", 85.0))
    fuzzy_scorer = str(nlp_cfg.get("fuzzy_scorer", "ratio"))
    if fuzzy_scorer not in ["ratio", "partial_ratio", "token_sort_ratio", "token_set_ratio", "WRatio"]:
        fuzzy_scorer = "ratio"

    palabras_clave = rules.get("palabras_clave_servicios", [
        "agua corriente", "luz electrica", "escritura", "arboleda", "asfalto", "gas natural", "rio"
    ])
    stop_words_es = rules.get("stop_words_es", [])

    topics_res: dict[str, Any] = {}
    if len(corpus_sentences) >= 2:
        topics_res = find_topics(
            sentences=corpus_sentences,
            top_n=top_topics,
            n_clusters=n_clusters,
            n_terms=n_terms,
            n_examples=n_examples,
            stop_words="spanish",
            extra_stop_words=stop_words_es[:40] if stop_words_es else None,
        )

    # Tópicos específicos de quejas en reseñas Google Maps (1-3 estrellas)
    quejas_sentences: list[str] = []
    for r in gmaps_reviews:
        try:
            stars = float(r.get("estrellas_rating") or 5)
        except (TypeError, ValueError):
            stars = 5.0
        if stars <= 3.0 and r.get("texto_reseña"):
            quejas_sentences.extend(split_sentences([str(r["texto_reseña"])]))

    gmaps_quejas_topics: dict[str, Any] = {}
    if len(quejas_sentences) >= 4:
        gmaps_quejas_topics = find_topics(
            sentences=quejas_sentences,
            top_n=min(4, top_topics),
            n_clusters=3 if len(quejas_sentences) >= 6 else 2,
            n_terms=n_terms,
            n_examples=n_examples,
            stop_words="spanish",
            extra_stop_words=(stop_words_es[:40] if stop_words_es else []) + ["camping", "lugar", "muy"],
        )

    # Conteo difuso sobre infraestructura y servicios exclusivamente sobre avisos ML
    sentence_idx = SentenceIndex(ml_sentences or corpus_sentences)
    fuzzy_counts: dict[str, Any] = {}
    for kw in palabras_clave:
        fuzzy_counts[kw] = fuzzy_count(
            index=sentence_idx,
            query=kw,
            scorer_name=fuzzy_scorer,
            threshold=fuzzy_thresh,
        )

    topicos_data = {
        "metadata": {
            "fecha_extraccion": datetime.now().isoformat(),
            "algoritmo": "TF-IDF + KMeans + SentenceIndex (scikit-learn / rapidfuzz / difflib)",
            "fuzzy_counts_fuente": "mercadolibre_publicaciones",
            "fuentes_utilizadas": [
                "MercadoLibre Inmuebles Córdoba",
                "OpenStreetMap Overpass",
                "Directorio SoloCampings Córdoba",
            ] + (["Google Maps Places via Apify"] if gmaps_reviews else []),
            "total_publicaciones_ml": len(ml_listings),
            "total_campings_reales": len(campings),
            "total_reviews_reales": len(gmaps_reviews),
            "total_oraciones_corpus": len(corpus_sentences),
            "gmaps_status": gmaps_status,
        },
        "n_clusters": topics_res.get("n_clusters", 0),
        "silhouette": topics_res.get("silhouette"),
        "n_sentences": topics_res.get("n_sentences", len(corpus_sentences)),
        "topics": topics_res.get("items", []),
        "topics_quejas_gmaps": gmaps_quejas_topics,
        "fuzzy_counts": fuzzy_counts,
    }

    with open(TOPICOS_JSON_PATH, mode="w", encoding="utf-8") as f:
        json.dump(topicos_data, f, indent=2, ensure_ascii=False)
    logger.info("Archivo escrito: %s", TOPICOS_JSON_PATH)

    # 4. Resumen Ejecutivo Final
    calamuchita_ml = sum(1 for r in ml_listings if r.get("valle_corredor") == "Valle de Calamuchita")
    punilla_ml = sum(1 for r in ml_listings if r.get("valle_corredor") == "Valle de Punilla")
    calamuchita_camp = sum(1 for c in campings if c.get("valle_corredor") == "Valle de Calamuchita")
    punilla_camp = sum(1 for c in campings if c.get("valle_corredor") == "Valle de Punilla")

    logger.info("=================================================================")
    logger.info("   RESUMEN EJECUTIVO — SCRAPING REAL COMPLETADO                  ")
    logger.info("=================================================================")
    logger.info("Publicaciones Mercado Libre:")
    logger.info("  * Total: %d", len(ml_listings))
    logger.info("  * Valle de Calamuchita: %d", calamuchita_ml)
    logger.info("  * Valle de Punilla: %d", punilla_ml)
    logger.info("Campings Reales:")
    logger.info("  * Total: %d", len(campings))
    logger.info("  * Valle de Calamuchita: %d", calamuchita_camp)
    logger.info("  * Valle de Punilla: %d", punilla_camp)
    logger.info("Reseñas Google Maps:")
    logger.info("  * Total: %d", len(gmaps_reviews))
    logger.info("Tópicos NLP descubiertos (%d clusters):", topicos_data.get("n_clusters", 0))
    for topic in topicos_data.get("topics", []):
        logger.info("  * Tópico #%d (Share: %.1f%%): %s", topic["rank"], topic["share"] * 100, ", ".join(topic["terms"]))
    logger.info("Menciones de Servicios e Infraestructura:")
    for kw, stats in fuzzy_counts.items():
        if stats.get("count", 0) > 0:
            logger.info("  * '%s': %d menciones", kw, stats["count"])
    logger.info("=================================================================")

    return {
        "ml_listings_count": len(ml_listings),
        "campings_count": len(campings),
        "gmaps_reviews_count": len(gmaps_reviews),
        "n_clusters": topicos_data.get("n_clusters", 0),
        "ml_csv": str(ML_CSV_PATH),
        "campings_csv": str(CAMPINGS_CSV_PATH),
        "topicos_json": str(TOPICOS_JSON_PATH),
    }


def main() -> None:
    """Punto de entrada CLI para ejecución del nodo scraper."""
    parser = argparse.ArgumentParser(
        description="CampAR — Scraper Node (Extracción 100% Real)"
    )
    parser.add_argument(
        "--max-items-per-valley",
        type=int,
        default=600,
        help="Máximo de publicaciones a extraer por valle (default: 600)",
    )
    parser.add_argument(
        "--max-pages-per-valley",
        type=int,
        default=15,
        help="Máximo de páginas de Mercado Libre a recorrer por valle (default: 15)",
    )
    parser.add_argument(
        "--gmaps-json",
        type=str,
        default=None,
        help="Ruta opcional a dataset JSON exportado desde Apify compass/crawler-google-places",
    )
    parser.add_argument(
        "--skip-ml-details",
        action="store_true",
        default=False,
        help="Omitir enriquecimiento individual de detalles en Mercado Libre (por defecto: ejecuta enriquecimiento)",
    )
    parser.add_argument(
        "--gmaps-only",
        action="store_true",
        default=False,
        help="Reutiliza el CSV de Mercado Libre existente y ejecuta solo la extracción de campings / Google Maps",
    )
    parser.add_argument(
        "--nlp-only",
        action="store_true",
        default=False,
        help="Recalcula los tópicos NLP y fuzzy counts desde los CSVs existentes en data/raw/ sin scrapear la web",
    )
    parser.add_argument(
        "--gmaps-full",
        action="store_true",
        default=False,
        help="Ejecuta extracción intensiva en Google Maps vía Apify (16+ localidades + campings faltantes) con checkpoints",
    )

    args = parser.parse_args()

    # Cargar .env si existe
    load_env_file()

    run_scraper_pipeline(
        max_items_per_valley=args.max_items_per_valley,
        max_pages_per_valley=args.max_pages_per_valley,
        gmaps_json_path=args.gmaps_json,
        skip_ml_details=args.skip_ml_details,
        gmaps_only=args.gmaps_only,
        nlp_only=args.nlp_only,
        gmaps_full=args.gmaps_full,
    )


if __name__ == "__main__":
    main()
