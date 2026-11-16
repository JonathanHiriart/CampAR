#!/usr/bin/env python3
"""TerraScout AI — Scraper Node & Real Raw Pipeline.

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
from datetime import datetime
from pathlib import Path
from typing import Any

# Asegurar path para importar terrascout_actor y librerías del repo
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "terrascout_actor"))

from terrascout_actor.my_actor.camping_scraper import scrape_all_real_campings
from terrascout_actor.my_actor.main import (
    SentenceIndex,
    find_topics,
    fuzzy_count,
    split_sentences,
)
from terrascout_actor.my_actor.ml_scraper import scrape_all_mercadolibre_valleys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_scraper_node")

# Rutas estándar del proyecto
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
ML_CSV_PATH = DATA_RAW_DIR / "mercadolibre_terrenos_calamuchita_punilla_raw.csv"
CAMPINGS_CSV_PATH = DATA_RAW_DIR / "campings_zona_real_raw.csv"
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


def run_scraper_pipeline(
    max_items_per_valley: int = 600,
    max_pages_per_valley: int = 15,
    gmaps_json_path: str | Path | None = None,
    apify_token: str | None = None,
) -> dict[str, Any]:
    """Ejecuta el pipeline completo de extracción real y NLP sin datos sintéticos."""
    os.makedirs(DATA_RAW_DIR, exist_ok=True)
    clean_stale_dummy_files()

    rules = load_business_rules()
    token = apify_token or os.getenv("APIFY_TOKEN")

    logger.info("=================================================================")
    logger.info("   TerraScout AI — Scraper Node (Extracción 100% Real)          ")
    logger.info("=================================================================")
    logger.info("Parámetros: max_items_per_valley=%d, max_pages_per_valley=%d", max_items_per_valley, max_pages_per_valley)
    logger.info("Apify Token configurado: %s", "SÍ" if bool(token) else "NO (Modo OSM/SoloCampings)")
    if gmaps_json_path:
        logger.info("Ruta JSON local Google Maps: %s", gmaps_json_path)

    # 1. Extracción de Publicaciones Reales de Mercado Libre
    logger.info(">>> Paso 1: Scrapeando Mercado Libre Inmuebles Córdoba...")
    ml_listings = scrape_all_mercadolibre_valleys(
        max_items_per_valley=max_items_per_valley,
        max_pages_per_valley=max_pages_per_valley,
    )
    logger.info("Mercado Libre: %d publicaciones extraídas.", len(ml_listings))

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
        "vendedor_nombre",
        "es_tienda_oficial",
        "tipo_aviso",
        "url_publicacion",
        "fuente_extraccion",
    ]
    with open(ML_CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ml_fieldnames)
        writer.writeheader()
        writer.writerows(ml_listings)
    logger.info("Archivo escrito: %s (%d filas)", ML_CSV_PATH, len(ml_listings))

    # 2. Extracción de Campings y Reseñas Reales
    logger.info(">>> Paso 2: Scrapeando Campings Reales (OSM + SoloCampings + Apify GMaps)...")
    campings_res = scrape_all_real_campings(
        aux_csv_path=AUX_TOPO_PATH if AUX_TOPO_PATH.exists() else None,
        apify_token=token,
        gmaps_json_path=gmaps_json_path,
    )
    campings = campings_res.get("campings", [])
    gmaps_reviews = campings_res.get("gmaps_reviews", [])
    gmaps_status = campings_res.get("gmaps_status", "")
    logger.info("Campings reales obtenidos: %d", len(campings))
    logger.info("Reseñas reales Google Maps obtenidas: %d (%s)", len(gmaps_reviews), gmaps_status)

    # Guardar CSV de Campings Reales
    camping_fieldnames = [
        "osm_id",
        "nombre_camping",
        "latitud",
        "longitud",
        "localidad_raw",
        "localidad_asignada",
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
        "fuente_extraccion",
    ]
    with open(CAMPINGS_CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=camping_fieldnames)
        writer.writeheader()
        writer.writerows(campings)
    logger.info("Archivo escrito: %s (%d filas)", CAMPINGS_CSV_PATH, len(campings))

    # Guardar CSV de Reseñas de Google Maps si hay reseñas reales
    if gmaps_reviews:
        gmaps_fieldnames = [
            "id_review",
            "place_id",
            "nombre_camping",
            "valle_corredor",
            "localidad_raw",
            "estrellas_rating",
            "fecha_reseña",
            "texto_reseña",
        ]
        with open(GMAPS_CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=gmaps_fieldnames)
            writer.writeheader()
            writer.writerows(gmaps_reviews)
        logger.info("Archivo escrito: %s (%d reseñas reales)", GMAPS_CSV_PATH, len(gmaps_reviews))
    else:
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

    # Textos de publicaciones de Mercado Libre
    for item in ml_listings:
        title = item.get("titulo_publicacion")
        if title:
            corpus_sentences.extend(split_sentences([title]))

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

    # Conteo difuso sobre infraestructura y servicios en el corpus real
    sentence_idx = SentenceIndex(corpus_sentences)
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
        description="TerraScout AI — Scraper Node (Extracción 100% Real)"
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

    args = parser.parse_args()

    # Cargar .env si existe
    load_env_file()

    run_scraper_pipeline(
        max_items_per_valley=args.max_items_per_valley,
        max_pages_per_valley=args.max_pages_per_valley,
        gmaps_json_path=args.gmaps_json,
    )


if __name__ == "__main__":
    main()
