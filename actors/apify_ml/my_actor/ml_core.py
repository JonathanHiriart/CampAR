"""Núcleo de Machine Learning Hedónico y Arbitraje para TerraScout AI (Producto 2).

Consume `dataset_limpio.csv` producido por `APIFY ETL` (`etl_core.py`) y reglas de
`config/business_rules.json`. Implementa:
1. Split anti-leakage (train/test estratificado) previo a cualquier preprocesamiento.
2. Pipeline `ColumnTransformer` + comparación 5-Fold CV (`DummyRegressor`, `Ridge`,
   `RandomForestRegressor`, `HistGradientBoostingRegressor`) sobre `log(precio_m2_usd)`.
3. Detección de arbitraje out-of-fold (train) + out-of-sample (test) o inferencia en producción.
4. Serialización Pickle (`.pkl`) con verificación exacta `dif_max < 1e-6`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import re
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

_DEFAULT_FEATURES = [
    "superficie_m2",
    "lat_eff",
    "lon_eff",
    "score_servicios",
    "tiene_escritura",
    "tiene_arboleda",
    "tiene_rio",
    "pendiente_media_grados",
    "ndvi_sombra_verano",
    "distancia_rio_m",
    "campings_5km",
    "distancia_camping_min_km",
    "nps_proxy_zona",
    "valle_corredor",
    "barrio_localidad",
]
_DEFAULT_CATEGORICAL = ["valle_corredor", "barrio_localidad"]
_PII_COLUMNS = ("telefono_en_descripcion", "vendedor_nombre", "url_vendedor")


def sha256_bytes(payload: bytes) -> str:
    """Calcula el hash SHA-256 hexadecimal de un artefacto binario o CSV."""
    return hashlib.sha256(payload).hexdigest()


def normalize_drive_url(url_or_path: str, output_format: str = "csv") -> str:
    """Convierte links compartidos de Google Drive o Sheets en URLs directas de descarga."""
    s = str(url_or_path or "").strip()
    m_sheet = re.search(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", s)
    if m_sheet:
        base = f"https://docs.google.com/spreadsheets/d/{m_sheet.group(1)}/export?format={output_format}"
        if output_format == "csv":
            m_gid = re.search(r"[?&#]gid=(\d+)", s)
            if m_gid:
                base += f"&gid={m_gid.group(1)}"
        return base
    m = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", s)
    if m:
        return f"https://drive.google.com/uc?export=download&confirm=t&id={m.group(1)}"
    m_open = re.search(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)", s)
    if m_open:
        return f"https://drive.google.com/uc?export=download&confirm=t&id={m_open.group(1)}"
    return s


def resolve_repo_path(*candidates: str) -> Path | None:
    """Busca un archivo en fallback_data del actor, directorio actual o raíz del repo."""
    here = Path(__file__).resolve()
    bases = [Path("."), here.parents[1], here.parents[2], here.parents[3]]
    for cand in candidates:
        if not cand:
            continue
        p = Path(cand)
        if p.is_file():
            return p
        for base in bases:
            joined = base / cand
            if joined.is_file():
                return joined
            fb = base / "fallback_data" / Path(cand).name
            if fb.is_file():
                return fb
    return None


class _StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Evita reenviar Authorization a redirecciones externas (ej. S3 presigned URLs)."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None and new_req.host != req.host:
            new_req.remove_header("Authorization")
        return new_req


def _http_get_bytes(url: str, timeout: int = 60, user_agent: str = "TerraScout-ML-Actor/1.0") -> bytes:
    """Descarga bytes vía HTTP(S) evitando reenviar Authorization tras redirecciones."""
    headers = {"User-Agent": user_agent}
    apify_tok = os.getenv("APIFY_TOKEN")
    if url.startswith("https://api.apify.com/") and apify_tok and "token=" not in url:
        headers["Authorization"] = f"Bearer {apify_tok}"
    opener = urllib.request.build_opener(_StripAuthOnRedirect)
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read()
    head = data[:256].decode("utf-8", errors="ignore").lstrip().lower()
    if head.startswith(("<!doctype html", "<html")):
        raise ValueError(
            f"La URL '{url}' devolvió HTML en vez de datos. Verificá que el link de Drive/Sheets sea público."
        )
    return data


def read_bytes_source(url_or_path: str, *local_fallbacks: str, timeout: int = 60) -> bytes:
    """Lee bytes desde HTTP/Drive o disco local."""
    src = str(url_or_path or "").strip()
    if src.startswith(("http://", "https://")):
        direct_url = normalize_drive_url(src, output_format="csv")
        return _http_get_bytes(direct_url, timeout=timeout)
    resolved = resolve_repo_path(src, *local_fallbacks)
    if resolved is None:
        raise FileNotFoundError(f"No se encontró la fuente '{src}' ni fallbacks locales {local_fallbacks}.")
    return resolved.read_bytes()


def load_business_rules(
    rules_json_source: str = "",
    sdk_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Carga `config/business_rules.json` desde texto SDK, HTTP o disco."""
    texts = sdk_texts or {}
    if "rules_json" in texts:
        return json.loads(texts["rules_json"])
    raw_bytes = read_bytes_source(rules_json_source, "config/business_rules.json")
    return json.loads(raw_bytes.decode("utf-8"))


def load_clean_dataset(
    dataset_limpio_source: str = "",
    sdk_texts: dict[str, str] | None = None,
    sdk_records: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Carga `dataset_limpio.csv` desde registros SDK, texto SDK, URL o disco local."""
    if sdk_records is not None:
        return pd.DataFrame(sdk_records)
    texts = sdk_texts or {}
    if "dataset_limpio_csv" in texts:
        txt = texts["dataset_limpio_csv"].lstrip()
        if txt.startswith("["):
            return pd.DataFrame(json.loads(txt))
        return pd.read_csv(io.StringIO(txt))

    src = str(dataset_limpio_source or "").strip()
    raw_bytes = read_bytes_source(src, "data/processed/dataset_limpio.csv")
    text = raw_bytes.decode("utf-8", errors="replace").lstrip()
    if text.startswith("["):
        return pd.DataFrame(json.loads(text))
    return pd.read_csv(io.StringIO(text))


def load_model_bundle(model_pkl_source: str = "", sdk_pkl_bytes: bytes | None = None) -> dict[str, Any]:
    """Deserializa el bundle Pickle (`.pkl`) validando su contrato mínimo."""
    payload = sdk_pkl_bytes if sdk_pkl_bytes is not None else read_bytes_source(
        model_pkl_source, "models/terrascout_pipeline.pkl"
    )
    bundle = pickle.loads(payload)
    for key in ("pipeline", "feature_columns", "target_log_transformed"):
        if key not in bundle:
            raise KeyError(f"El bundle Pickle no contiene la clave obligatoria '{key}'.")
    return bundle


def _ml_config(rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules.get("modelo_ml") or {}
    feature_cols = list(cfg.get("feature_columns") or _DEFAULT_FEATURES)
    cat_cols = [c for c in (cfg.get("categorical_columns") or _DEFAULT_CATEGORICAL) if c in feature_cols]
    num_cols = [c for c in feature_cols if c not in cat_cols]
    return {
        "target_col": str(cfg.get("target_column", "precio_m2_usd")),
        "target_log": bool(cfg.get("target_log_transform", True)),
        "test_size": float(cfg.get("test_size", 0.20)),
        "random_state": int(cfg.get("random_state", 42)),
        "cv_folds": int(cfg.get("cv_folds", 5)),
        "stratify_col": str(cfg.get("stratify_column", "valle_corredor")),
        "feature_cols": feature_cols,
        "cat_cols": cat_cols,
        "num_cols": num_cols,
    }


def _arbitrage_rules(rules: dict[str, Any]) -> dict[str, Any]:
    filtros = rules.get("filtros_terreno") or {}
    arb = rules.get("arbitraje") or {}
    seg = rules.get("seguridad") or {}
    return {
        "pend_alerta": float(filtros.get("pendiente_alerta_grados", 12.0)),
        "gap_min_pct": float(arb.get("umbral_descuento_minimo_pct", 0.20)) * 100.0,
        "gap_sospechoso_pct": float(arb.get("umbral_gap_sospechoso_pct", 0.50)) * 100.0,
        "excluir_riesgo_alto": bool(arb.get("excluir_riesgo_alto", True)),
        "ocultar_pii": bool(seg.get("ocultar_pii_en_salidas", True)),
    }


def build_preprocessor(num_features: list[str], cat_features: list[str]) -> ColumnTransformer:
    """Construye `ColumnTransformer` anti-leakage para variables numéricas y categóricas."""
    return ColumnTransformer(
        transformers=[
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
    )


def _extract_feature_importances(pipeline: Pipeline, top_n: int = 15) -> list[dict[str, Any]]:
    prep = pipeline.named_steps["prep"]
    model = pipeline.named_steps["model"]
    feat_names = prep.get_feature_names_out()
    if hasattr(model, "feature_importances_"):
        raw_imp = np.asarray(model.feature_importances_, dtype=float)
    elif hasattr(model, "coef_"):
        raw_imp = np.abs(np.asarray(model.coef_, dtype=float)).ravel()
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


def _normalize_id_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "id_registro" not in out.columns and "id_publicacion" in out.columns:
        out["id_registro"] = out["id_publicacion"]
    if "id_registro" in out.columns:
        out["id_registro"] = out["id_registro"].astype(str)
    return out


def score_opportunities(
    df_clean: pd.DataFrame,
    bundle: dict[str, Any],
    rules: dict[str, Any],
    pred_m2_override: pd.Series | None = None,
    split_override: pd.Series | None = None,
    ids_ya_alertados: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplica el modelo hedónico y las reglas de arbitraje sobre lotes limpios."""
    arb = _arbitrage_rules(rules)
    feature_cols = list(bundle["feature_columns"])
    target_log = bool(bundle.get("target_log_transformed", True))
    df = _normalize_id_column(df_clean)

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan features requeridas por el modelo: {missing}")

    if df.empty:
        for col in (
            "precio_modelo_m2",
            "precio_modelo_total_usd",
            "gap_arbitraje_pct",
            "es_oportunidad_ml",
            "flag_revision",
            "ya_alertada",
        ):
            df[col] = pd.Series(dtype=object)
        return df, df.copy()

    if pred_m2_override is not None:
        pred_m2 = np.asarray(pred_m2_override.loc[df.index], dtype=float)
    else:
        raw_pred = bundle["pipeline"].predict(df[feature_cols])
        pred_m2 = np.exp(raw_pred) if target_log else np.asarray(raw_pred, dtype=float)

    df["precio_modelo_m2"] = np.round(pred_m2, 2)
    df["precio_modelo_total_usd"] = np.round(df["precio_modelo_m2"] * df["superficie_m2"].astype(float), 0)
    df["gap_arbitraje_pct"] = np.where(
        df["precio_modelo_m2"] > 0,
        ((df["precio_modelo_m2"] - df["precio_m2_usd"].astype(float)) / df["precio_modelo_m2"] * 100.0).round(2),
        0.0,
    )
    if split_override is not None:
        df["split_evaluacion"] = split_override.loc[df.index].to_numpy()
    elif "split_evaluacion" not in df.columns:
        df["split_evaluacion"] = "produccion_unseen"

    cond_riesgo = (df["riesgo_ambiental"] != "ALTO") if arb["excluir_riesgo_alto"] else True
    df["es_oportunidad_ml"] = (
        (df["gap_arbitraje_pct"] >= arb["gap_min_pct"])
        & (df["pendiente_media_grados"].astype(float) <= arb["pend_alerta"])
        & cond_riesgo
    )
    df["flag_revision"] = np.where(
        df["gap_arbitraje_pct"] >= arb["gap_sospechoso_pct"],
        "REVISAR",
        "OK",
    )

    alertados_set = {str(x) for x in (ids_ya_alertados or set())}
    df["ya_alertada"] = df["id_registro"].isin(alertados_set) if "id_registro" in df.columns else False

    if arb["ocultar_pii"]:
        df = df.drop(columns=[c for c in _PII_COLUMNS if c in df.columns])

    oportunidades = (
        df[df["es_oportunidad_ml"] & (~df["ya_alertada"])]
        .sort_values("gap_arbitraje_pct", ascending=False)
        .reset_index(drop=True)
    )
    return df, oportunidades


def build_validation_sample(df_oportunidades: pd.DataFrame, max_rows: int = 30) -> pd.DataFrame:
    """Construye una muestra determinística estratificada por ranking para auditoría manual."""
    if df_oportunidades.empty:
        return pd.DataFrame()
    n = min(max_rows, len(df_oportunidades))
    idx_pos = np.linspace(0, len(df_oportunidades) - 1, num=n, dtype=int)
    cols = [
        c
        for c in (
            "id_registro",
            "valle_corredor",
            "barrio_localidad",
            "precio_usd",
            "superficie_m2",
            "precio_m2_usd",
            "precio_modelo_m2",
            "gap_arbitraje_pct",
            "pendiente_media_grados",
            "riesgo_ambiental",
            "flag_revision",
            "url_publicacion",
            "url_google_maps",
        )
        if c in df_oportunidades.columns
    ]
    muestra = df_oportunidades.iloc[idx_pos][cols].copy().reset_index(drop=True)
    for crit in ("existe_lote", "superficie_ok", "lejos_del_rio", "terreno_plano"):
        muestra[crit] = ""
    muestra["observaciones"] = ""
    return muestra


def format_telegram_summary(df_oportunidades: pd.DataFrame, top_n: int = 8) -> str:
    """Genera resumen compacto sin PII listo para nodos de alerta (Telegram/Email en n8n)."""
    if df_oportunidades.empty:
        return "TerraScout AI (Producto 2): no se detectaron oportunidades nuevas bajo las reglas activas."
    lines = [f"TerraScout AI — Producto 2: {len(df_oportunidades)} oportunidad(es) ML. Top {min(top_n, len(df_oportunidades))}:"]
    for _, r in df_oportunidades.head(top_n).iterrows():
        rev = " [REVISAR]" if r.get("flag_revision") == "REVISAR" else ""
        lines.append(
            f"\n• {r.get('barrio_localidad', '')} ({r.get('valle_corredor', '')}){rev}\n"
            f"  USD {float(r['precio_usd']):,.0f} | {float(r['superficie_m2']):,.0f} m² | "
            f"{float(r['precio_m2_usd']):.1f} vs {float(r['precio_modelo_m2']):.1f} USD/m² "
            f"(gap {float(r['gap_arbitraje_pct']):.1f}%)\n"
            f"  Pendiente {float(r['pendiente_media_grados']):.1f}° | riesgo {r.get('riesgo_ambiental', '')}\n"
            f"  {r.get('url_publicacion', '')}"
        )
    return "\n".join(lines)[:4000]


def train_and_evaluate_hedonic_model(
    df_clean: pd.DataFrame,
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Entrena y evalúa 4 modelos hedónicos sin data leakage y retorna bundle + predicciones OOF/Test."""
    cfg = _ml_config(rules)
    df = _normalize_id_column(df_clean)
    required = cfg["feature_cols"] + [cfg["target_col"], cfg["stratify_col"]]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en dataset_limpio: {missing}")

    df_model = df.dropna(subset=[cfg["target_col"]]).copy()
    target_vals = df_model[cfg["target_col"]].to_numpy(dtype=float)
    y = np.log(target_vals) if cfg["target_log"] else target_vals
    X = df_model[cfg["feature_cols"]].copy()

    strat = df_model[cfg["stratify_col"]] if df_model[cfg["stratify_col"]].nunique() > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=cfg["test_size"],
        random_state=cfg["random_state"],
        stratify=strat,
    )

    preprocessor = build_preprocessor(cfg["num_cols"], cfg["cat_cols"])
    candidates = {
        "Baseline (Dummy mediana)": DummyRegressor(strategy="median"),
        "Ridge Linear": Ridge(alpha=5.0),
        "Random Forest": RandomForestRegressor(
            n_estimators=200, min_samples_leaf=3, random_state=cfg["random_state"]
        ),
        "HistGradientBoosting": HistGradientBoostingRegressor(
            max_depth=5, min_samples_leaf=10, random_state=cfg["random_state"]
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
        "feature_columns": cfg["feature_cols"],
        "categorical_columns": cfg["cat_cols"],
        "numeric_columns": cfg["num_cols"],
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
        prod_pipe, pkl_bytes, X_test, cfg["feature_cols"], target_log=cfg["target_log"]
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


def execute_ml_actor(
    inp: dict[str, Any],
    sdk_texts: dict[str, str] | None = None,
    sdk_records: list[dict[str, Any]] | None = None,
    sdk_pkl_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Orquesta entrenamiento o inferencia de Producto 2 y serializa salidas para Apify/local."""
    rules = load_business_rules(str(inp.get("rules_json_url") or ""), sdk_texts=sdk_texts)
    df_clean = load_clean_dataset(
        str(inp.get("dataset_limpio_url") or ""),
        sdk_texts=sdk_texts,
        sdk_records=sdk_records,
    )
    ids_alertados = {str(x) for x in (inp.get("ids_ya_alertados") or [])}

    model_url = str(inp.get("model_pkl_url") or "").strip()
    has_external_model = (sdk_pkl_bytes is not None) or bool(model_url)
    reentrenar = bool(inp.get("reentrenar", not has_external_model))

    if has_external_model and not reentrenar:
        bundle = load_model_bundle(model_url, sdk_pkl_bytes=sdk_pkl_bytes)
        pkl_bytes = sdk_pkl_bytes if sdk_pkl_bytes is not None else pickle.dumps(bundle)
        df_scored, df_oportunidades = score_opportunities(
            df_clean, bundle, rules, ids_ya_alertados=ids_alertados
        )
        modo = "inferencia"
        comparison = bundle.get("model_comparison", [])
        winner_metrics = bundle.get("metrics_winner", {})
        feature_importances = bundle.get("feature_importances", [])
        dif_max = float(bundle.get("serialization_dif_max", 0.0))
    else:
        train_res = train_and_evaluate_hedonic_model(df_clean, rules)
        bundle = train_res["bundle"]
        pkl_bytes = train_res["pkl_bytes"]
        df_scored = train_res["df_scored"]
        df_oportunidades = train_res["df_oportunidades"]
        if ids_alertados:
            df_scored["ya_alertada"] = df_scored["id_registro"].isin(ids_alertados)
            df_oportunidades = df_oportunidades[~df_oportunidades["id_registro"].isin(ids_alertados)].reset_index(drop=True)
        modo = "entrenamiento_y_evaluacion"
        comparison = train_res["comparison"]
        winner_metrics = train_res["winner_metrics"]
        feature_importances = train_res["feature_importances"]
        dif_max = train_res["dif_max"]

    pred_bytes = df_scored.to_csv(index=False).encode("utf-8")
    oport_bytes = df_oportunidades.to_csv(index=False).encode("utf-8")
    dataset_rows = json.loads(df_oportunidades.to_json(orient="records"))

    summary = {
        "modo": modo,
        "modelo_ganador": bundle["modelo_nombre"],
        "total_lotes_evaluados": int(len(df_scored)),
        "oportunidades_ml": int(len(df_oportunidades)),
        "oportunidades_a_revisar": int((df_oportunidades["flag_revision"] == "REVISAR").sum())
        if len(df_oportunidades)
        else 0,
        "serialization_dif_max": dif_max,
        "sklearn_version": bundle.get("sklearn_version", sklearn.__version__),
    }
    metricas_payload = {
        "summary": summary,
        "winner_metrics": winner_metrics,
        "model_comparison": comparison,
        "feature_importances": feature_importances,
        "rules_snapshot": bundle.get("rules_snapshot", {}),
        "resumen_telegram": format_telegram_summary(df_oportunidades),
        "artifacts_sha256": {
            "predicciones_producto2_csv": sha256_bytes(pred_bytes),
            "oportunidades_producto2_csv": sha256_bytes(oport_bytes),
            "terrascout_pipeline_pkl": sha256_bytes(pkl_bytes),
        },
    }

    return {
        "bundle": bundle,
        "df_scored": df_scored,
        "df_oportunidades": df_oportunidades,
        "predicciones_csv_bytes": pred_bytes,
        "oportunidades_csv_bytes": oport_bytes,
        "pkl_bytes": pkl_bytes,
        "dataset_rows": dataset_rows,
        "summary": summary,
        "metricas_payload": metricas_payload,
    }
