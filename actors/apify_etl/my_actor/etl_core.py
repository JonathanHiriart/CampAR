"""Núcleo ETL puro para TerraScout AI (Actor 1: APIFY ETL).

Convierte los insumos crudos (Drive/HTTP o disco local) en `dataset_limpio.csv`
aplicando las reglas desacopladas de `config/business_rules.json`, limpieza
trazable sin imputación ciega ni datos sintéticos y JOIN espacial Haversine.
"""

from __future__ import annotations

import io
import json
import os
import re
import unicodedata
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_PLACEHOLDER_PRICES = {101010101.0, 111111111.0, 99999999.0, 123456789.0}


def normalize_drive_url(url_or_path: str) -> str:
    """Convierte links compartidos de Google Drive o Sheets en URLs directas de descarga."""
    s = str(url_or_path or "").strip()
    m_sheet = re.search(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", s)
    if m_sheet:
        return f"https://docs.google.com/spreadsheets/d/{m_sheet.group(1)}/export?format=csv"
    m = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", s)
    if m:
        return f"https://drive.google.com/uc?export=download&confirm=t&id={m.group(1)}"
    m_open = re.search(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)", s)
    if m_open:
        return f"https://drive.google.com/uc?export=download&confirm=t&id={m_open.group(1)}"
    return s


def resolve_repo_path(*candidates: str) -> Path | None:
    """Busca un archivo en fallback_data del actor, el árbol local o raíz del repo."""
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

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None and new_req.host != req.host:
            new_req.remove_header("Authorization")
        return new_req


def read_text_source(url_or_path: str, *local_fallbacks: str, timeout: int = 60) -> str:
    """Descarga texto desde HTTP/Drive o lee desde disco local."""
    src = str(url_or_path or "").strip()
    if src.startswith(("http://", "https://")):
        direct_url = normalize_drive_url(src)
        headers = {"User-Agent": "TerraScout-ETL-Actor/1.0"}
        apify_tok = os.getenv("APIFY_TOKEN")
        if direct_url.startswith("https://api.apify.com/") and apify_tok and "token=" not in direct_url:
            headers["Authorization"] = f"Bearer {apify_tok}"
        opener = urllib.request.build_opener(_StripAuthOnRedirect)
        req = urllib.request.Request(direct_url, headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        if text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError(
                f"La URL '{src}' devolvió una página HTML en vez de datos. "
                "Si es Google Drive, verificá que esté compartido como 'Cualquiera con el enlace (Lector)'."
            )
        return text

    resolved = resolve_repo_path(src, *local_fallbacks)
    if resolved is None:
        raise FileNotFoundError(
            f"No se encontró la fuente '{src}' ni fallbacks locales {local_fallbacks}."
        )
    return resolved.read_text(encoding="utf-8")


def norm_txt(value: object) -> str:
    """Normaliza cadenas quitando acentos y signos no alfanuméricos."""
    if not isinstance(value, str):
        return ""
    clean = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9\s]", " ", clean).strip()


def extraer_superficie_segura(texto: object) -> float:
    """Extrae superficie en m² evitando capturar distancias (ej. 'a 300 m del río')."""
    if not isinstance(texto, str) or not texto.strip():
        return float("nan")
    patron = r"(?i)(\d+(?:[\.,]\d+)?)\s*(m2|mts2|metros\s*cuadrados|m²|ha|hect[aá]reas)\b"
    for m in re.finditer(patron, texto):
        prev_full = texto[max(0, m.start() - 18):m.start()].lower()
        clause = re.split(r"[,;.\-|/]", prev_full)[-1]
        if any(w in clause for w in ("a ", "distancia", "del rio", "de ruta", "del centro")):
            continue
        raw_num = m.group(1)
        if "." in raw_num and "," not in raw_num and len(raw_num.split(".")[-1]) == 3:
            raw_num = raw_num.replace(".", "")
        else:
            raw_num = raw_num.replace(",", ".")
        try:
            val = float(raw_num)
            unit = m.group(2).lower()
            if "ha" in unit or "hect" in unit:
                val *= 10000.0
            return val
        except ValueError:
            continue
    return float("nan")


def haversine_vec(lat1: float, lon1: float, lat2_arr: np.ndarray, lon2_arr: np.ndarray) -> np.ndarray:
    """Distancia Haversine vectorizada en kilómetros."""
    earth_r_km = 6371.0
    lat1_r, lon1_r = np.radians(lat1), np.radians(lon1)
    lat2_r, lon2_r = np.radians(lat2_arr), np.radians(lon2_arr)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2.0) ** 2
    return 2.0 * earth_r_km * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def run_etl_pipeline(
    ml_csv_source: str = "",
    campings_csv_source: str = "",
    places_csv_source: str = "",
    topo_csv_source: str = "",
    rules_json_source: str = "",
    tipo_cambio_override: float = 0.0,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Ejecuta el ETL completo de Producto 1 y retorna `(df_limpio, funnel)`."""
    rules_raw = read_text_source(rules_json_source, "config/business_rules.json")
    rules: dict[str, Any] = json.loads(rules_raw)

    tipo_cambio = (
        float(tipo_cambio_override)
        if tipo_cambio_override and float(tipo_cambio_override) > 0
        else float(rules["tipo_cambio_ars_usd"])
    )
    filtros = rules["filtros_terreno"]
    sup_min = float(filtros["superficie_minima_m2"])
    sup_max = float(filtros["superficie_maxima_m2"])
    pend_alerta = float(filtros["pendiente_alerta_grados"])
    arb_cfg = rules["arbitraje"]
    umbral_desc_pct = float(arb_cfg["umbral_descuento_minimo_pct"]) * 100.0
    excluir_riesgo_alto = bool(arb_cfg["excluir_riesgo_alto"])

    df_ml = pd.read_csv(
        io.StringIO(
            read_text_source(
                ml_csv_source,
                "data/raw/mercadolibre_terrenos_calamuchita_punilla_raw.csv",
            )
        )
    )
    df_campings = pd.read_csv(
        io.StringIO(
            read_text_source(
                campings_csv_source,
                "data/raw/campings_zona_real_raw.csv",
            )
        )
    )
    df_places = pd.read_csv(
        io.StringIO(
            read_text_source(
                places_csv_source,
                "data/raw/google_maps_campings_places_raw.csv",
            )
        )
    )
    df_topo = pd.read_csv(
        io.StringIO(
            read_text_source(
                topo_csv_source,
                "data/aux_topografia_cordoba.csv",
            )
        )
    )

    funnel: list[dict[str, Any]] = [{"etapa": "0. Crudo Mercado Libre", "registros": int(len(df_ml))}]
    df_clean = df_ml.copy()

    # 1. Normalización monetaria y descarte de placeholders/anticipos
    df_clean["precio_num"] = pd.to_numeric(df_clean["precio_raw"], errors="coerce")
    df_clean["moneda_norm"] = df_clean["moneda_raw"].astype(str).str.upper().str.strip()
    df_clean = df_clean[~df_clean["precio_num"].isin(_PLACEHOLDER_PRICES)].copy()

    es_ars = df_clean["moneda_norm"].isin(["ARS", "$", "AR$"])
    df_clean["precio_usd"] = np.where(es_ars, df_clean["precio_num"] / tipo_cambio, df_clean["precio_num"])
    df_clean = df_clean.dropna(subset=["precio_usd"])
    df_clean = df_clean[(df_clean["precio_usd"] >= 3000.0) & (df_clean["precio_usd"] <= 1_500_000.0)].copy()
    df_clean["precio_usd"] = df_clean["precio_usd"].round(2)
    funnel.append({"etapa": "1. Precio USD válido", "registros": int(len(df_clean))})

    # 2. Superficie en m² y filtros de dominio
    df_clean["superficie_m2"] = pd.to_numeric(df_clean["superficie_m2_extraida"], errors="coerce")
    mask_na_sup = df_clean["superficie_m2"].isna()
    if mask_na_sup.any() and "superficie_raw_texto" in df_clean.columns:
        df_clean.loc[mask_na_sup, "superficie_m2"] = (
            df_clean.loc[mask_na_sup, "superficie_raw_texto"].apply(extraer_superficie_segura)
        )
    mask_na_sup = df_clean["superficie_m2"].isna()
    if mask_na_sup.any():
        df_clean.loc[mask_na_sup, "superficie_m2"] = (
            df_clean.loc[mask_na_sup, "titulo_publicacion"].apply(extraer_superficie_segura)
        )
    df_clean = df_clean.dropna(subset=["superficie_m2"])
    df_clean = df_clean[(df_clean["superficie_m2"] >= sup_min) & (df_clean["superficie_m2"] <= sup_max)].copy()
    funnel.append({"etapa": f"2. Superficie apta [{sup_min:.0f}-{sup_max:.0f} m²]", "registros": int(len(df_clean))})

    # 3. Target y filtro conservador IQR en USD/m²
    df_clean["precio_m2_usd"] = (df_clean["precio_usd"] / df_clean["superficie_m2"]).round(2)
    q3 = float(df_clean["precio_m2_usd"].quantile(0.75))
    q1 = float(df_clean["precio_m2_usd"].quantile(0.25))
    lim_sup = max(q3 + 3.0 * (q3 - q1), 150.0)
    df_clean = df_clean[(df_clean["precio_m2_usd"] >= 2.0) & (df_clean["precio_m2_usd"] <= lim_sup)].copy()
    funnel.append({"etapa": f"3. Precio/m² válido [2.0-{lim_sup:.1f}]", "registros": int(len(df_clean))})

    # 4. Deduplicación real (por ID y por lote repetido en misma coordenada redondeada)
    df_clean = df_clean.drop_duplicates(subset=["id_publicacion"]).copy()
    df_clean["lat_round"] = pd.to_numeric(df_clean["latitud"], errors="coerce").round(3)
    df_clean["lon_round"] = pd.to_numeric(df_clean["longitud"], errors="coerce").round(3)
    df_clean = df_clean.drop_duplicates(
        subset=["valle_corredor", "superficie_m2", "precio_usd", "lat_round", "lon_round"]
    ).copy()
    funnel.append({"etapa": "4. Deduplicado (ID + lote repetido)", "registros": int(len(df_clean))})

    # 5. Señales de infraestructura en texto libre
    desc_series = df_clean["descripcion_completa"] if "descripcion_completa" in df_clean.columns else ""
    texto_full = (df_clean["titulo_publicacion"].fillna("") + " " + pd.Series(desc_series).fillna("")).apply(norm_txt)
    df_clean["tiene_agua"] = texto_full.str.contains(r"\bagua\b|agua corriente|red de agua", regex=True).astype(int)
    df_clean["tiene_luz"] = texto_full.str.contains(r"\bluz\b|energia electrica|tendido electrico", regex=True).astype(int)
    df_clean["tiene_escritura"] = texto_full.str.contains(r"escritura|escriturable|titulo perfecto", regex=True).astype(int)
    df_clean["tiene_arboleda"] = texto_full.str.contains(r"arboleda|arboles|pinos|sombra|monte", regex=True).astype(int)
    df_clean["tiene_rio"] = texto_full.str.contains(r"\brio\b|arroyo|costa|balneario", regex=True).astype(int)
    df_clean["score_servicios"] = df_clean["tiene_agua"] + df_clean["tiene_luz"] + df_clean["tiene_escritura"]
    df_clean["tiene_servicios"] = (df_clean["score_servicios"] >= 2).astype(int)

    # 6. JOIN Espacial Haversine (Topografía + Campings + NPS Proxy Google Maps)
    topo_lats = df_topo["latitud_centroide"].to_numpy(dtype=float)
    topo_lons = df_topo["longitud_centroide"].to_numpy(dtype=float)
    topo_norms = [norm_txt(x) for x in df_topo["barrio_localidad"]]

    camp_coords = df_campings.dropna(subset=["latitud", "longitud"])
    camp_lats = pd.to_numeric(camp_coords["latitud"], errors="coerce").to_numpy(dtype=float)
    camp_lons = pd.to_numeric(camp_coords["longitud"], errors="coerce").to_numpy(dtype=float)

    places_valid = df_places.dropna(subset=["latitud", "longitud", "nps_proxy"]).copy()
    places_valid["reviews_w"] = pd.to_numeric(places_valid["reviews_count"], errors="coerce").fillna(1.0).clip(lower=1.0)
    pl_lats = places_valid["latitud"].to_numpy(dtype=float)
    pl_lons = places_valid["longitud"].to_numpy(dtype=float)
    pl_nps = places_valid["nps_proxy"].to_numpy(dtype=float)
    pl_w = places_valid["reviews_w"].to_numpy(dtype=float)
    nps_valle_mean = places_valid.groupby("valle_corredor")["nps_proxy"].mean().to_dict()

    barrios, pendientes, ndvis, dist_rios, riesgos = [], [], [], [], []
    camp_5km_l, camp_min_l, nps_zona_l, lat_eff_l, lon_eff_l = [], [], [], [], []

    for _, row in df_clean.iterrows():
        lat = pd.to_numeric(row["latitud"], errors="coerce")
        lon = pd.to_numeric(row["longitud"], errors="coerce")
        valle = str(row["valle_corredor"])

        if pd.notna(lat) and pd.notna(lon):
            dists_t = haversine_vec(float(lat), float(lon), topo_lats, topo_lons)
            idx_t = int(np.argmin(dists_t))
        else:
            loc_n = norm_txt(row.get("localidad_raw", ""))
            idx_t = int(np.argmax([SequenceMatcher(None, loc_n, tn).ratio() for tn in topo_norms]))
            lat = float(topo_lats[idx_t])
            lon = float(topo_lons[idx_t])

        t_row = df_topo.iloc[idx_t]
        barrios.append(str(t_row["barrio_localidad"]))
        pendientes.append(float(t_row["pendiente_media_grados"]))
        ndvis.append(float(t_row["ndvi_sombra_verano"]))
        dist_rios.append(float(t_row["distancia_rio_m"]))
        riesgos.append(str(t_row["riesgo_ambiental"]))
        lat_eff_l.append(round(float(lat), 6))
        lon_eff_l.append(round(float(lon), 6))

        dists_c = haversine_vec(float(lat), float(lon), camp_lats, camp_lons)
        camp_5km_l.append(int(np.sum(dists_c <= 5.0)))
        camp_min_l.append(round(float(np.min(dists_c)), 2))

        dists_p = haversine_vec(float(lat), float(lon), pl_lats, pl_lons)
        mask_5 = dists_p <= 5.0
        if np.any(mask_5):
            nps_z = float(np.average(pl_nps[mask_5], weights=pl_w[mask_5]))
        else:
            mask_15 = dists_p <= 15.0
            if np.any(mask_15):
                nps_z = float(np.average(pl_nps[mask_15], weights=pl_w[mask_15]))
            else:
                nps_z = float(nps_valle_mean.get(valle, np.mean(pl_nps)))
        nps_zona_l.append(round(nps_z, 2))

    df_clean["barrio_localidad"] = barrios
    df_clean["pendiente_media_grados"] = pendientes
    df_clean["ndvi_sombra_verano"] = ndvis
    df_clean["distancia_rio_m"] = dist_rios
    df_clean["riesgo_ambiental"] = riesgos
    df_clean["campings_5km"] = camp_5km_l
    df_clean["distancia_camping_min_km"] = camp_min_l
    df_clean["nps_proxy_zona"] = nps_zona_l
    df_clean["lat_eff"] = lat_eff_l
    df_clean["lon_eff"] = lon_eff_l

    # 7. Línea base de oportunidad Producto 1 (mediana por localidad, sin ML)
    med_zona = df_clean.groupby("barrio_localidad")["precio_m2_usd"].transform("median")
    df_clean["precio_referencia_zona_m2"] = med_zona.round(2)
    df_clean["descuento_vs_mediana_pct"] = (
        (df_clean["precio_referencia_zona_m2"] - df_clean["precio_m2_usd"])
        / df_clean["precio_referencia_zona_m2"]
        * 100.0
    ).round(2)
    cond_riesgo = (df_clean["riesgo_ambiental"] != "ALTO") if excluir_riesgo_alto else True
    df_clean["es_oportunidad_p1"] = (
        (df_clean["descuento_vs_mediana_pct"] >= umbral_desc_pct)
        & (df_clean["pendiente_media_grados"] <= pend_alerta)
        & cond_riesgo
    )

    df_out = df_clean.rename(columns={"id_publicacion": "id_registro"}).copy()
    cols_final = [
        "id_registro", "valle_corredor", "barrio_localidad", "precio_usd", "superficie_m2",
        "precio_m2_usd", "score_servicios", "tiene_agua", "tiene_luz", "tiene_escritura",
        "tiene_arboleda", "tiene_rio", "tiene_servicios", "pendiente_media_grados",
        "ndvi_sombra_verano", "distancia_rio_m", "riesgo_ambiental", "campings_5km",
        "distancia_camping_min_km", "nps_proxy_zona", "precio_referencia_zona_m2",
        "descuento_vs_mediana_pct", "es_oportunidad_p1", "titulo_publicacion", "lat_eff",
        "lon_eff", "telefono_en_descripcion", "vendedor_nombre", "url_publicacion", "url_google_maps",
    ]
    for col in cols_final:
        if col not in df_out.columns:
            df_out[col] = ""
    df_out = df_out[cols_final].reset_index(drop=True)

    total_crudo = max(int(len(df_ml)), 1)
    for item in funnel:
        item["retencion_pct"] = round(item["registros"] / total_crudo * 100.0, 1)

    return df_out, funnel