"""Ejecutor local del flujo Producto 1: APIFY ETL -> dataset_limpio.csv -> APIFY EDA -> Dashboard CSVs/XLSX.

Refleja paso a paso el diagrama `docs/diagrama_flujo_producto1.png`:
  1. [DRIVE DATASET RAW] -> data/raw/* + data/aux_topografia_cordoba.csv + config/business_rules.json
  2. [APIFY ETL]         -> actors/apify_etl -> data/processed/dataset_limpio.csv
  3. [APIFY EDA]         -> actors/apify_eda -> data/processed/dashboard/{csv_1,csv_2,csv_3,.xlsx}
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Auto-detectar entorno virtual local (.venv en repo o carpeta padre)
try:
    import pandas  # noqa: F401
    import scipy  # noqa: F401
except ImportError:
    for venv_root in (REPO_ROOT / ".venv", REPO_ROOT.parent / ".venv"):
        for sp in venv_root.glob("lib/python*/site-packages"):
            if sp.is_dir():
                sys.path.append(str(sp))

sys.path.insert(0, str(REPO_ROOT))

from actors.apify_eda.my_actor.eda_core import build_multisheet_xlsx_bytes, run_eda_pipeline  # noqa: E402
from actors.apify_etl.my_actor.etl_core import run_etl_pipeline  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_producto1_pipeline")


def build_raw_consolidated_xlsx(output_path: Path | None = None) -> Path:
    """Consolida todos los CSV y JSON RAW del Paso 1 en un único Excel multi-hoja para Google Sheets."""
    raw_dir = REPO_ROOT / "data" / "raw"
    out_xlsx = output_path or (raw_dir / "dataset_raw_consolidado.xlsx")

    df_ml = pd.read_csv(raw_dir / "mercadolibre_terrenos_calamuchita_punilla_raw.csv", dtype={"telefono_en_descripcion": str})
    df_camp = pd.read_csv(raw_dir / "campings_zona_real_raw.csv")
    df_places = pd.read_csv(raw_dir / "google_maps_campings_places_raw.csv")
    df_topo = pd.read_csv(REPO_ROOT / "data" / "aux_topografia_cordoba.csv")
    df_reviews = pd.read_csv(raw_dir / "google_maps_campings_reviews_raw.csv")

    rules = json.loads((REPO_ROOT / "config" / "business_rules.json").read_text(encoding="utf-8"))
    df_rules = pd.DataFrame([
        {"clave": k, "valor_json": json.dumps(v, ensure_ascii=False)}
        for k, v in rules.items()
    ])

    top = json.loads((raw_dir / "topicos_nlp_real_raw.json").read_text(encoding="utf-8"))
    top_rows: list[dict[str, Any]] = []
    for item in (top.get("topics_quejas_gmaps") or {}).get("items", []):
        top_rows.append({
            "seccion": "topic_queja",
            "rank_o_clave": str(item.get("rank", "")),
            "size": int(item.get("size", 0)),
            "share": float(item.get("share", 0.0)),
            "terms_json": json.dumps(item.get("terms", []), ensure_ascii=False),
        })
    for kw, stats in (top.get("fuzzy_counts") or {}).items():
        top_rows.append({
            "seccion": "fuzzy_count",
            "rank_o_clave": str(kw),
            "size": int(stats.get("count", 0)),
            "share": None,
            "terms_json": json.dumps(stats, ensure_ascii=False),
        })
    df_topicos = pd.DataFrame(top_rows)

    xlsx_bytes = build_multisheet_xlsx_bytes({
        "ml_terrenos": df_ml,
        "campings": df_camp,
        "places": df_places,
        "topografia": df_topo,
        "reviews": df_reviews,
        "business_rules": df_rules,
        "topicos_nlp": df_topicos,
    })
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    out_xlsx.write_bytes(xlsx_bytes)
    logger.info("Excel RAW consolidado escrito: %s (%d bytes, 7 pestañas)", out_xlsx, len(xlsx_bytes))
    return out_xlsx


def run_producto1_end_to_end(
    processed_dir: Path | None = None,
    top_oportunidades_limit: int = 250,
) -> dict[str, Any]:
    """Ejecuta localmente Actor 1 (ETL) seguido de Actor 2 (EDA) generando salidas de Dashboard."""
    out_root = processed_dir or (REPO_ROOT / "data" / "processed")
    dash_dir = out_root / "dashboard"
    out_root.mkdir(parents=True, exist_ok=True)
    dash_dir.mkdir(parents=True, exist_ok=True)

    logger.info(">>> Paso 1 [APIFY ETL]: Ejecutando limpieza, reglas y JOIN espacial...")
    df_clean, funnel = run_etl_pipeline()

    dataset_limpio_path = out_root / "dataset_limpio.csv"
    funnel_path = out_root / "etl_funnel.json"
    df_clean.to_csv(dataset_limpio_path, index=False, encoding="utf-8")
    funnel_path.write_text(json.dumps({"funnel": funnel}, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Dataset limpio escrito: %s (%d filas x %d cols)", dataset_limpio_path, len(df_clean), df_clean.shape[1])

    logger.info(">>> Paso 2 [APIFY EDA]: Generando csv 1, csv 2, csv 3 y xlsx (hoja1..hoja3)...")
    eda_res = run_eda_pipeline(
        dataset_limpio_source=str(dataset_limpio_path),
        top_oportunidades_limit=top_oportunidades_limit,
    )

    csv1_path = dash_dir / "csv_1_localidades_y_riesgo.csv"
    csv2_path = dash_dir / "csv_2_correlaciones_y_distribuciones.csv"
    csv3_path = dash_dir / "csv_3_oportunidades_y_voz_turista.csv"
    unico_path = dash_dir / "dashboard_consolidado.csv"
    xlsx_path = dash_dir / "contenido_graficas_dashboard.xlsx"

    eda_res["csv_1_localidades_y_riesgo"].to_csv(csv1_path, index=False, encoding="utf-8")
    eda_res["csv_2_correlaciones_y_distribuciones"].to_csv(csv2_path, index=False, encoding="utf-8")
    eda_res["csv_3_oportunidades_y_voz_turista"].to_csv(csv3_path, index=False, encoding="utf-8")
    eda_res["dashboard_consolidado"].to_csv(unico_path, index=False, encoding="utf-8")
    xlsx_path.write_bytes(eda_res["xlsx_bytes"])

    logger.info("Salidas Dashboard listas en: %s", dash_dir)
    logger.info("  * csv_1 (hoja1): %s (%d filas)", csv1_path.name, len(eda_res["csv_1_localidades_y_riesgo"]))
    logger.info("  * csv_2 (hoja2): %s (%d filas)", csv2_path.name, len(eda_res["csv_2_correlaciones_y_distribuciones"]))
    logger.info("  * csv_3 (hoja3): %s (%d filas)", csv3_path.name, len(eda_res["csv_3_oportunidades_y_voz_turista"]))
    logger.info("  * dashboard_consolidado: %s (%d filas)", unico_path.name, len(eda_res["dashboard_consolidado"]))
    logger.info("  * xlsx consolidado: %s (%d bytes)", xlsx_path.name, len(eda_res["xlsx_bytes"]))

    return {
        "dataset_limpio_csv": str(dataset_limpio_path),
        "csv_1": str(csv1_path),
        "csv_2": str(csv2_path),
        "csv_3": str(csv3_path),
        "dashboard_consolidado": str(unico_path),
        "xlsx": str(xlsx_path),
        "funnel": funnel,
        "summary": eda_res["summary"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TerraScout AI — Pipeline Producto 1 (ETL + EDA)")
    parser.add_argument("--top-oportunidades", type=int, default=250, help="Tope de lotes en csv_3 (0 = todos)")
    parser.add_argument("--skip-raw-xlsx", action="store_true", help="No regenerar dataset_raw_consolidado.xlsx")
    args = parser.parse_args()
    if not args.skip_raw_xlsx:
        build_raw_consolidated_xlsx()
    res = run_producto1_end_to_end(top_oportunidades_limit=args.top_oportunidades)
    print(json.dumps(res["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
