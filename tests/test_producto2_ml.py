"""Tests unitarios e integración para Producto 2 (APIFY ML + Valuación Hedónica + Arbitraje)."""

from __future__ import annotations

import ast
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from actors.apify_etl.my_actor.etl_core import run_etl_pipeline  # noqa: E402
from actors.apify_ml.my_actor.preprocessing import (  # noqa: E402
    load_business_rules,
    load_clean_dataset,
)
from actors.apify_ml.my_actor.tooling_business import (  # noqa: E402
    build_validation_sample,
    execute_ml_actor,
    score_opportunities,
)
from src.run_producto2_pipeline import (  # noqa: E402
    run_producto2_inference,
    run_producto2_train,
)
from src.training import train_and_evaluate_hedonic_model  # noqa: E402


def _get_clean_df() -> pd.DataFrame:
    csv_path = REPO_ROOT / "data" / "processed" / "dataset_limpio.csv"
    if csv_path.is_file():
        return load_clean_dataset(str(csv_path))
    df_clean, _ = run_etl_pipeline()
    return df_clean


class TestActorMLEstructuraYReglasR1aR4:
    def test_archivos_requeridos_apify_ml(self):
        actor_dir = REPO_ROOT / "actors" / "apify_ml"
        assert (actor_dir / "Dockerfile").is_file()
        assert (actor_dir / "requirements.txt").is_file()
        assert (actor_dir / ".actor" / "actor.json").is_file()
        assert (actor_dir / ".actor" / "input_schema.json").is_file()
        assert (actor_dir / ".actor" / "dataset_schema.json").is_file()
        assert (actor_dir / ".actor" / "output_schema.json").is_file()
        assert (actor_dir / "my_actor" / "main.py").is_file()
        assert (actor_dir / "my_actor" / "__main__.py").is_file()
        assert (actor_dir / "my_actor" / "preprocessing.py").is_file()
        assert (actor_dir / "my_actor" / "tooling_business.py").is_file()
        assert (actor_dir / "my_actor" / "sdk_compat.py").is_file()

    def test_main_py_puro_sin_logica_ni_loops_r4(self):
        mp = REPO_ROOT / "actors" / "apify_ml" / "my_actor" / "main.py"
        src = mp.read_text(encoding="utf-8")
        tree = ast.parse(src)
        assert not any(isinstance(n, (ast.For, ast.While, ast.AsyncFor)) for n in ast.walk(tree))
        assert not any(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
        for forbidden in ("urllib", "requests", "sklearn", "pandas"):
            assert forbidden not in src

    def test_actor_ml_solo_inferencia_sin_entrenamiento(self):
        actor_dir = REPO_ROOT / "actors" / "apify_ml"
        forbidden_tokens = (
            "train_and_evaluate_hedonic_model",
            "train_test_split",
            "cross_val_score",
            "VotingRegressor",
            "ExtraTreesRegressor",
            '"reentrenar"',
        )
        files_to_check = list((actor_dir / "my_actor").glob("*.py")) + [
            actor_dir / ".actor" / "input_schema.json",
            actor_dir / ".actor" / "output_schema.json",
        ]
        for path in files_to_check:
            txt = path.read_text(encoding="utf-8")
            for tok in forbidden_tokens:
                assert tok not in txt, f"Se encontró token de entrenamiento '{tok}' en {path}"

    def test_sin_np_random_en_producto2(self):
        for p in (
            REPO_ROOT / "actors" / "apify_ml" / "my_actor" / "preprocessing.py",
            REPO_ROOT / "actors" / "apify_ml" / "my_actor" / "tooling_business.py",
            REPO_ROOT / "src" / "training.py",
            REPO_ROOT / "src" / "run_producto2_pipeline.py",
        ):
            assert "np.random" not in p.read_text(encoding="utf-8")


class TestModeladoHedonicoYArbitraje:
    def test_entrenamiento_anti_leakage_y_pickle_roundtrip(self):
        rules = load_business_rules(str(REPO_ROOT / "config" / "business_rules.json"))
        df_clean = _get_clean_df()
        assert len(df_clean) == 894

        res = train_and_evaluate_hedonic_model(df_clean, rules)
        assert res["dif_max"] < 1e-6
        assert len(res["comparison"]) == 7

        by_name = {m["modelo"]: m for m in res["comparison"]}
        assert res["winner_metrics"]["r2_cv_mean"] > by_name["Baseline (Dummy mediana)"]["r2_cv_mean"]
        assert res["winner_metrics"]["mae_test_usd_m2"] < by_name["Baseline (Dummy mediana)"]["mae_test_usd_m2"]

        loaded = pickle.loads(res["pkl_bytes"])
        assert loaded["target_log_transformed"] is True
        assert loaded["precio_m2_max"] >= 150.0
        assert len(loaded["feature_columns"]) >= 15

        oport = res["df_oportunidades"]
        assert len(oport) > 0
        assert (oport["gap_arbitraje_pct"] >= 20.0).all()
        assert (oport["pendiente_media_grados"] <= 12.0).all()
        assert (oport["riesgo_ambiental"] != "ALTO").all()
        assert "telefono_en_descripcion" not in res["df_scored"].columns
        assert "vendedor_nombre" not in res["df_scored"].columns

        muestra = build_validation_sample(oport, max_rows=30)
        assert len(muestra) == min(30, len(oport))
        assert {"existe_lote", "superficie_ok", "lejos_del_rio", "terreno_plano"}.issubset(muestra.columns)

    def test_pipeline_local_train_y_inferencia_desde_raw_sin_duplicar_alertas(self, tmp_path: Path):
        out_dir = tmp_path / "p2_out"
        mod_dir = tmp_path / "models"
        clean_csv = REPO_ROOT / "data" / "processed" / "dataset_limpio.csv"
        train_res = run_producto2_train(
            dataset_limpio_path=clean_csv if clean_csv.is_file() else None,
            from_raw=not clean_csv.is_file(),
            output_dir=out_dir,
            models_dir=mod_dir,
        )
        assert Path(train_res["pkl_path"]).is_file()
        assert Path(train_res["oportunidades_csv"]).is_file()
        assert Path(train_res["validacion_csv"]).is_file()
        assert train_res["metricas"]["serialization_dif_max"] < 1e-6

        # Inferencia punta a punta desde publicaciones CRUDAS de Mercado Libre vía etl_core
        raw_df = pd.read_csv(REPO_ROOT / "data" / "raw" / "mercadolibre_terrenos_calamuchita_punilla_raw.csv").head(60)
        raw_sample_csv = tmp_path / "lote_semanal_raw.csv"
        raw_df.to_csv(raw_sample_csv, index=False)
        hist_csv = tmp_path / "alertas_historial.csv"

        inf1 = run_producto2_inference(
            input_path=raw_sample_csv,
            model_path=Path(train_res["pkl_path"]),
            output_dir=out_dir,
            historial_path=hist_csv,
            is_raw_ml=True,
        )
        assert inf1["summary"]["lotes_limpios"] > 0
        assert Path(inf1["alertas_csv"]).is_file()

        # Segunda corrida con el mismo lote: las alertas previas no deben repetirse
        inf2 = run_producto2_inference(
            input_path=raw_sample_csv,
            model_path=Path(train_res["pkl_path"]),
            output_dir=out_dir,
            historial_path=hist_csv,
            is_raw_ml=True,
        )
        assert inf2["summary"]["alertas_nuevas"] == 0

    def test_execute_ml_actor_sdk_inferencia(self):
        df_clean = _get_clean_df()
        clean_records = json.loads(df_clean.to_json(orient="records"))
        rules_text = (REPO_ROOT / "config" / "business_rules.json").read_text(encoding="utf-8")
        rules = json.loads(rules_text)

        train_res = train_and_evaluate_hedonic_model(df_clean, rules)
        first_id = str(train_res["df_oportunidades"].iloc[0]["id_registro"])

        out_inf = execute_ml_actor(
            inp={"ids_ya_alertados": [first_id]},
            sdk_texts={"rules_json": rules_text},
            sdk_records=clean_records[:50],
            sdk_pkl_bytes=train_res["pkl_bytes"],
        )
        assert out_inf["summary"]["modo"] == "inferencia"
        assert out_inf["summary"]["total_lotes_evaluados"] == 50
        assert len(out_inf["metricas_payload"]["artifacts_sha256"]["predicciones_producto2_csv"]) == 64
        assert len(out_inf["metricas_payload"]["artifacts_sha256"]["oportunidades_producto2_csv"]) == 64
        assert "terrascout_pipeline_pkl" not in out_inf["metricas_payload"]["artifacts_sha256"]
        assert first_id not in set(out_inf["df_oportunidades"]["id_registro"].astype(str))

    def test_score_opportunities_soporta_dataframe_vacio(self):
        rules = load_business_rules(str(REPO_ROOT / "config" / "business_rules.json"))
        df_clean = _get_clean_df()
        res = train_and_evaluate_hedonic_model(df_clean, rules)
        empty_df = df_clean.iloc[0:0].copy()
        scored, oport = score_opportunities(empty_df, res["bundle"], rules)
        assert scored.empty
        assert oport.empty