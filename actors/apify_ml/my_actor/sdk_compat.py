"""Compatibilidad y helpers Apify SDK para TerraScout ML Actor (Regla R1/R4)."""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

try:
    from apify import Actor
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

    class _MockLog:
        """Logger compatible con `Actor.log` para pruebas locales."""

        info = staticmethod(logging.getLogger("apify_ml").info)
        warning = staticmethod(logging.getLogger("apify_ml").warning)
        error = staticmethod(logging.getLogger("apify_ml").error)

    class _MockKeyValueStore:
        """Key-Value Store en memoria para ejecución offline."""

        def __init__(self) -> None:
            self._store: dict[str, Any] = {}

        async def get_value(self, key: str, default_value: Any = None) -> Any:
            return self._store.get(key, default_value)

        async def set_value(self, key: str, value: Any, content_type: str | None = None) -> None:
            self._store[key] = value

        async def get_public_url(self, key: str) -> str:
            return f"kv://default/{key}"

    class _MockDataset:
        """Dataset en memoria para ejecución offline."""

        async def get_data(self, limit: int | None = None) -> Any:
            class _Page:
                items: list[dict[str, Any]] = []
            return _Page()

    class _MockActor:
        """Mock liviano de `apify.Actor` cuando `apify` no está instalado."""

        log = _MockLog()

        def __init__(self) -> None:
            self._kv = _MockKeyValueStore()
            self._ds = _MockDataset()

        async def get_input(self) -> dict[str, Any]:
            return {}

        async def push_data(self, data: Any) -> None:
            return None

        async def set_value(self, key: str, value: Any, content_type: str | None = None) -> None:
            await self._kv.set_value(key, value, content_type=content_type)

        async def open_key_value_store(self, id: str | None = None, name: str | None = None) -> _MockKeyValueStore:
            return self._kv

        async def open_dataset(self, id: str | None = None, name: str | None = None) -> _MockDataset:
            return self._ds

        async def set_status_message(self, message: str) -> None:
            self.log.info(message)

        async def __aenter__(self) -> _MockActor:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    Actor = _MockActor()


def _coerce_kv_text(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return bytes(val).decode("utf-8", errors="replace")
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, str):
        return val
    return None


def _coerce_kv_bytes(val: Any) -> bytes | None:
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    if isinstance(val, str):
        return base64.b64decode(val)
    return None


def _parse_apify_kv_url(url: str) -> tuple[str, str] | None:
    if "signature=" in url:
        return None
    m = re.match(r"^https://api\.apify\.com/v2/key-value-stores/([^/]+)/records/([^/?#]+)", url.strip())
    return (m.group(1), m.group(2)) if m else None


def _parse_apify_dataset_url(url: str) -> str | None:
    if "signature=" in url or "token=" in url:
        return None
    m = re.match(r"^https://api\.apify\.com/v2/datasets/([^/]+)/items", url.strip())
    return m.group(1) if m else None


async def resolve_ml_sdk_inputs(
    actor: Any,
    inp: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, Any]] | None, bytes | None]:
    """Lee inputs desde KV Store / Dataset / payload inline vía Apify SDK (R1)."""
    sdk_texts: dict[str, str] = {}
    sdk_records: list[dict[str, Any]] | None = None
    sdk_pkl_bytes: bytes | None = None

    if isinstance(inp.get("records"), list):
        sdk_records = list(inp["records"])

    dataset_id = str(inp.get("dataset_id") or "").strip() or _parse_apify_dataset_url(
        str(inp.get("dataset_limpio_url") or "")
    )
    if dataset_id and sdk_records is None:
        try:
            ds = await actor.open_dataset(id=dataset_id)
            data_page = await ds.get_data()
            items = getattr(data_page, "items", None)
            if items:
                sdk_records = list(items)
        except Exception as exc:
            actor.log.warning(f"Dataset externo no accesible por SDK ({dataset_id}): {exc}")

    kv_store_id = str(inp.get("kv_store_id") or "").strip() or None
    default_store = await actor.open_key_value_store(id=kv_store_id)

    for text_key in ("dataset_limpio_csv", "rules_json"):
        raw = inp.get(text_key)
        if raw is not None and raw != "":
            sdk_texts[text_key] = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)

    if inp.get("model_pkl_b64"):
        sdk_pkl_bytes = base64.b64decode(str(inp["model_pkl_b64"]))

    for inp_k, dest_k in (("dataset_limpio_kv_key", "dataset_limpio_csv"), ("rules_json_kv_key", "rules_json")):
        rec_key = str(inp.get(inp_k) or "").strip()
        if rec_key and dest_k not in sdk_texts:
            txt = _coerce_kv_text(await default_store.get_value(rec_key))
            if txt:
                sdk_texts[dest_k] = txt

    pkl_kv_key = str(inp.get("model_pkl_kv_key") or "").strip()
    if pkl_kv_key and sdk_pkl_bytes is None:
        sdk_pkl_bytes = _coerce_kv_bytes(await default_store.get_value(pkl_kv_key))

    for url_field, dest_k in (("dataset_limpio_url", "dataset_limpio_csv"), ("rules_json_url", "rules_json")):
        kv_ref = _parse_apify_kv_url(str(inp.get(url_field) or ""))
        if kv_ref and dest_k not in sdk_texts:
            try:
                ref_store = await actor.open_key_value_store(id=kv_ref[0])
                txt = _coerce_kv_text(await ref_store.get_value(kv_ref[1]))
                if txt:
                    sdk_texts[dest_k] = txt
            except Exception as exc:
                actor.log.warning(f"KV Store externo no accesible por SDK ({kv_ref[0]}): {exc}")

    pkl_ref = _parse_apify_kv_url(str(inp.get("model_pkl_url") or ""))
    if pkl_ref and sdk_pkl_bytes is None:
        try:
            ref_store = await actor.open_key_value_store(id=pkl_ref[0])
            sdk_pkl_bytes = _coerce_kv_bytes(await ref_store.get_value(pkl_ref[1]))
        except Exception as exc:
            actor.log.warning(f"Modelo KV Store externo no accesible por SDK ({pkl_ref[0]}): {exc}")

    return sdk_texts, sdk_records, sdk_pkl_bytes
