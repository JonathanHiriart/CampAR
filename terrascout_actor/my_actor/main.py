"""Entrypoint Apify para TerraScout Actor (Regla R4: solo armado del Actor SDK)."""

from __future__ import annotations

try:
    from my_actor.nlp_analysis import execute_terrascout_pipeline
    from my_actor.sdk_compat import Actor
except ImportError:
    from .nlp_analysis import execute_terrascout_pipeline
    from .sdk_compat import Actor


async def main() -> None:
    """Orquesta entradas/salidas vía SDK Apify delegando la lógica a `nlp_analysis`."""
    async with Actor:
        actor_input = await Actor.get_input() or {}
        await Actor.set_status_message("TerraScout Actor: cargando configuración y ejecutando pipeline...")

        store = await Actor.open_key_value_store()
        precomputed_topics = None
        topics_kv_key = str(actor_input.get("topics_kv_key") or "").strip()
        if topics_kv_key:
            precomputed_topics = await store.get_value(topics_kv_key)

        result = execute_terrascout_pipeline(
            actor_input=actor_input,
            log=Actor.log,
            precomputed_topics=precomputed_topics,
        )

        if result["topics_res"]:
            await Actor.set_value("topics_res.json", result["topics_res"])

        enhanced_listings = result["enhanced_listings"]
        if enhanced_listings:
            await Actor.push_data(enhanced_listings)
            Actor.log.info(f"Dataset Apify cargado con {len(enhanced_listings)} publicaciones reales.")
            await Actor.set_status_message(f"Completado: {len(enhanced_listings)} publicaciones publicadas.")
        else:
            await Actor.push_data({
                "status": "completed",
                "processed_items": 0,
                "topics": result["topics_res"],
            })
            await Actor.set_status_message("Completado sin publicaciones; tópicos guardados.")
