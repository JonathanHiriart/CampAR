"""Lógica de negocio e inferencia hedónica para TerraScout AI (Actor 3 — Solo Inferencia).

Carga el modelo serializado `terrascout_pipeline.pkl` junto a `config/business_rules.json`,
predice el valor justo en `USD/m²`, calcula el gap de arbitraje y genera alertas sin PII.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from typing import Any

import numpy as np
import pandas as pd
import sklearn

try:
    from my_actor.preprocessing import (
        _normalize_id_column,
        enrich_ml_features,
        load_business_rules,
        load_clean_dataset,
        read_bytes_source,
    )
except ImportError:
    from .preprocessing import (
        _normalize_id_column,
        enrich_ml_features,
        load_business_rules,
        load_clean_dataset,
        read_bytes_source,
    )

_PII_COLUMNS = ("telefono_en_descripcion", "vendedor_nombre", "url_vendedor")


def sha256_bytes(payload: bytes) -> str:
    """Calcula el hash SHA-256 hexadecimal de un artefacto binario o CSV."""
    return hashlib.sha256(payload).hexdigest()


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


def score_opportunities(
    df_clean: pd.DataFrame,
    bundle: dict[str, Any],
    rules: dict[str, Any],
    pred_m2_override: pd.Series | None = None,
    split_override: pd.Series | None = None,
    ids_ya_alertados: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplica el modelo hedónico pre-entrenado y las reglas de arbitraje sobre lotes limpios."""
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

    drop_internal = [
        c
        for c in df.columns
        if c.startswith("dist_loc_")
        or c in ("texto_full", "descripcion_completa", "localidad_raw", "latitud", "longitud")
    ]
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
    lines = [
        f"TerraScout AI — Producto 2: {len(df_oportunidades)} oportunidad(es) ML. Top {min(top_n, len(df_oportunidades))}:"
    ]
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


def execute_ml_actor(
    inp: dict[str, Any],
    sdk_texts: dict[str, str] | None = None,
    sdk_records: list[dict[str, Any]] | None = None,
    sdk_pkl_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Ejecuta únicamente inferencia de Producto 2 usando el `.pkl` pre-entrenado y exporta salidas."""
    rules = load_business_rules(str(inp.get("rules_json_url") or ""), sdk_texts=sdk_texts)
    df_clean = load_clean_dataset(
        str(inp.get("dataset_limpio_url") or ""),
        sdk_texts=sdk_texts,
        sdk_records=sdk_records,
    )
    ids_alertados = {str(x) for x in (inp.get("ids_ya_alertados") or [])}

    model_url = str(inp.get("model_pkl_url") or "").strip()
    bundle = load_model_bundle(model_url, sdk_pkl_bytes=sdk_pkl_bytes)
    df_scored, df_oportunidades = score_opportunities(
        df_clean, bundle, rules, ids_ya_alertados=ids_alertados
    )

    comparison = bundle.get("model_comparison", [])
    winner_metrics = bundle.get("metrics_winner", {})
    feature_importances = bundle.get("feature_importances", [])
    dif_max = float(bundle.get("serialization_dif_max", 0.0))

    pred_bytes = df_scored.to_csv(index=False).encode("utf-8")
    oport_bytes = df_oportunidades.to_csv(index=False).encode("utf-8")
    dataset_rows = json.loads(df_oportunidades.to_json(orient="records"))

    summary = {
        "modo": "inferencia",
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
        },
    }

    return {
        "bundle": bundle,
        "df_scored": df_scored,
        "df_oportunidades": df_oportunidades,
        "predicciones_csv_bytes": pred_bytes,
        "oportunidades_csv_bytes": oport_bytes,
        "dataset_rows": dataset_rows,
        "summary": summary,
        "metricas_payload": metricas_payload,
    }