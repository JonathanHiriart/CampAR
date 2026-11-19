"""Núcleo ETL puro para TerraScout AI (Actor 1: APIFY ETL).

Convierte los insumos crudos (Drive/HTTP o disco local) en `dataset_limpio.csv`
aplicando las reglas desacopladas de `config/business_rules.json`, limpieza
trazable sin imputación ciega ni datos sintéticos y JOIN espacial Haversine.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_PLACEHOLDER_PRICES = {101010101.0, 111111111.0, 99999999.0, 123456789.0}


def sha256_bytes(payload: bytes) -> str:
    """Calcula el hash SHA-256 hexadecimal de un artefacto o insumo (Regla R3)."""
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


def _http_get_bytes(url: str, timeout: int = 60, user_agent: str = "TerraScout-ETL-Actor/1.0") -> bytes:
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
            f"La URL '{url}' devolvió HTML en vez de datos. "
            "Si es Google Drive/Sheets, verificá que esté compartido como 'Cualquiera con el enlace (Lector)'."
        )
    return data


def read_text_source(url_or_path: str, *local_fallbacks: str, timeout: int = 60) -> str:
    """Descarga texto desde HTTP/Drive o lee desde disco local."""
    src = str(url_or_path or "").strip()
    if src.startswith(("http://", "https://")):
        direct_url = normalize_drive_url(src, output_format="csv")
        return _http_get_bytes(direct_url, timeout=timeout).decode("utf-8", errors="replace")

    resolved = resolve_repo_path(src, *local_fallbacks)
    if resolved is None:
        raise FileNotFoundError(
            f"No se encontró la fuente '{src}' ni fallbacks locales {local_fallbacks}."
        )
    return resolved.read_text(encoding="utf-8")


def _read_xlsx_sheets_stdlib(raw_bytes: bytes) -> dict[str, pd.DataFrame]:
    """Lector OpenXML puro (fallback si openpyxl no está instalado)."""
    ns_m = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ns_r = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    out: dict[str, pd.DataFrame] = {}

    def _col_idx(ref: str) -> int:
        letters = "".join(ch for ch in ref if ch.isalpha())
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch.upper()) - 64)
        return max(idx - 1, 0)

    with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("m:si", ns_m):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", ns_m)))

        rels_map: dict[str, str] = {}
        rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rels_root:
            rid = rel.attrib.get("Id", "")
            tgt = rel.attrib.get("Target", "").lstrip("/")
            rels_map[rid] = tgt if tgt.startswith("xl/") else f"xl/{tgt}"

        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        for sh in wb_root.findall(".//m:sheet", ns_m):
            name = sh.attrib["name"]
            rid = sh.attrib.get(ns_r, "")
            xml_path = rels_map.get(rid, "")
            if xml_path not in zf.namelist():
                continue
            ws_root = ET.fromstring(zf.read(xml_path))
            rows_parsed: list[list[Any]] = []
            max_cols = 0
            for r_el in ws_root.findall(".//m:sheetData/m:row", ns_m):
                row_vals: dict[int, Any] = {}
                for c_el in r_el.findall("m:c", ns_m):
                    c_i = _col_idx(c_el.attrib.get("r", "A1"))
                    ctype = c_el.attrib.get("t", "")
                    if ctype == "inlineStr":
                        val: Any = "".join(t.text or "" for t in c_el.findall(".//m:t", ns_m))
                    elif ctype == "s":
                        v_el = c_el.find("m:v", ns_m)
                        val = shared[int(v_el.text)] if (v_el is not None and v_el.text) else ""
                    elif ctype in ("str", "e"):
                        v_el = c_el.find("m:v", ns_m)
                        val = v_el.text if v_el is not None else ""
                    elif ctype == "b":
                        v_el = c_el.find("m:v", ns_m)
                        val = bool(int(v_el.text)) if (v_el is not None and v_el.text) else False
                    else:
                        v_el = c_el.find("m:v", ns_m)
                        if v_el is not None and v_el.text is not None:
                            try:
                                f = float(v_el.text)
                                val = int(f) if f.is_integer() and "." not in v_el.text else f
                            except ValueError:
                                val = v_el.text
                        else:
                            val = None
                    row_vals[c_i] = val
                    max_cols = max(max_cols, c_i + 1)
                if row_vals:
                    rows_parsed.append([row_vals.get(i) for i in range(max_cols)])
            if not rows_parsed:
                out[name] = pd.DataFrame()
                continue
            headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows_parsed[0])]
            body = [r + [None] * (len(headers) - len(r)) for r in rows_parsed[1:]]
            out[name] = pd.DataFrame(body, columns=headers)
    return out


def load_workbook_sheets(
    url_or_path: str,
    timeout: int = 90,
    raw_bytes_override: bytes | None = None,
) -> dict[str, pd.DataFrame]:
    """Carga todas las pestañas de un libro Google Sheets / Excel (.xlsx)."""
    if raw_bytes_override is not None:
        raw_bytes = raw_bytes_override
    else:
        src = str(url_or_path or "").strip()
        if not src:
            return {}
        if src.startswith(("http://", "https://")):
            direct_url = normalize_drive_url(src, output_format="xlsx")
            raw_bytes = _http_get_bytes(direct_url, timeout=timeout)
        else:
            resolved = resolve_repo_path(src)
            if resolved is None:
                raise FileNotFoundError(f"No se encontró el libro RAW '{src}'.")
            raw_bytes = resolved.read_bytes()
    try:
        return pd.read_excel(io.BytesIO(raw_bytes), sheet_name=None, engine="openpyxl")
    except ImportError:
        return _read_xlsx_sheets_stdlib(raw_bytes)


def _rules_from_dataframe(df_rules: pd.DataFrame) -> dict[str, Any]:
    """Reconstruye el diccionario `business_rules.json` desde una pestaña clave/valor."""
    rules: dict[str, Any] = {}
    for _, row in df_rules.iterrows():
        clave = str(row.get("clave", "")).strip()
        if not clave:
            continue
        val_raw = row.get("valor_json")
        if pd.isna(val_raw):
            continue
        if isinstance(val_raw, str):
            txt = val_raw.strip()
            try:
                rules[clave] = json.loads(txt)
            except json.JSONDecodeError:
                rules[clave] = txt
        else:
            rules[clave] = val_raw
    return rules


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


def detect_tiene_escritura(texto_norm: pd.Series) -> pd.Series:
    """Detecta tenencia real de escritura excluyendo disclaimers legales y negaciones."""
    clean = (
        texto_norm
        .str.replace(r"no\s+interviene[^.]{0,160}escritura", " ", regex=True)
        .str.replace(r"confeccion\s+y\s+o\s+firma\s+del\s+boleto\s+de\s+compraventa\s+y\s+o\s+escritura", " ", regex=True)
        .str.replace(r"gastos\s+de\s+escribania\s+por\s+escritura(?:\s+o\s+boleto\s+de\s+compra\s+venta)?", " ", regex=True)
        .str.replace(r"\b(?:sin|no\s+tiene|no\s+posee|no\s+cuenta\s+con|carece\s+de)\s+(?:de\s+)?escritur\w*", " ", regex=True)
        .str.replace(r"\b(?:escritura\s+en\s+tramite|proximamente\s+a\s+escriturar|boleto\s+para\s+escriturar|mediante\s+boleto\s+de\s+compra\s*venta)\b", " ", regex=True)
    )
    return clean.str.contains(
        r"\bescritura(?:do|da|dos|das)?\b|\bescriturable\b|\blist[oa]s?\s+para\s+escriturar\b|\btitulo\s+perfecto\b",
        regex=True,
    ).astype(int)


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
    raw_workbook_source: str = "",
    sdk_texts: dict[str, str] | None = None,
    sdk_workbook_bytes: bytes | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Ejecuta el ETL completo de Producto 1 y retorna `(df_limpio, funnel)`."""
    texts = sdk_texts or {}
    wb_sheets = (
        load_workbook_sheets(raw_workbook_source, raw_bytes_override=sdk_workbook_bytes)
        if (sdk_workbook_bytes is not None or raw_workbook_source)
        else {}
    )

    if "rules_json" in texts:
        rules_raw = texts["rules_json"]
        rules = json.loads(rules_raw)
    elif not rules_json_source and "business_rules" in wb_sheets:
        rules = _rules_from_dataframe(wb_sheets["business_rules"])
    else:
        rules_raw = read_text_source(rules_json_source, "config/business_rules.json")
        rules = json.loads(rules_raw)

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
    seg_cfg = rules.get("segmentacion_superficie") or {}
    cortes_sup = [float(x) for x in seg_cfg.get("cortes_m2", [1000.0, 3000.0, 10000.0])]
    etiq_sup = [str(x) for x in seg_cfg.get("etiquetas", ["<= 1.000 m2", "1.001 - 3.000 m2", "3.001 - 10.000 m2", "> 10.000 m2"])]
    orden_riesgo_map = {str(k): int(v) for k, v in (seg_cfg.get("orden_riesgo") or {"BAJO": 1, "MEDIO": 2, "ALTO": 3}).items()}
    min_muestra_seg = int(seg_cfg.get("minimo_muestra_segmento", 5))
    ocultar_pii = bool((rules.get("seguridad") or {}).get("ocultar_pii_en_salidas", True))

    def _sheet_or_csv(sheet_name: str, src: str, fallback: str, sdk_key: str) -> pd.DataFrame:
        if sdk_key in texts:
            return pd.read_csv(io.StringIO(texts[sdk_key]))
        if not src and sheet_name in wb_sheets:
            return wb_sheets[sheet_name].copy()
        return pd.read_csv(io.StringIO(read_text_source(src, fallback)))

    df_ml = _sheet_or_csv("ml_terrenos", ml_csv_source, "data/raw/mercadolibre_terrenos_calamuchita_punilla_raw.csv", "ml_csv_text")
    df_campings = _sheet_or_csv("campings", campings_csv_source, "data/raw/campings_zona_real_raw.csv", "campings_csv_text")
    df_places = _sheet_or_csv("places", places_csv_source, "data/raw/google_maps_campings_places_raw.csv", "places_csv_text")
    df_topo = _sheet_or_csv("topografia", topo_csv_source, "data/aux_topografia_cordoba.csv", "topo_csv_text")

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
    df_clean["tiene_escritura"] = detect_tiene_escritura(texto_full)
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

    valles, barrios, pendientes, ndvis, dist_rios, riesgos = [], [], [], [], [], []
    camp_5km_l, camp_min_l, nps_zona_l, lat_eff_l, lon_eff_l = [], [], [], [], []

    for _, row in df_clean.iterrows():
        lat = pd.to_numeric(row["latitud"], errors="coerce")
        lon = pd.to_numeric(row["longitud"], errors="coerce")

        if pd.notna(lat) and pd.notna(lon):
            dists_t = haversine_vec(float(lat), float(lon), topo_lats, topo_lons)
            idx_t = int(np.argmin(dists_t))
        else:
            loc_n = norm_txt(row.get("localidad_raw", ""))
            idx_t = int(np.argmax([SequenceMatcher(None, loc_n, tn).ratio() for tn in topo_norms]))
            lat = float(topo_lats[idx_t])
            lon = float(topo_lons[idx_t])

        t_row = df_topo.iloc[idx_t]
        valle = str(t_row["valle_corredor"]) if "valle_corredor" in t_row and pd.notna(t_row["valle_corredor"]) else str(row["valle_corredor"])
        valles.append(valle)
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

    df_clean["valle_corredor"] = valles
    df_clean["barrio_localidad"] = barrios
    df_clean["pendiente_media_grados"] = pendientes
    df_clean["ndvi_sombra_verano"] = ndvis
    df_clean["distancia_rio_m"] = dist_rios
    df_clean["riesgo_ambiental"] = riesgos
    df_clean["riesgo_orden"] = df_clean["riesgo_ambiental"].map(orden_riesgo_map).fillna(9).astype(int)
    df_clean["campings_5km"] = camp_5km_l
    df_clean["distancia_camping_min_km"] = camp_min_l
    df_clean["nps_proxy_zona"] = nps_zona_l
    df_clean["lat_eff"] = lat_eff_l
    df_clean["lon_eff"] = lon_eff_l
    df_clean["coordenadas_gmaps"] = [f"{la:.6f},{lo:.6f}" for la, lo in zip(lat_eff_l, lon_eff_l)]

    # 7. Segmentación por superficie y oportunidad (localidad + banda con fallback muestral)
    bin_idx = np.searchsorted(cortes_sup, df_clean["superficie_m2"].to_numpy(dtype=float), side="left")
    df_clean["banda_orden"] = (bin_idx + 1).astype(int)
    df_clean["banda_superficie"] = [etiq_sup[min(int(i), len(etiq_sup) - 1)] for i in bin_idx]

    med_zona = df_clean.groupby("barrio_localidad")["precio_m2_usd"].transform("median")
    df_clean["precio_referencia_zona_m2"] = med_zona.round(2)
    df_clean["descuento_vs_mediana_pct"] = (
        (df_clean["precio_referencia_zona_m2"] - df_clean["precio_m2_usd"])
        / df_clean["precio_referencia_zona_m2"]
        * 100.0
    ).round(2)

    grp_seg = df_clean.groupby(["barrio_localidad", "banda_superficie"])["precio_m2_usd"]
    df_clean["segmento_n"] = grp_seg.transform("count").astype(int)
    med_seg = grp_seg.transform("median")
    df_clean["precio_referencia_segmento_m2"] = np.where(
        df_clean["segmento_n"] >= min_muestra_seg, med_seg, med_zona
    ).round(2)
    df_clean["descuento_vs_segmento_pct"] = (
        (df_clean["precio_referencia_segmento_m2"] - df_clean["precio_m2_usd"])
        / df_clean["precio_referencia_segmento_m2"]
        * 100.0
    ).round(2)

    cond_riesgo = (df_clean["riesgo_ambiental"] != "ALTO") if excluir_riesgo_alto else True
    df_clean["es_oportunidad_p1"] = (
        (df_clean["descuento_vs_mediana_pct"] >= umbral_desc_pct)
        & (df_clean["pendiente_media_grados"] <= pend_alerta)
        & cond_riesgo
    )
    df_clean["es_oportunidad_segmento"] = (
        (df_clean["descuento_vs_segmento_pct"] >= umbral_desc_pct)
        & (df_clean["pendiente_media_grados"] <= pend_alerta)
        & cond_riesgo
    )

    df_out = df_clean.rename(columns={"id_publicacion": "id_registro"}).copy()
    cols_final = [
        "id_registro", "fecha_extraccion", "valle_corredor", "barrio_localidad",
        "precio_usd", "superficie_m2", "banda_superficie", "banda_orden", "precio_m2_usd",
        "score_servicios", "tiene_agua", "tiene_luz", "tiene_escritura",
        "tiene_arboleda", "tiene_rio", "tiene_servicios", "pendiente_media_grados",
        "ndvi_sombra_verano", "distancia_rio_m", "riesgo_ambiental", "riesgo_orden",
        "campings_5km", "distancia_camping_min_km", "nps_proxy_zona",
        "precio_referencia_zona_m2", "descuento_vs_mediana_pct", "es_oportunidad_p1",
        "segmento_n", "precio_referencia_segmento_m2", "descuento_vs_segmento_pct",
        "es_oportunidad_segmento", "titulo_publicacion", "lat_eff", "lon_eff", "coordenadas_gmaps",
    ]
    if not ocultar_pii:
        cols_final.extend(["telefono_en_descripcion", "vendedor_nombre"])
    cols_final.extend(["url_publicacion", "url_google_maps"])
    for col in cols_final:
        if col not in df_out.columns:
            df_out[col] = ""
    df_out = df_out[cols_final].reset_index(drop=True)

    total_crudo = max(int(len(df_ml)), 1)
    for item in funnel:
        item["retencion_pct"] = round(item["registros"] / total_crudo * 100.0, 1)

    return df_out, funnel


def execute_etl_actor(
    inp: dict[str, Any],
    sdk_texts: dict[str, str] | None = None,
    sdk_workbook_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Ejecuta ETL y serializa CSV/JSON listos para persistencia vía SDK en `main.py`."""
    df_clean, funnel = run_etl_pipeline(
        ml_csv_source=str(inp.get("ml_csv_url") or ""),
        campings_csv_source=str(inp.get("campings_csv_url") or ""),
        places_csv_source=str(inp.get("places_csv_url") or ""),
        topo_csv_source=str(inp.get("topo_csv_url") or ""),
        rules_json_source=str(inp.get("rules_json_url") or ""),
        tipo_cambio_override=float(inp.get("tipo_cambio_ars_usd_override") or 0.0),
        raw_workbook_source=str(inp.get("raw_workbook_url") or ""),
        sdk_texts=sdk_texts,
        sdk_workbook_bytes=sdk_workbook_bytes,
    )
    csv_bytes = df_clean.to_csv(index=False).encode("utf-8")
    dataset_rows = json.loads(df_clean.to_json(orient="records"))
    total_clean = int(len(df_clean))
    return {
        "df_clean": df_clean,
        "csv_bytes": csv_bytes,
        "dataset_rows": dataset_rows,
        "total_clean": total_clean,
        "funnel_payload": {
            "funnel": funnel,
            "total_clean": total_clean,
            "dataset_limpio_sha256": sha256_bytes(csv_bytes),
        },
    }