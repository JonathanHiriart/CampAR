"""Ejecutor local del flujo Producto 2: dataset_limpio -> Modelo Hedónico -> Arbitraje ML.

Reutiliza `actors/apify_etl/my_actor/etl_core.py` (cero duplicación de ETL),
`src/training.py` (entrenamiento fuera del Actor Apify) y
`actors/apify_ml/my_actor/{preprocessing.py, tooling_business.py}` para:
  1. Entrenar y comparar 4 modelos sobre `log(precio_m2_usd)` sin data leakage.
  2. Serializar `models/terrascout_pipeline.pkl` con verificación `dif_max < 1e-6`.
  3. Detectar oportunidades de arbitraje OOF + Test y exportar CSVs/JSON/muestra de auditoría.
  4. Ejecutar inferencia semanal (`--infer-only`) sobre publicaciones crudas o limpias nuevas.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Auto-detectar entorno virtual local (.venv en repo o carpeta padre)
try:
    import pandas  # noqa: F401
    import sklearn  # noqa: F401
except ImportError:
    for venv_root in (REPO_ROOT / ".venv", REPO_ROOT.parent / ".venv"):
        for sp in venv_root.glob("lib/python*/site-packages"):
            if sp.is_dir():
                sys.path.append(str(sp))

sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
from actors.apify_etl.my_actor.etl_core import run_etl_pipeline  # noqa: E402
from actors.apify_ml.my_actor.preprocessing import (  # noqa: E402
    load_business_rules,
    load_clean_dataset,
)
from actors.apify_ml.my_actor.tooling_business import (  # noqa: E402
    build_validation_sample,
    format_telegram_summary,
    load_model_bundle,
    score_opportunities,
)
from src.training import train_and_evaluate_hedonic_model  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_producto2_pipeline")


def run_producto2_train(
    dataset_limpio_path: Path | None = None,
    from_raw: bool = False,
    output_dir: Path | None = None,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """Entrena el modelo hedónico Producto 2, verifica Pickle y exporta resultados."""
    out_dir = output_dir or (REPO_ROOT / "data" / "processed" / "producto2")
    mod_dir = models_dir or (REPO_ROOT / "models")
    out_dir.mkdir(parents=True, exist_ok=True)
    mod_dir.mkdir(parents=True, exist_ok=True)

    rules = load_business_rules(str(REPO_ROOT / "config" / "business_rules.json"))

    if from_raw:
        logger.info(">>> Ejecutando ETL oficial Producto 1 (etl_core) desde datos crudos...")
        df_clean, _ = run_etl_pipeline()
    else:
        src = str(dataset_limpio_path or (REPO_ROOT / "data" / "processed" / "dataset_limpio.csv"))
        logger.info(">>> Cargando dataset limpio oficial desde: %s", src)
        df_clean = load_clean_dataset(src)

    logger.info(">>> Entrenando y comparando modelos hedónicos (5-Fold CV sobre 80%% train)...")
    res = train_and_evaluate_hedonic_model(df_clean, rules)

    pkl_path = mod_dir / "terrascout_pipeline.pkl"
    pkl_path.write_bytes(res["pkl_bytes"])

    comp_df = pd.DataFrame(res["comparison"])
    comp_path = out_dir / "comparacion_modelos.csv"
    comp_df.to_csv(comp_path, index=False, encoding="utf-8")

    pred_path = out_dir / "predicciones_producto2.csv"
    res["df_scored"].to_csv(pred_path, index=False, encoding="utf-8")

    oport_path = out_dir / "oportunidades_producto2.csv"
    res["df_oportunidades"].to_csv(oport_path, index=False, encoding="utf-8")

    val_df = build_validation_sample(res["df_oportunidades"], max_rows=30)
    val_path = out_dir / "validacion_30_alertas.csv"
    val_df.to_csv(val_path, index=False, encoding="utf-8-sig")

    metricas = {
        "modelo_ganador": res["bundle"]["modelo_nombre"],
        "winner_metrics": res["winner_metrics"],
        "model_comparison": res["comparison"],
        "feature_importances": res["feature_importances"],
        "total_lotes_evaluados": int(len(res["df_scored"])),
        "oportunidades_ml": int(len(res["df_oportunidades"])),
        "oportunidades_a_revisar": int((res["df_oportunidades"]["flag_revision"] == "REVISAR").sum())
        if len(res["df_oportunidades"])
        else 0,
        "serialization_dif_max": res["dif_max"],
        "precio_m2_max": res["bundle"]["precio_m2_max"],
        "sklearn_version": res["bundle"]["sklearn_version"],
        "rules_snapshot": res["bundle"]["rules_snapshot"],
        "resumen_telegram": format_telegram_summary(res["df_oportunidades"]),
    }
    metricas_path = out_dir / "metricas_producto2.json"
    metricas_path.write_text(json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("[OK] Modelo ganador: %s (R2 CV=%.4f, R2 Test=%.4f, MAE=%.2f USD/m2)",
                metricas["modelo_ganador"],
                res["winner_metrics"]["r2_cv_mean"],
                res["winner_metrics"]["r2_test_log"],
                res["winner_metrics"]["mae_test_usd_m2"])
    logger.info("[OK] Pickle verificado: %s (dif_max=%.2e)", pkl_path, res["dif_max"])
    logger.info("[OK] Oportunidades ML detectadas: %d -> %s", metricas["oportunidades_ml"], oport_path)

    return {
        "pkl_path": str(pkl_path),
        "comparacion_csv": str(comp_path),
        "predicciones_csv": str(pred_path),
        "oportunidades_csv": str(oport_path),
        "validacion_csv": str(val_path),
        "metricas_json": str(metricas_path),
        "metricas": metricas,
    }


def run_producto2_inference(
    input_path: Path,
    model_path: Path | None = None,
    output_dir: Path | None = None,
    historial_path: Path | None = None,
    is_raw_ml: bool = False,
) -> dict[str, Any]:
    """Ejecuta inferencia sobre un lote nuevo (crudo o limpio) sin reentrenar el modelo."""
    out_dir = output_dir or (REPO_ROOT / "data" / "processed" / "producto2")
    out_dir.mkdir(parents=True, exist_ok=True)
    mod_path = model_path or (REPO_ROOT / "models" / "terrascout_pipeline.pkl")
    hist_file = historial_path or (out_dir / "alertas_historial.csv")

    rules = load_business_rules(str(REPO_ROOT / "config" / "business_rules.json"))
    bundle = load_model_bundle(str(mod_path))

    if is_raw_ml:
        df_clean, funnel = run_etl_pipeline(
            ml_csv_source=str(input_path),
            precio_m2_max_override=float(bundle.get("precio_m2_max", 150.0)),
        )
    else:
        df_clean = load_clean_dataset(str(input_path))
        funnel = []

    ids_alertados: set[str] = set()
    if hist_file.is_file():
        hist_df = pd.read_csv(hist_file)
        col_id = "id_registro" if "id_registro" in hist_df.columns else "id_publicacion"
        if col_id in hist_df.columns:
            ids_alertados = set(hist_df[col_id].astype(str))

    df_scored, df_nuevas = score_opportunities(
        df_clean,
        bundle,
        rules,
        ids_ya_alertados=ids_alertados,
    )

    alertas_path = out_dir / "alertas_nuevas.csv"
    df_nuevas.to_csv(alertas_path, index=False, encoding="utf-8")

    if not df_nuevas.empty:
        nuevos_ids = pd.DataFrame({
            "id_registro": df_nuevas["id_registro"].astype(str),
            "fecha_alerta": date.today().isoformat(),
        })
        if hist_file.is_file():
            hist_prev = pd.read_csv(hist_file)
            hist_all = pd.concat([hist_prev, nuevos_ids], ignore_index=True)
        else:
            hist_all = nuevos_ids
        hist_all.drop_duplicates(subset=["id_registro"]).to_csv(hist_file, index=False, encoding="utf-8")

    summary = {
        "input": str(input_path),
        "is_raw_ml": is_raw_ml,
        "lotes_limpios": int(len(df_scored)),
        "alertas_nuevas": int(len(df_nuevas)),
        "alertas_a_revisar": int((df_nuevas["flag_revision"] == "REVISAR").sum()) if len(df_nuevas) else 0,
        "etl_funnel": funnel,
        "resumen_telegram": format_telegram_summary(df_nuevas),
    }
    return {
        "alertas_csv": str(alertas_path),
        "historial_csv": str(hist_file),
        "df_scored": df_scored,
        "df_nuevas": df_nuevas,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TerraScout AI — Pipeline Producto 2 (ML Hedónico)")
    parser.add_argument("--from-raw", action="store_true", help="Ejecuta ETL oficial desde data/raw/ antes de entrenar")
    parser.add_argument("--infer-only", action="store_true", help="Solo inferencia usando models/terrascout_pipeline.pkl")
    parser.add_argument("--input", type=str, default="", help="CSV de entrada para --infer-only (limpio o crudo ML)")
    parser.add_argument("--raw-input", action="store_true", help="Indica que --input es CSV crudo de Mercado Libre")
    parser.add_argument("--modelo", type=str, default="", help="Ruta alternativa al .pkl")
    parser.add_argument("--historial", type=str, default="", help="CSV con id_registro ya alertados")
    args = parser.parse_args(argv)

    if args.infer_only:
        if not args.input:
            parser.error("--infer-only requiere --input <ruta_csv>")
        res = run_producto2_inference(
            input_path=Path(args.input),
            model_path=Path(args.modelo) if args.modelo else None,
            historial_path=Path(args.historial) if args.historial else None,
            is_raw_ml=args.raw_input,
        )
        print(json.dumps(res["summary"], indent=2, ensure_ascii=False))
        return 0

    res = run_producto2_train(from_raw=args.from_raw)
    print(json.dumps(res["metricas"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())