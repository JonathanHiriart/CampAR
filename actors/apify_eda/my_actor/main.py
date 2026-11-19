"""Entrypoint Apify para TerraScout Actor 2 (`APIFY EDA`, Regla R4)."""

from __future__ import annotations

try:
    from my_actor.eda_core import execute_eda_actor
    from my_actor.sdk_compat import HAS_APIFY, Actor, resolve_eda_sdk_inputs
except ImportError:
    from .eda_core import execute_eda_actor
    from .sdk_compat import HAS_APIFY, Actor, resolve_eda_sdk_inputs


async def main() -> None:
    """Lee `dataset_limpio` vía SDK Apify, ejecuta EDA y exporta 3 CSVs + XLSX + Dataset."""
    async with Actor:
        inp = await Actor.get_input() or {}
        Actor.log.info("Iniciando TerraScout APIFY EDA...")
        await Actor.set_status_message("APIFY EDA: cargando insumos por SDK Apify...")

        sdk_texts, sdk_records, sdk_wb_bytes = await resolve_eda_sdk_inputs(Actor, inp)
        outputs = execute_eda_actor(
            inp=inp,
            sdk_texts=sdk_texts,
            sdk_records=sdk_records,
            sdk_workbook_bytes=sdk_wb_bytes,
        )

        await Actor.set_value("csv_1_localidades_y_riesgo.csv", outputs["csv1_bytes"], content_type="text/csv; charset=utf-8")
        await Actor.set_value("csv_2_correlaciones_y_distribuciones.csv", outputs["csv2_bytes"], content_type="text/csv; charset=utf-8")
        await Actor.set_value("csv_3_oportunidades_y_voz_turista.csv", outputs["csv3_bytes"], content_type="text/csv; charset=utf-8")
        await Actor.set_value("dashboard_consolidado.csv", outputs["unico_bytes"], content_type="text/csv; charset=utf-8")
        await Actor.set_value(
            "contenido_graficas_dashboard.xlsx",
            outputs["xlsx_bytes"],
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        summary_payload = outputs["summary_payload"]
        if HAS_APIFY:
            try:
                store = await Actor.open_key_value_store()
                summary_payload["public_urls"] = {
                    "csv_1": await store.get_public_url("csv_1_localidades_y_riesgo.csv"),
                    "csv_2": await store.get_public_url("csv_2_correlaciones_y_distribuciones.csv"),
                    "csv_3": await store.get_public_url("csv_3_oportunidades_y_voz_turista.csv"),
                    "dashboard_consolidado": await store.get_public_url("dashboard_consolidado.csv"),
                    "xlsx": await store.get_public_url("contenido_graficas_dashboard.xlsx"),
                }
            except Exception as exc:  # pragma: no cover - depende de runtime Apify
                Actor.log.warning(f"No se pudieron obtener public_urls del KV Store: {exc}")

        await Actor.set_value("eda_summary.json", summary_payload)

        if outputs["dataset_rows"]:
            await Actor.push_data(outputs["dataset_rows"])

        Actor.log.info(f"APIFY EDA completado: {outputs['summary']}")
        await Actor.set_status_message(
            f"APIFY EDA completado: {outputs['summary'].get('filas_consolidado', 0)} filas publicadas."
        )