"""Compatibilidad con Apify SDK para `terrascout_actor`.

Provee `Actor` real de `apify` cuando está disponible en runtime Apify, o un mock
tipado para pruebas locales sin dependencias externas.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from apify import Actor
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

    class _MockActorLog:
        """Logger compatible con `Actor.log` para ejecución local."""

        @staticmethod
        def info(msg: str) -> None:
            logging.info(msg)

        @staticmethod
        def warning(msg: str) -> None:
            logging.warning(msg)

        @staticmethod
        def error(msg: str) -> None:
            logging.error(msg)

    class _MockKeyValueStore:
        """Key-Value Store en memoria para ejecución local."""

        def __init__(self) -> None:
            self._store: dict[str, Any] = {}

        async def get_value(self, key: str, default_value: Any = None) -> Any:
            return self._store.get(key, default_value)

        async def set_value(self, key: str, value: Any, content_type: str | None = None) -> None:
            self._store[key] = value

    class _MockActor:
        """Mock liviano de `apify.Actor` para tests unitarios offline."""

        log = _MockActorLog()

        def __init__(self) -> None:
            self._kv = _MockKeyValueStore()

        async def get_input(self) -> dict[str, Any]:
            return {}

        async def push_data(self, data: Any) -> None:
            return None

        async def set_value(self, key: str, value: Any, content_type: str | None = None) -> None:
            await self._kv.set_value(key, value, content_type=content_type)

        async def open_key_value_store(self, id: str | None = None, name: str | None = None) -> _MockKeyValueStore:
            return self._kv

        async def set_status_message(self, message: str) -> None:
            self.log.info(message)

        async def __aenter__(self) -> _MockActor:
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

    Actor = _MockActor()
