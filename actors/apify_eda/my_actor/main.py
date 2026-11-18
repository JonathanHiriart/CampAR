"""Entrypoint Apify para TerraScout Actor 2 (`APIFY EDA`)."""

from __future__ import annotations

import json
import logging
from typing import Any

from .eda_core import run_eda_pipeline

try:
    from apify import Actor
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

    class _MockLog:
        info = staticmethod(logging.getLogger("apify_eda").info)

    class _MockActor:
        log = _MockLog()

        async def get_input(self) -> dict[str, Any]:
            return {}

        async def push_data(self, data: Any) -> None:
            return None

        async def set_value(self, key: str, value: Any, content_type: str | None = None) -> None:
            return None

        async def __aenter__(self) -> _MockActor:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    Actor = _MockActor()


async def main() -> None:
    """Lee `dataset_limpio.csv`, ejecuta EDA y exporta 3 CSVs + XLSX multi-hoja."""
    async with Actor:
        inp = await Actor.get_input() or {}
        Actor.log.info("Iniciando TerraScout APIFY EDA...")

        res = run_eda_pipeline(
            dataset_limpio_source=str(inp.get("dataset_limpio_url") or ""),
            reviews_csv_source=str(inp.get("reviews_csv_url") or ""),
            topicos_json_source=str(inp.get("topicos_json_url") or ""),
            topo_csv_source=str(inp.get("topo_csv_url") or ""),
            top_oportunidades_limit=int(inp.get("top_oportunidades_limit") or 250),
            raw_workbook_source=str(inp.get("raw_workbook_url") or ""),
        )

        csv1_txt = res["csv_1_localidades_y_riesgo"].to_csv(index=False)
        csv2_txt = res["csv_2_correlaciones_y_distribuciones"].to_csv(index=False)
        csv3_txt = res["csv_3_oportunidades_y_voz_turista"].to_csv(index=False)
        unico_txt = res["dashboard_consolidado"].to_csv(index=False)

        await Actor.set_value("csv_1_localidades_y_riesgo.csv", csv1_txt.encode("utf-8"), content_type="text/csv; charset=utf-8")
        await Actor.set_value("csv_2_correlaciones_y_distribuciones.csv", csv2_txt.encode("utf-8"), content_type="text/csv; charset=utf-8")
        await Actor.set_value("csv_3_oportunidades_y_voz_turista.csv", csv3_txt.encode("utf-8"), content_type="text/csv; charset=utf-8")
        await Actor.set_value("dashboard_consolidado.csv", unico_txt.encode("utf-8"), content_type="text/csv; charset=utf-8")
        await Actor.set_value(
            "contenido_graficas_dashboard.xlsx",
            res["xlsx_bytes"],
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        summary_payload = dict(res["summary"])
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

        # Subir tabla única uniforme al Dataset Apify para consumo directo en Google Sheets vía n8n
        dataset_rows = json.loads(res["dashboard_consolidado"].to_json(orient="records"))
        if dataset_rows:
            await Actor.push_data(dataset_rows)

        Actor.log.info(f"APIFY EDA completado: {res['summary']}")
