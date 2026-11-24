"""Entrypoint Apify para TerraScout Actor 3 (`APIFY ML`, solo inferencia, Regla R4)."""

from __future__ import annotations

try:
    from my_actor.sdk_compat import HAS_APIFY, Actor, resolve_ml_sdk_inputs
    from my_actor.tooling_business import execute_ml_actor
except ImportError:
    from .sdk_compat import HAS_APIFY, Actor, resolve_ml_sdk_inputs
    from .tooling_business import execute_ml_actor


async def main() -> None:
    """Lee `dataset_limpio` vía SDK Apify, ejecuta inferencia Producto 2 y publica resultados."""
    async with Actor:
        inp = await Actor.get_input() or {}
        Actor.log.info("Iniciando TerraScout APIFY ML — Inferencia (Producto 2)...")
        await Actor.set_status_message("APIFY ML: cargando dataset limpio, modelo .pkl y reglas...")

        sdk_texts, sdk_records, sdk_pkl_bytes = await resolve_ml_sdk_inputs(Actor, inp)
        outputs = execute_ml_actor(
            inp=inp,
            sdk_texts=sdk_texts,
            sdk_records=sdk_records,
            sdk_pkl_bytes=sdk_pkl_bytes,
        )

        await Actor.set_value(
            "predicciones_producto2.csv",
            outputs["predicciones_csv_bytes"],
            content_type="text/csv; charset=utf-8",
        )
        await Actor.set_value(
            "oportunidades_producto2.csv",
            outputs["oportunidades_csv_bytes"],
            content_type="text/csv; charset=utf-8",
        )

        metricas_payload = outputs["metricas_payload"]
        if HAS_APIFY:
            try:
                store = await Actor.open_key_value_store()
                metricas_payload["public_urls"] = {
                    "predicciones_producto2": await store.get_public_url("predicciones_producto2.csv"),
                    "oportunidades_producto2": await store.get_public_url("oportunidades_producto2.csv"),
                }
            except Exception as exc:  # pragma: no cover - depende de runtime Apify
                Actor.log.warning(f"No se pudieron obtener public_urls del KV Store: {exc}")

        await Actor.set_value("metricas_producto2.json", metricas_payload)

        if outputs["dataset_rows"]:
            await Actor.push_data(outputs["dataset_rows"])

        resumen = outputs["summary"]
        Actor.log.info(f"APIFY ML (inferencia) completado: {resumen}")
        await Actor.set_status_message(
            f"APIFY ML completado: {resumen.get('oportunidades_ml', 0)} oportunidades detectadas."
        )