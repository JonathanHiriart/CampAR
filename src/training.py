"""Entrenamiento y evaluación anti-leakage del modelo hedónico CampAR (fuera del Actor Apify).

Reutiliza `actors.apify_ml.my_actor.preprocessing` (`enrich_ml_features`) y
`actors.apify_ml.my_actor.tooling_business` (`score_opportunities`) para:
1. Split anti-leakage (train/test estratificado) previo a cualquier preprocesamiento.
2. Pipeline `ColumnTransformer` (`StandardScaler` + `OneHotEncoder` + `KMeans` geo +
   `TfidfVectorizer`/`TruncatedSVD`) y comparación 5-Fold CV (`DummyRegressor`,
   `Ridge`, `RandomForest`, `ExtraTrees`, `GradientBoosting`, `HistGradientBoosting`,
   `Ensemble Voting`).
3. Detección de arbitraje out-of-fold (train) + out-of-sample (test).
4. Serialización Pickle (`.pkl`) con verificación exacta `dif_max < 1e-6`.
"""

from __future__ import annotations

import pickle
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import TruncatedSVD
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import (
    ExtraTreesRegressor,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
    VotingRegressor,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from actors.apify_ml.my_actor.preprocessing import (
    _BASE_FEATURES,
    _DEFAULT_CATEGORICAL,
    _normalize_id_column,
    enrich_ml_features,
)
from actors.apify_ml.my_actor.tooling_business import _arbitrage_rules, score_opportunities


def _ml_config(rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules.get("modelo_ml") or {}
    base_feats = list(cfg.get("feature_columns") or _BASE_FEATURES)
    cat_cols = [c for c in (cfg.get("categorical_columns") or _DEFAULT_CATEGORICAL) if c in base_feats]
    return {
        "target_col": str(cfg.get("target_column", "precio_m2_usd")),
        "target_log": bool(cfg.get("target_log_transform", True)),
        "test_size": float(cfg.get("test_size", 0.20)),
        "random_state": int(cfg.get("random_state", 42)),
        "cv_folds": int(cfg.get("cv_folds", 5)),
        "stratify_col": str(cfg.get("stratify_column", "valle_corredor")),
        "base_features": base_feats,
        "cat_cols": cat_cols,
    }


def build_preprocessor(
    num_features: list[str],
    cat_features: list[str],
    text_column: str = "texto_full",
    n_samples: int = 894,
    random_state: int = 42,
    use_text_and_clusters: bool = True,
) -> ColumnTransformer:
    """Construye `ColumnTransformer` anti-leakage con escalado, OHE, KMeans geo y TF-IDF/SVD."""
    transformers: list[tuple[str, Any, Any]] = [
        (
            "num",
            Pipeline([("imp", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]),
            num_features,
        ),
        (
            "cat",
            Pipeline([
                ("imp", SimpleImputer(strategy="most_frequent")),
                ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]),
            cat_features,
        ),
    ]
    if use_text_and_clusters and n_samples >= 60:
        n_clusters = min(30, max(5, n_samples // 25))
        transformers.append(
            (
                "geo_cl",
                Pipeline([
                    ("imp", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                    ("km", KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state)),
                ]),
                ["lat_eff", "lon_eff"],
            )
        )
        transformers.append(
            (
                "txt",
                Pipeline([
                    ("tf", TfidfVectorizer(max_features=400, ngram_range=(1, 2), min_df=3)),
                    ("svd", TruncatedSVD(n_components=20, random_state=random_state)),
                ]),
                text_column,
            )
        )
    return ColumnTransformer(transformers=transformers)


def _extract_feature_importances(pipeline: Pipeline, top_n: int = 15) -> list[dict[str, Any]]:
    prep = pipeline.named_steps["prep"]
    model = pipeline.named_steps["model"]
    feat_names = prep.get_feature_names_out()
    if hasattr(model, "feature_importances_"):
        raw_imp = np.asarray(model.feature_importances_, dtype=float)
    elif hasattr(model, "coef_"):
        raw_imp = np.abs(np.asarray(model.coef_, dtype=float)).ravel()
    elif hasattr(model, "estimators_"):
        imps = [
            np.asarray(est.feature_importances_, dtype=float)
            for est in model.estimators_
            if hasattr(est, "feature_importances_")
        ]
        if not imps:
            return []
        raw_imp = np.mean(imps, axis=0)
    else:
        return []
    total = float(raw_imp.sum()) or 1.0
    order = np.argsort(raw_imp)[::-1][:top_n]
    return [
        {
            "feature": str(feat_names[i]),
            "importancia": round(float(raw_imp[i]), 4),
            "importancia_pct": round(float(raw_imp[i] / total * 100.0), 2),
        }
        for i in order
    ]


def verify_pickle_roundtrip(
    pipeline: Pipeline,
    bundle_bytes: bytes,
    X_sample: pd.DataFrame,
    feature_columns: list[str],
    target_log: bool = True,
) -> float:
    """Verifica que el modelo deserializado reproduzca exactamente las predicciones en memoria."""
    loaded = pickle.loads(bundle_bytes)
    raw_mem = pipeline.predict(X_sample[feature_columns])
    raw_disk = loaded["pipeline"].predict(X_sample[feature_columns])
    pred_mem = np.exp(raw_mem) if target_log else raw_mem
    pred_disk = np.exp(raw_disk) if target_log else raw_disk
    dif_max = float(np.max(np.abs(pred_mem - pred_disk)))
    if dif_max >= 1e-6:
        raise AssertionError(f"Error de serialización Pickle: dif_max={dif_max:.3e} >= 1e-6")
    return dif_max


def train_and_evaluate_hedonic_model(
    df_clean: pd.DataFrame,
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Entrena y evalúa 7 modelos hedónicos sin data leakage y retorna bundle + predicciones OOF/Test."""
    cfg = _ml_config(rules)
    df_norm = _normalize_id_column(df_clean)
    required_base = cfg["base_features"] + [cfg["target_col"], cfg["stratify_col"]]
    missing = [c for c in required_base if c not in df_norm.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en dataset_limpio: {missing}")

    df_model, feat_meta = enrich_ml_features(df_norm, rules)
    df_model = df_model.dropna(subset=[cfg["target_col"]]).copy()
    target_vals = df_model[cfg["target_col"]].to_numpy(dtype=float)
    y = np.log(target_vals) if cfg["target_log"] else target_vals

    feature_cols = feat_meta["feature_columns"]
    X = df_model[feature_cols].copy()

    strat = df_model[cfg["stratify_col"]] if df_model[cfg["stratify_col"]].nunique() > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=cfg["test_size"],
        random_state=cfg["random_state"],
        stratify=strat,
    )

    preprocessor = build_preprocessor(
        feat_meta["num_features"],
        feat_meta["cat_features"],
        text_column=feat_meta["text_column"],
        n_samples=len(X_train),
        random_state=cfg["random_state"],
        use_text_and_clusters=True,
    )

    et_est = ExtraTreesRegressor(
        n_estimators=500, min_samples_leaf=2, max_features=0.5, random_state=cfg["random_state"]
    )
    gbr_est = GradientBoostingRegressor(
        n_estimators=250, max_depth=3, learning_rate=0.04, subsample=0.8, random_state=cfg["random_state"]
    )
    hgbr_est = HistGradientBoostingRegressor(
        max_depth=5, min_samples_leaf=10, learning_rate=0.04, max_iter=250, random_state=cfg["random_state"]
    )

    candidates = {
        "Baseline (Dummy mediana)": DummyRegressor(strategy="median"),
        "Ridge Linear": Ridge(alpha=10.0),
        "Random Forest": RandomForestRegressor(
            n_estimators=300, min_samples_leaf=2, max_features=0.5, random_state=cfg["random_state"]
        ),
        "ExtraTrees": et_est,
        "GradientBoosting": gbr_est,
        "HistGradientBoosting": hgbr_est,
        "Ensemble (2ET + GBR + HGBR)": VotingRegressor(
            [("et", clone(et_est)), ("gbr", clone(gbr_est)), ("hgbr", clone(hgbr_est))],
            weights=[2, 1, 1],
        ),
    }

    cv = KFold(n_splits=cfg["cv_folds"], shuffle=True, random_state=cfg["random_state"])
    comparison: list[dict[str, Any]] = []
    trained_val_pipes: dict[str, Pipeline] = {}

    for name, estimator in candidates.items():
        pipe = Pipeline([("prep", clone(preprocessor)), ("model", estimator)])
        cv_r2 = cross_val_score(pipe, X_train, y_train, cv=cv, scoring="r2")
        pipe.fit(X_train, y_train)
        trained_val_pipes[name] = pipe

        pred_test_raw = pipe.predict(X_test)
        pred_test_usd = np.exp(pred_test_raw) if cfg["target_log"] else pred_test_raw
        real_test_usd = np.exp(y_test) if cfg["target_log"] else y_test

        comparison.append({
            "modelo": name,
            "r2_cv_mean": round(float(cv_r2.mean()), 4),
            "r2_cv_std": round(float(cv_r2.std()), 4),
            "r2_test_log": round(float(r2_score(y_test, pred_test_raw)), 4),
            "mae_test_usd_m2": round(float(mean_absolute_error(real_test_usd, pred_test_usd)), 2),
            "rmse_test_usd_m2": round(float(np.sqrt(mean_squared_error(real_test_usd, pred_test_usd))), 2),
        })

    comparison.sort(key=lambda r: (-r["r2_cv_mean"], r["mae_test_usd_m2"]))
    winner_metrics = comparison[0]
    winner_name = winner_metrics["modelo"]
    winner_val_pipe = trained_val_pipes[winner_name]

    # Predicciones honestas sin leakage para todo el histórico (OOF en train + out-of-sample en test)
    oof_train_raw = cross_val_predict(clone(winner_val_pipe), X_train, y_train, cv=cv)
    pred_test_raw = winner_val_pipe.predict(X_test)
    oof_train_m2 = np.exp(oof_train_raw) if cfg["target_log"] else oof_train_raw
    pred_test_m2 = np.exp(pred_test_raw) if cfg["target_log"] else pred_test_raw

    pred_series = pd.Series(index=df_model.index, dtype=float)
    pred_series.loc[X_train.index] = oof_train_m2
    pred_series.loc[X_test.index] = pred_test_m2

    split_series = pd.Series(index=df_model.index, dtype=object)
    split_series.loc[X_train.index] = "train_oof"
    split_series.loc[X_test.index] = "test"

    # Reentrenamiento final sobre 100% de X limpio para inferencia futura en producción
    prod_pipe = clone(winner_val_pipe).fit(X, y)
    q1, q3 = df_model[cfg["target_col"]].quantile([0.25, 0.75])
    iqr_lim = float(q3 + 3.0 * (q3 - q1))
    precio_m2_max = max(iqr_lim, 150.0) if np.isfinite(iqr_lim) else 150.0

    top_importances = _extract_feature_importances(prod_pipe, top_n=15)
    arb = _arbitrage_rules(rules)

    bundle = {
        "pipeline": prod_pipe,
        "modelo_nombre": winner_name,
        "feature_columns": feature_cols,
        "categorical_columns": feat_meta["cat_features"],
        "numeric_columns": feat_meta["num_features"],
        "target_column": cfg["target_col"],
        "target_log_transformed": cfg["target_log"],
        "sklearn_version": sklearn.__version__,
        "precio_m2_max": round(precio_m2_max, 2),
        "fecha_entrenamiento": date.today().isoformat(),
        "n_filas_entrenamiento": int(len(X)),
        "n_filas_train_split": int(len(X_train)),
        "n_filas_test_split": int(len(X_test)),
        "rules_snapshot": {
            "tipo_cambio_ars_usd": float(rules.get("tipo_cambio_ars_usd", 1280.0)),
            "pendiente_alerta_grados": arb["pend_alerta"],
            "gap_min_arbitraje_pct": arb["gap_min_pct"],
            "gap_sospechoso_pct": arb["gap_sospechoso_pct"],
            "excluir_riesgo_alto": arb["excluir_riesgo_alto"],
        },
        "model_comparison": comparison,
        "metrics_winner": winner_metrics,
        "feature_importances": top_importances,
    }
    pkl_bytes = pickle.dumps(bundle)
    dif_max = verify_pickle_roundtrip(
        prod_pipe, pkl_bytes, X_test, feature_cols, target_log=cfg["target_log"]
    )
    bundle["serialization_dif_max"] = dif_max
    pkl_bytes = pickle.dumps(bundle)

    df_scored, df_oportunidades = score_opportunities(
        df_model,
        bundle,
        rules,
        pred_m2_override=pred_series,
        split_override=split_series,
    )

    return {
        "bundle": bundle,
        "pkl_bytes": pkl_bytes,
        "dif_max": dif_max,
        "comparison": comparison,
        "winner_metrics": winner_metrics,
        "feature_importances": top_importances,
        "df_scored": df_scored,
        "df_oportunidades": df_oportunidades,
    }
