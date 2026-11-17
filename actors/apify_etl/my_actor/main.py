"""Entrypoint Apify para TerraScout Actor 1 (`APIFY ETL`)."""

from __future__ import annotations

import json
import logging
from typing import Any

from .etl_core import run_etl_pipeline

try:
    from apify import Actor
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

    class _MockLog:
        info = staticmethod(logging.getLogger("apify_etl").info)

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
    """Lee las fuentes RAW, ejecuta ETL y publica `dataset_limpio.csv` + filas JSON."""
    async with Actor:
        inp = await Actor.get_input() or {}
        Actor.log.info("Iniciando TerraScout APIFY ETL...")

        df_clean, funnel = run_etl_pipeline(
            ml_csv_source=str(inp.get("ml_csv_url") or ""),
            campings_csv_source=str(inp.get("campings_csv_url") or ""),
            places_csv_source=str(inp.get("places_csv_url") or ""),
            topo_csv_source=str(inp.get("topo_csv_url") or ""),
            rules_json_source=str(inp.get("rules_json_url") or ""),
            tipo_cambio_override=float(inp.get("tipo_cambio_ars_usd_override") or 0.0),
        )

        csv_text = df_clean.to_csv(index=False)
        await Actor.set_value("dataset_limpio.csv", csv_text.encode("utf-8"), content_type="text/csv; charset=utf-8")

        funnel_payload: dict[str, Any] = {"funnel": funnel, "total_clean": int(len(df_clean))}
        if HAS_APIFY:
            try:
                store = await Actor.open_key_value_store()
                funnel_payload["dataset_limpio_public_url"] = await store.get_public_url("dataset_limpio.csv")
            except Exception as exc:  # pragma: no cover - depende de runtime Apify
                Actor.log.warning(f"No se pudo obtener public_url del KV Store: {exc}")

        await Actor.set_value("etl_funnel.json", funnel_payload)

        records = json.loads(df_clean.to_json(orient="records"))
        if records:
            await Actor.push_data(records)

        Actor.log.info(f"ETL completado: {len(df_clean)} registros limpios exportados a dataset_limpio.csv.")