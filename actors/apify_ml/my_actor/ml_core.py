"""Compatibilidad de re-export para TerraScout Actor 3 (Solo Inferencia).

Los módulos principales viven en `preprocessing.py` y `tooling_business.py`.
El entrenamiento del modelo fue movido fuera del Actor a `src/training.py`.
"""

from __future__ import annotations

try:
    from my_actor.preprocessing import (
        enrich_ml_features,
        load_business_rules,
        load_clean_dataset,
        normalize_drive_url,
        read_bytes_source,
        resolve_repo_path,
    )
    from my_actor.tooling_business import (
        build_validation_sample,
        execute_ml_actor,
        format_telegram_summary,
        load_model_bundle,
        score_opportunities,
        sha256_bytes,
    )
except ImportError:
    from .preprocessing import (
        enrich_ml_features,
        load_business_rules,
        load_clean_dataset,
        normalize_drive_url,
        read_bytes_source,
        resolve_repo_path,
    )
    from .tooling_business import (
        build_validation_sample,
        execute_ml_actor,
        format_telegram_summary,
        load_model_bundle,
        score_opportunities,
        sha256_bytes,
    )

__all__ = [
    "build_validation_sample",
    "enrich_ml_features",
    "execute_ml_actor",
    "format_telegram_summary",
    "load_business_rules",
    "load_clean_dataset",
    "load_model_bundle",
    "normalize_drive_url",
    "read_bytes_source",
    "resolve_repo_path",
    "score_opportunities",
    "sha256_bytes",
]