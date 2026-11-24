"""Núcleo de Machine Learning Hedónico y Arbitraje para TerraScout AI (Producto 2).

Consume `dataset_limpio.csv` producido por `APIFY ETL` (`etl_core.py`) y reglas de
`config/business_rules.json` (con enriquecimiento opcional desde fuentes RAW locales
para corregir localidades sin GPS y extraer señales espaciales/NLP). Implementa:
1. Split anti-leakage (train/test estratificado) previo a cualquier preprocesamiento.
2. Feature engineering espacial y textual sin datos sintéticos ni data leakage.
3. Pipeline `ColumnTransformer` (`StandardScaler` + `OneHotEncoder` + `KMeans` geo +
   `TfidfVectorizer`/`TruncatedSVD`) y comparación 5-Fold CV (`DummyRegressor`,
   `Ridge`, `RandomForest`, `ExtraTrees`, `GradientBoosting`, `HistGradientBoosting`,
   `Ensemble Voting`).
4. Detección de arbitraje out-of-fold (train) + out-of-sample (test) o inferencia.
5. Serialización Pickle (`.pkl`) con verificación exacta `dif_max < 1e-6`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import re
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path
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

_BASE_FEATURES = [
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


def _norm_txt(s: object) -> str:
    clean = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9\s]", " ", clean).strip()


def _haversine_matrix(
    lats1: np.ndarray, lons1: np.ndarray, lats2: np.ndarray, lons2: np.ndarray
) -> np.ndarray:
    earth_r_km = 6371.0
    p1 = np.radians(lats1)[:, None]
    p2 = np.radians(lats2)[None, :]
    l1 = np.radians(lons1)[:, None]
    l2 = np.radians(lons2)[None, :]
    a = np.sin((p2 - p1) / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin((l2 - l1) / 2.0) ** 2
    return 2.0 * earth_r_km * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _load_optional_csv(rel_path: str) -> pd.DataFrame | None:
    resolved = resolve_repo_path(rel_path)
    if resolved is None:
        return None
    return pd.read_csv(resolved)


def _normalize_id_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "id_registro" not in out.columns and "id_publicacion" in out.columns:
        out["id_registro"] = out["id_publicacion"]
    if "id_registro" in out.columns:
        out["id_registro"] = out["id_registro"].astype(str)
    return out


def _fix_missing_gps_localities(
    df: pd.DataFrame,
    rules: dict[str, Any],
    df_topo: pd.DataFrame | None,
) -> pd.DataFrame:
    """Corrige asignaciones de localidad en filas sin GPS usando alias de `business_rules.json`."""
    catalogo = rules.get("localidades_catalogo") or {}
    if df_topo is None or not catalogo or "localidad_raw" not in df.columns:
        return df
    if "latitud" not in df.columns or "longitud" not in df.columns:
        return df

    alias_map: dict[str, str] = {}
    for loc, meta in catalogo.items():
        alias_map[_norm_txt(loc)] = loc
        for alias in (meta.get("alias") or []):
            alias_map[_norm_txt(alias)] = loc
    sorted_aliases = sorted(alias_map.items(), key=lambda x: -len(x[0]))
    topo_idx = df_topo.set_index("barrio_localidad")

    out = df.copy()
    missing_gps = out["latitud"].isna() | out["longitud"].isna()
    for idx, row in out.loc[missing_gps].iterrows():
        haystack = f"{_norm_txt(row.get('localidad_raw', ''))} {_norm_txt(row.get('titulo_publicacion', ''))}"
        matched = next(
            (canon for a_norm, canon in sorted_aliases if a_norm and re.search(rf"\b{re.escape(a_norm)}\b", haystack)),
            None,
        )
        if matched and matched in topo_idx.index and matched != row.get("barrio_localidad"):
            t = topo_idx.loc[matched]
            out.loc[idx, "barrio_localidad"] = matched
            out.loc[idx, "valle_corredor"] = str(t["valle_corredor"])
            out.loc[idx, "lat_eff"] = float(t["latitud_centroide"])
            out.loc[idx, "lon_eff"] = float(t["longitud_centroide"])
            out.loc[idx, "pendiente_media_grados"] = float(t["pendiente_media_grados"])
            out.loc[idx, "ndvi_sombra_verano"] = float(t["ndvi_sombra_verano"])
            out.loc[idx, "distancia_rio_m"] = float(t["distancia_rio_m"])
            out.loc[idx, "riesgo_ambiental"] = str(t["riesgo_ambiental"])
    return out


def enrich_ml_features(
    df_clean: pd.DataFrame,
    rules: dict[str, Any],
    topo_df: pd.DataFrame | None = None,
    campings_df: pd.DataFrame | None = None,
    places_df: pd.DataFrame | None = None,
    raw_ml_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Enriquece `dataset_limpio` con señales reales espaciales y textuales sin fuga de datos."""
    df = _normalize_id_column(df_clean)
    df_topo = topo_df if topo_df is not None else _load_optional_csv("data/aux_topografia_cordoba.csv")
    df_camp = campings_df if campings_df is not None else _load_optional_csv("data/raw/campings_zona_real_raw.csv")
    df_places = places_df if places_df is not None else _load_optional_csv("data/raw/google_maps_campings_places_raw.csv")
    df_raw = raw_ml_df if raw_ml_df is not None else _load_optional_csv(
        "data/raw/mercadolibre_terrenos_calamuchita_punilla_raw.csv"
    )

    if df_raw is not None and "id_publicacion" in df_raw.columns and "id_registro" in df.columns:
        raw_cols = [c for c in ("descripcion_completa", "localidad_raw", "es_tienda_oficial", "latitud", "longitud")
                    if c in df_raw.columns and c not in df.columns]
        if raw_cols:
            raw_idx = df_raw.drop_duplicates("id_publicacion").assign(
                id_publicacion=lambda d: d["id_publicacion"].astype(str)
            ).set_index("id_publicacion")
            df = df.merge(raw_idx[raw_cols], left_on="id_registro", right_index=True, how="left")

    df = _fix_missing_gps_localities(df, rules, df_topo)

    # Asegurar indicadores individuales si solo vienen columnas base
    for col in ("tiene_agua", "tiene_luz", "tiene_escritura", "tiene_arboleda", "tiene_rio", "tiene_servicios"):
        if col not in df.columns:
            df[col] = 0

    sup = pd.to_numeric(df["superficie_m2"], errors="coerce").clip(lower=1.0)
    df["log_superficie"] = np.log1p(sup)
    df["inv_sqrt_sup"] = 1.0 / np.sqrt(sup)
    lat_arr = pd.to_numeric(df["lat_eff"], errors="coerce").to_numpy(dtype=float)
    lon_arr = pd.to_numeric(df["lon_eff"], errors="coerce").to_numpy(dtype=float)
    df["lat_lon_rot1"] = lat_arr + lon_arr
    df["lat_lon_rot2"] = lat_arr - lon_arr

    # Distancias Haversine a los 16 centroides de localidades (siempre consistente con topo)
    dist_loc_cols: list[str] = []
    if df_topo is not None and not df_topo.empty:
        d_topo = _haversine_matrix(
            lat_arr,
            lon_arr,
            df_topo["latitud_centroide"].to_numpy(dtype=float),
            df_topo["longitud_centroide"].to_numpy(dtype=float),
        )
        for i in range(len(df_topo)):
            col = f"dist_loc_{i}"
            df[col] = d_topo[:, i]
            dist_loc_cols.append(col)
        df["dist_centroide_min"] = d_topo.min(axis=1)
    else:
        df["dist_centroide_min"] = 0.0

    # Densidad multi-radio de campings y demanda Google Maps
    if df_camp is not None and not df_camp.empty:
        c_valid = df_camp.dropna(subset=["latitud", "longitud"])
        d_camp = _haversine_matrix(
            lat_arr,
            lon_arr,
            pd.to_numeric(c_valid["latitud"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(c_valid["longitud"], errors="coerce").to_numpy(dtype=float),
        )
        df["campings_2km"] = (d_camp <= 2.0).sum(axis=1)
        df["campings_10km"] = (d_camp <= 10.0).sum(axis=1)
    else:
        df["campings_2km"] = 0
        df["campings_10km"] = pd.to_numeric(df.get("campings_5km", 0), errors="coerce").fillna(0)

    if df_places is not None and not df_places.empty:
        p_valid = df_places.dropna(subset=["latitud", "longitud"])
        d_pl = _haversine_matrix(
            lat_arr,
            lon_arr,
            pd.to_numeric(p_valid["latitud"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(p_valid["longitud"], errors="coerce").to_numpy(dtype=float),
        )
        df["places_5km"] = (d_pl <= 5.0).sum(axis=1)
        rev_w = pd.to_numeric(p_valid["reviews_count"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        df["log_reviews_5km"] = np.log1p(np.where(d_pl <= 5.0, rev_w[None, :], 0.0).sum(axis=1))
    else:
        df["places_5km"] = 0
        df["log_reviews_5km"] = 0.0

    # Señales reales de texto (título + descripción si está disponible)
    tit = df["titulo_publicacion"].fillna("") if "titulo_publicacion" in df.columns else pd.Series("", index=df.index)
    desc = df["descripcion_completa"].fillna("") if "descripcion_completa" in df.columns else pd.Series("", index=df.index)
    txt_all = (tit + " " + desc).str.lower()
    df["kw_lago_dique"] = txt_all.str.contains(r"\blago\b|\bdique\b|costa del lago|frente al lago", regex=True).astype(int)
    df["kw_barrio_privado"] = txt_all.str.contains(
        r"barrio privado|barrio cerrado|country|condominio|club de campo", regex=True
    ).astype(int)
    df["kw_ruta_asfalto"] = txt_all.str.contains(r"sobre ruta|asfalto|asfaltada|pavimento|ruta \d+", regex=True).astype(int)
    df["kw_construido"] = txt_all.str.contains(
        r"casa|cabana|cabaña|construid|preventa|complejo|quincho|pileta|piscina|galpon", regex=True
    ).astype(int)
    df["kw_financiacion"] = txt_all.str.contains(r"financiaci|cuotas|anticipo|entrega|permuta", regex=True).astype(int)
    df["kw_esquina"] = txt_all.str.contains(r"\besquina\b|doble frente", regex=True).astype(int)
    df["kw_vista"] = txt_all.str.contains(r"vista panoramica|vista a las sierras|vista al lago|vistas", regex=True).astype(int)
    df["kw_loteo"] = txt_all.str.contains(r"loteo|urbanizaci|parcela|fraccion|fracción", regex=True).astype(int)
    df["kw_gas"] = txt_all.str.contains(r"gas natural", regex=True).astype(int)
    df["kw_alambrado"] = txt_all.str.contains(r"alambrado|perimetrado|cerrado", regex=True).astype(int)
    df["txt_len"] = np.log1p(desc.str.len())
    df["es_tienda_oficial_int"] = (
        df["es_tienda_oficial"].fillna(False).astype(int) if "es_tienda_oficial" in df.columns else 0
    )
    df["texto_full"] = (tit + " " + desc).str.strip()

    num_features = [
        "superficie_m2",
        "log_superficie",
        "inv_sqrt_sup",
        "lat_eff",
        "lon_eff",
        "lat_lon_rot1",
        "lat_lon_rot2",
        "score_servicios",
        "tiene_agua",
        "tiene_luz",
        "tiene_escritura",
        "tiene_arboleda",
        "tiene_rio",
        "tiene_servicios",
        "pendiente_media_grados",
        "ndvi_sombra_verano",
        "distancia_rio_m",
        "campings_2km",
        "campings_5km",
        "campings_10km",
        "distancia_camping_min_km",
        "nps_proxy_zona",
        "places_5km",
        "log_reviews_5km",
        "dist_centroide_min",
        "kw_lago_dique",
        "kw_barrio_privado",
        "kw_ruta_asfalto",
        "kw_construido",
        "kw_financiacion",
        "kw_esquina",
        "kw_vista",
        "kw_loteo",
        "kw_gas",
        "kw_alambrado",
        "txt_len",
        "es_tienda_oficial_int",
    ] + dist_loc_cols

    meta = {
        "num_features": num_features,
        "cat_features": list(_DEFAULT_CATEGORICAL),
        "text_column": "texto_full",
        "feature_columns": num_features + list(_DEFAULT_CATEGORICAL) + ["texto_full"],
    }
    return df, meta


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
        imps = [np.asarray(est.feature_importances_, dtype=float) for est in model.estimators_ if hasattr(est, "feature_importances_")]
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

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        df, _ = enrich_ml_features(df, rules)
        for col in missing:
            if col not in df.columns:
                df[col] = 0.0

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

    drop_internal = [c for c in df.columns if c.startswith("dist_loc_") or c in ("texto_full", "descripcion_completa", "localidad_raw", "latitud", "longitud")]
    if arb["ocultar_pii"]:
        drop_internal.extend([c for c in _PII_COLUMNS if c in df.columns])
    df = df.drop(columns=[c for c in dict.fromkeys(drop_internal) if c in df.columns])

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
