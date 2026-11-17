"""Núcleo EDA puro para TerraScout AI (Actor 2: APIFY EDA).

Consume `dataset_limpio.csv` (+ reviews y tópicos NLP opcionales) y genera
las salidas listas para Dashboard (`Looker Studio` / `Google Sheets`):
- `csv_1_localidades_y_riesgo.csv` (`hoja1`)
- `csv_2_correlaciones_y_distribuciones.csv` (`hoja2`)
- `csv_3_oportunidades_y_voz_turista.csv` (`hoja3`)
- `contenido_graficas_dashboard.xlsx` (Excel consolidado con `hoja1`, `hoja2`, `hoja3`)
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from scipy.stats import kendalltau
from sklearn.feature_selection import mutual_info_regression


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

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None and new_req.host != req.host:
            new_req.remove_header("Authorization")
        return new_req


def _http_get_bytes(url: str, timeout: int = 60, user_agent: str = "TerraScout-EDA-Actor/1.0") -> bytes:
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


def read_optional_source(url_or_path: str, *local_fallbacks: str, timeout: int = 60) -> str | None:
    """Lee texto desde HTTP/Drive o disco local; retorna None si no existe fuente."""
    src = str(url_or_path or "").strip()
    if src.startswith(("http://", "https://")):
        direct_url = normalize_drive_url(src, output_format="csv")
        return _http_get_bytes(direct_url, timeout=timeout).decode("utf-8", errors="replace")

    resolved = resolve_repo_path(src, *local_fallbacks)
    if resolved is not None:
        return resolved.read_text(encoding="utf-8")
    return None


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


def load_workbook_sheets(url_or_path: str, timeout: int = 90) -> dict[str, pd.DataFrame]:
    """Carga pestañas desde un Google Sheet / Excel (.xlsx) consolidado."""
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


def _topicos_from_dataframe(df_top: pd.DataFrame) -> dict[str, Any]:
    """Reconstruye `topics_quejas_gmaps` y `fuzzy_counts` desde la pestaña `topicos_nlp`."""
    quejas: list[dict[str, Any]] = []
    fuzzy: dict[str, dict[str, Any]] = {}
    for _, row in df_top.iterrows():
        sec = str(row.get("seccion", "")).strip()
        key = str(row.get("rank_o_clave", "")).strip()
        terms_raw = row.get("terms_json")
        if sec == "topic_queja":
            terms = json.loads(str(terms_raw)) if pd.notna(terms_raw) else []
            quejas.append({
                "rank": int(float(key)) if key else len(quejas) + 1,
                "size": int(float(row.get("size") or 0)),
                "share": float(row.get("share") or 0.0),
                "terms": terms,
            })
        elif sec == "fuzzy_count" and key:
            fuzzy[key] = json.loads(str(terms_raw)) if pd.notna(terms_raw) else {"count": int(float(row.get("size") or 0))}
    return {"topics_quejas_gmaps": {"items": quejas}, "fuzzy_counts": fuzzy}


def _col_letter(col_idx: int) -> str:
    """Convierte índice 1-based a letra de columna Excel (1->A, 27->AA)."""
    res = ""
    n = col_idx
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res


def _df_to_sheet_xml(df: pd.DataFrame) -> str:
    """Serializa un DataFrame a XML de hoja OpenXML válido."""
    rows_xml: list[str] = []
    headers = [str(c) for c in df.columns]
    all_rows = [headers] + df.values.tolist()

    for r_idx, row_vals in enumerate(all_rows, start=1):
        cells: list[str] = []
        for c_idx, val in enumerate(row_vals, start=1):
            ref = f"{_col_letter(c_idx)}{r_idx}"
            if val is None or (isinstance(val, float) and math.isnan(val)):
                continue
            if r_idx > 1 and isinstance(val, (int, float, np.integer, np.floating)) and not isinstance(val, bool):
                num = float(val)
                if math.isfinite(num):
                    cells.append(f'<c r="{ref}"><v>{num}</v></c>')
                    continue
            txt = escape(str(val))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{txt}</t></is></c>')
        rows_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows_xml)}</sheetData>'
        '</worksheet>'
    )


def build_multisheet_xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Genera un archivo .xlsx multi-hoja usando openpyxl o fallback OpenXML puro."""
    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        return buf.getvalue()
    except ImportError:
        pass

    buf = io.BytesIO()
    sheet_names = list(sheets.keys())
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheet_names) + 1)
        )
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f"{overrides}"
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        sheet_tags = "".join(
            f'<sheet name="{escape(name[:31])}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(sheet_names, start=1)
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheet_tags}</sheets>"
            "</workbook>",
        )
        wb_rels = "".join(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheet_names) + 1)
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{wb_rels}"
            "</Relationships>",
        )
        for i, name in enumerate(sheet_names, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _df_to_sheet_xml(sheets[name]))
    return buf.getvalue()


def _load_clean_dataframe(dataset_limpio_source: str) -> pd.DataFrame:
    raw_text = read_optional_source(
        dataset_limpio_source,
        "data/processed/dataset_limpio.csv",
        "data/processed/terrascout_dataset_producto1.csv",
        "outputs_campar/terrascout_dataset_producto1.csv",
    )
    if raw_text is None:
        raise FileNotFoundError(
            "No se encontró dataset_limpio.csv. Ejecutá primero APIFY ETL o pasá `dataset_limpio_url`."
        )
    stripped = raw_text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        parsed = json.loads(raw_text)
        rows = parsed if isinstance(parsed, list) else parsed.get("items", [parsed])
        return pd.DataFrame(rows)
    return pd.read_csv(io.StringIO(raw_text))


def run_eda_pipeline(
    dataset_limpio_source: str = "",
    reviews_csv_source: str = "",
    topicos_json_source: str = "",
    topo_csv_source: str = "",
    top_oportunidades_limit: int = 250,
    raw_workbook_source: str = "",
) -> dict[str, Any]:
    """Ejecuta el EDA y construye `csv_1`, `csv_2`, `csv_3` y el `.xlsx` multi-hoja."""
    wb_sheets = load_workbook_sheets(raw_workbook_source) if raw_workbook_source else {}
    df = _load_clean_dataframe(dataset_limpio_source)
    for col in [
        "precio_usd", "superficie_m2", "precio_m2_usd", "score_servicios",
        "tiene_escritura", "tiene_arboleda", "pendiente_media_grados",
        "ndvi_sombra_verano", "distancia_rio_m", "campings_5km",
        "distancia_camping_min_km", "nps_proxy_zona",
        "precio_referencia_zona_m2", "descuento_vs_mediana_pct", "lat_eff", "lon_eff",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "es_oportunidad_p1" in df.columns:
        df["es_oportunidad_p1"] = df["es_oportunidad_p1"].astype(str).str.lower().isin(["true", "1", "yes"])
    else:
        df["es_oportunidad_p1"] = False

    topo_centroids: dict[str, tuple[float, float]] = {}
    if not topo_csv_source and "topografia" in wb_sheets:
        df_topo = wb_sheets["topografia"]
    else:
        topo_text = read_optional_source(topo_csv_source, "data/aux_topografia_cordoba.csv")
        df_topo = pd.read_csv(io.StringIO(topo_text)) if topo_text else None
    if df_topo is not None:
        for _, tr in df_topo.iterrows():
            topo_centroids[str(tr["barrio_localidad"])] = (
                float(tr["latitud_centroide"]),
                float(tr["longitud_centroide"]),
            )

    # ------------------------------------------------------------------
    # CSV 1 / hoja1: Mapa de Localidades, Riesgo Ambiental y Demanda
    # ------------------------------------------------------------------
    grp_cols = ["valle_corredor", "barrio_localidad", "riesgo_ambiental"]
    df_csv1 = (
        df.groupby(grp_cols, as_index=False)
        .agg(
            cantidad_lotes=("id_registro", "count"),
            superficie_mediana_m2=("superficie_m2", "median"),
            precio_mediano_usd=("precio_usd", "median"),
            precio_m2_mediano_usd=("precio_m2_usd", "median"),
            precio_m2_promedio_usd=("precio_m2_usd", "mean"),
            score_servicios_promedio=("score_servicios", "mean"),
            pct_con_escritura=("tiene_escritura", "mean"),
            pendiente_media_grados=("pendiente_media_grados", "median"),
            ndvi_sombra_verano=("ndvi_sombra_verano", "median"),
            distancia_rio_m=("distancia_rio_m", "median"),
            campings_5km_mediana=("campings_5km", "median"),
            nps_proxy_zona_mediana=("nps_proxy_zona", "median"),
            oportunidades_p1_count=("es_oportunidad_p1", "sum"),
            lat_lote_med=("lat_eff", "median"),
            lon_lote_med=("lon_eff", "median"),
        )
        .sort_values(["precio_m2_mediano_usd", "cantidad_lotes"], ascending=[False, False])
        .reset_index(drop=True)
    )
    df_csv1["pct_con_escritura"] = (df_csv1["pct_con_escritura"] * 100.0).round(1)
    for c in [
        "superficie_mediana_m2", "precio_mediano_usd", "precio_m2_mediano_usd",
        "precio_m2_promedio_usd", "score_servicios_promedio", "pendiente_media_grados",
        "ndvi_sombra_verano", "distancia_rio_m", "campings_5km_mediana", "nps_proxy_zona_mediana",
    ]:
        df_csv1[c] = df_csv1[c].round(2)

    lats_c, lons_c, coords_str = [], [], []
    for _, row in df_csv1.iterrows():
        loc = str(row["barrio_localidad"])
        if loc in topo_centroids:
            la, lo = topo_centroids[loc]
        else:
            la = float(row["lat_lote_med"]) if pd.notna(row["lat_lote_med"]) else -31.8
            lo = float(row["lon_lote_med"]) if pd.notna(row["lon_lote_med"]) else -64.5
        lats_c.append(round(la, 6))
        lons_c.append(round(lo, 6))
        coords_str.append(f"{la:.6f},{lo:.6f}")

    df_csv1["latitud_centroide"] = lats_c
    df_csv1["longitud_centroide"] = lons_c
    df_csv1["coordenadas_gmaps"] = coords_str
    df_csv1 = df_csv1.drop(columns=["lat_lote_med", "lon_lote_med"])

    # ------------------------------------------------------------------
    # CSV 2 / hoja2: Correlaciones Reales + Distribuciones + Cruce Riesgo
    # ------------------------------------------------------------------
    corr_rows: list[dict[str, Any]] = []
    num_cols = [
        "superficie_m2", "score_servicios", "tiene_escritura", "tiene_arboleda",
        "pendiente_media_grados", "ndvi_sombra_verano", "distancia_rio_m",
        "campings_5km", "distancia_camping_min_km", "nps_proxy_zona",
    ]
    avail_num = [c for c in num_cols if c in df.columns]
    df_num = df[avail_num + ["precio_m2_usd", "precio_usd"]].dropna()

    if len(df_num) >= 5:
        X_mi = df_num[avail_num]
        y_m2 = df_num["precio_m2_usd"]
        y_tot = df_num["precio_usd"]
        mi_vals = mutual_info_regression(X_mi, y_m2, random_state=42)
        for col, mi_v in zip(avail_num, mi_vals):
            ken_stat = float(kendalltau(X_mi[col], y_m2).statistic)
            corr_rows.append({
                "bloque": "correlacion_features",
                "variable_o_grupo": col,
                "subgrupo": "vs precio_m2_usd",
                "pearson_m2": round(float(X_mi[col].corr(y_m2, method="pearson")), 4),
                "spearman_m2": round(float(X_mi[col].corr(y_m2, method="spearman")), 4),
                "kendall_m2": round(0.0 if math.isnan(ken_stat) else ken_stat, 4),
                "info_mutua_m2": round(float(mi_v), 4),
                "pearson_total_usd": round(float(X_mi[col].corr(y_tot, method="pearson")), 4),
                "n": int(len(df_num)),
                "media": None, "mediana": None, "std": None, "skew": None,
            })

    dist_targets = avail_num + ["precio_usd", "precio_m2_usd"]
    for col in dist_targets:
        s = df[col].dropna()
        if len(s) == 0:
            continue
        corr_rows.append({
            "bloque": "distribucion_asimetria",
            "variable_o_grupo": col,
            "subgrupo": "univariado",
            "pearson_m2": None, "spearman_m2": None, "kendall_m2": None,
            "info_mutua_m2": None, "pearson_total_usd": None,
            "n": int(len(s)),
            "media": round(float(s.mean()), 2),
            "mediana": round(float(s.median()), 2),
            "std": round(float(s.std()), 2),
            "skew": round(float(s.skew()), 3),
        })

    if (df["precio_m2_usd"] > 0).all():
        log_pm2 = np.log(df["precio_m2_usd"])
        corr_rows.append({
            "bloque": "distribucion_asimetria",
            "variable_o_grupo": "log_precio_m2_usd",
            "subgrupo": "transformacion_log",
            "pearson_m2": None, "spearman_m2": None, "kendall_m2": None,
            "info_mutua_m2": None, "pearson_total_usd": None,
            "n": int(len(log_pm2)),
            "media": round(float(log_pm2.mean()), 3),
            "mediana": round(float(log_pm2.median()), 3),
            "std": round(float(log_pm2.std()), 3),
            "skew": round(float(pd.Series(log_pm2).skew()), 3),
        })

    cruce_vr = (
        df.groupby(["valle_corredor", "riesgo_ambiental"], as_index=False)["precio_m2_usd"]
        .agg(n="count", mediana="median", media="mean", std="std")
    )
    for _, cr in cruce_vr.iterrows():
        corr_rows.append({
            "bloque": "cruce_valle_riesgo",
            "variable_o_grupo": str(cr["valle_corredor"]),
            "subgrupo": f"riesgo_{cr['riesgo_ambiental']}",
            "pearson_m2": None, "spearman_m2": None, "kendall_m2": None,
            "info_mutua_m2": None, "pearson_total_usd": None,
            "n": int(cr["n"]),
            "media": round(float(cr["media"]), 2),
            "mediana": round(float(cr["mediana"]), 2),
            "std": round(float(cr["std"]) if pd.notna(cr["std"]) else 0.0, 2),
            "skew": None,
        })

    df_csv2 = pd.DataFrame(corr_rows)

    # ------------------------------------------------------------------
    # CSV 3 / hoja3: Oportunidades Producto 1 + Voz del Turista y Quejas
    # ------------------------------------------------------------------
    opp_rows: list[dict[str, Any]] = []
    df_sorted_lotes = df.sort_values(["es_oportunidad_p1", "descuento_vs_mediana_pct"], ascending=[False, False])
    if top_oportunidades_limit and top_oportunidades_limit > 0:
        df_sorted_lotes = df_sorted_lotes.head(int(top_oportunidades_limit))

    for _, lr in df_sorted_lotes.iterrows():
        opp_rows.append({
            "seccion": "oportunidad_lote",
            "id_registro": lr.get("id_registro", ""),
            "valle_corredor": lr.get("valle_corredor", ""),
            "barrio_localidad": lr.get("barrio_localidad", ""),
            "titulo_publicacion": lr.get("titulo_publicacion", ""),
            "precio_usd": lr.get("precio_usd"),
            "superficie_m2": lr.get("superficie_m2"),
            "precio_m2_usd": lr.get("precio_m2_usd"),
            "precio_referencia_zona_m2": lr.get("precio_referencia_zona_m2"),
            "descuento_vs_mediana_pct": lr.get("descuento_vs_mediana_pct"),
            "es_oportunidad_p1": bool(lr.get("es_oportunidad_p1", False)),
            "pendiente_media_grados": lr.get("pendiente_media_grados"),
            "riesgo_ambiental": lr.get("riesgo_ambiental", ""),
            "score_servicios": lr.get("score_servicios"),
            "telefono_en_descripcion": lr.get("telefono_en_descripcion", "") if pd.notna(lr.get("telefono_en_descripcion")) else "",
            "url_publicacion": lr.get("url_publicacion", ""),
            "url_google_maps": lr.get("url_google_maps", ""),
            "metrica_turismo_o_topico": "",
            "cantidad_o_menciones": None,
            "porcentaje_o_share": None,
        })

    if not reviews_csv_source and "reviews" in wb_sheets:
        df_rev = wb_sheets["reviews"]
    else:
        reviews_text = read_optional_source(
            reviews_csv_source,
            "data/raw/google_maps_campings_reviews_raw.csv",
        )
        df_rev = pd.read_csv(io.StringIO(reviews_text)) if reviews_text else None

    if df_rev is not None:
        total_rev = max(int(len(df_rev)), 1)
        star_counts = df_rev["estrellas_rating"].value_counts().sort_index()
        for star, cnt in star_counts.items():
            opp_rows.append({
                "seccion": "voz_turista_estrellas",
                "id_registro": f"STAR-{star}",
                "valle_corredor": "Todos",
                "barrio_localidad": "Sierras de Córdoba",
                "titulo_publicacion": f"Reseñas Google Maps {star} estrellas",
                "precio_usd": None, "superficie_m2": None, "precio_m2_usd": None,
                "precio_referencia_zona_m2": None, "descuento_vs_mediana_pct": None,
                "es_oportunidad_p1": False, "pendiente_media_grados": None,
                "riesgo_ambiental": "", "score_servicios": None,
                "telefono_en_descripcion": "", "url_publicacion": "", "url_google_maps": "",
                "metrica_turismo_o_topico": f"{star}_estrellas",
                "cantidad_o_menciones": int(cnt),
                "porcentaje_o_share": round(int(cnt) / total_rev * 100.0, 2),
            })

    if not topicos_json_source and "topicos_nlp" in wb_sheets:
        top_data = _topicos_from_dataframe(wb_sheets["topicos_nlp"])
    else:
        topicos_text = read_optional_source(
            topicos_json_source,
            "data/raw/topicos_nlp_real_raw.json",
        )
        top_data = json.loads(topicos_text) if topicos_text else None

    if top_data:
        quejas = (top_data.get("topics_quejas_gmaps") or {}).get("items", [])
        for q in quejas:
            opp_rows.append({
                "seccion": "topico_queja_gmaps",
                "id_registro": f"QUEJA-{q.get('rank')}",
                "valle_corredor": "Todos",
                "barrio_localidad": "Sierras de Córdoba",
                "titulo_publicacion": ", ".join(q.get("terms", [])),
                "precio_usd": None, "superficie_m2": None, "precio_m2_usd": None,
                "precio_referencia_zona_m2": None, "descuento_vs_mediana_pct": None,
                "es_oportunidad_p1": False, "pendiente_media_grados": None,
                "riesgo_ambiental": "", "score_servicios": None,
                "telefono_en_descripcion": "", "url_publicacion": "", "url_google_maps": "",
                "metrica_turismo_o_topico": f"Cluster #{q.get('rank')}: {', '.join(q.get('terms', []))}",
                "cantidad_o_menciones": int(q.get("size", 0)),
                "porcentaje_o_share": round(float(q.get("share", 0.0)) * 100.0, 2),
            })
        for kw, stats in (top_data.get("fuzzy_counts") or {}).items():
            opp_rows.append({
                "seccion": "infraestructura_keyword",
                "id_registro": f"KW-{kw}",
                "valle_corredor": "Todos",
                "barrio_localidad": "Sierras de Córdoba",
                "titulo_publicacion": f"Mención difusa '{kw}'",
                "precio_usd": None, "superficie_m2": None, "precio_m2_usd": None,
                "precio_referencia_zona_m2": None, "descuento_vs_mediana_pct": None,
                "es_oportunidad_p1": False, "pendiente_media_grados": None,
                "riesgo_ambiental": "", "score_servicios": None,
                "telefono_en_descripcion": "", "url_publicacion": "", "url_google_maps": "",
                "metrica_turismo_o_topico": str(kw),
                "cantidad_o_menciones": int(stats.get("count", 0)),
                "porcentaje_o_share": None,
            })

    df_csv3 = pd.DataFrame(opp_rows)

    xlsx_bytes = build_multisheet_xlsx_bytes({
        "hoja1": df_csv1,
        "hoja2": df_csv2,
        "hoja3": df_csv3,
    })

    return {
        "csv_1_localidades_y_riesgo": df_csv1,
        "csv_2_correlaciones_y_distribuciones": df_csv2,
        "csv_3_oportunidades_y_voz_turista": df_csv3,
        "xlsx_bytes": xlsx_bytes,
        "summary": {
            "total_lotes_limpios": int(len(df)),
            "oportunidades_p1": int(df["es_oportunidad_p1"].sum()),
            "filas_csv1": int(len(df_csv1)),
            "filas_csv2": int(len(df_csv2)),
            "filas_csv3": int(len(df_csv3)),
        },
    }