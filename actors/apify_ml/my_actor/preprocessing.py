"""Preprocesamiento e ingeniería de features para TerraScout AI (Actor 3 — Inferencia ML).

Consume `dataset_limpio.csv` producido por `APIFY ETL` (`etl_core.py`) y reglas de
`config/business_rules.json` (con enriquecimiento opcional desde fuentes RAW locales
para corregir localidades sin GPS y extraer señales espaciales/NLP sin fuga de datos).
"""

from __future__ import annotations

import io
import json
import os
import re
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

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