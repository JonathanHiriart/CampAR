"""Entrypoint Apify para TerraScout Actor 1 (`APIFY ETL`, Regla R4)."""

from __future__ import annotations

try:
    from my_actor.etl_core import execute_etl_actor
    from my_actor.sdk_compat import HAS_APIFY, Actor, resolve_etl_sdk_inputs
except ImportError:
    from .etl_core import execute_etl_actor
    from .sdk_compat import HAS_APIFY, Actor, resolve_etl_sdk_inputs


async def main() -> None:
    """Lee insumos por SDK Apify, ejecuta ETL y publica `dataset_limpio.csv` + JSON."""
    async with Actor:
        inp = await Actor.get_input() or {}
        Actor.log.info("Iniciando TerraScout APIFY ETL...")
        await Actor.set_status_message("APIFY ETL: leyendo insumos por SDK Apify...")

        sdk_texts, sdk_wb_bytes = await resolve_etl_sdk_inputs(Actor, inp)
        outputs = execute_etl_actor(
            inp=inp,
            sdk_texts=sdk_texts,
            sdk_workbook_bytes=sdk_wb_bytes,
        )

        await Actor.set_value(
            "dataset_limpio.csv",
            outputs["csv_bytes"],
            content_type="text/csv; charset=utf-8",
        )

        funnel_payload = outputs["funnel_payload"]
        if HAS_APIFY:
            try:
                store = await Actor.open_key_value_store()
                funnel_payload["dataset_limpio_public_url"] = await store.get_public_url("dataset_limpio.csv")
            except Exception as exc:  # pragma: no cover - depende de runtime Apify
                Actor.log.warning(f"No se pudo obtener public_url del KV Store: {exc}")

        await Actor.set_value("etl_funnel.json", funnel_payload)

        if outputs["dataset_rows"]:
            await Actor.push_data(outputs["dataset_rows"])

        total_clean = outputs["total_clean"]
        Actor.log.info(f"ETL completado: {total_clean} registros limpios exportados a dataset_limpio.csv.")
        await Actor.set_status_message(f"APIFY ETL completado: {total_clean} registros limpios.")