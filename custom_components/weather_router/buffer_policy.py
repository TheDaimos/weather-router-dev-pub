"""E-078 versioned, provider-independent buffer policy registration.

Prototype-only: no extension autoload and no live consumer routing.
Registration never changes ordinary provider or quota authorizations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .buffer_core import BufferPolicy, IsolatedBuffer, validate_policy

POLICY_CONTRACT = "weather_router.buffer_policy.v1"


@dataclass(frozen=True)
class BufferContext:
    provider_id: str
    capability_id: str
    consumer_id: str
    scope_key: str
    operation: str


class BufferPolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, Callable[[BufferContext], BufferPolicy]] = {}

    def register(self, extension_id: str,
                 function: Callable[[BufferContext], BufferPolicy]) -> None:
        if (not isinstance(extension_id, str) or not extension_id
                or not extension_id.replace("_", "").isalnum()
                or not callable(function) or extension_id in self._policies):
            raise ValueError("invalid or duplicate policy registration")
        self._policies[extension_id] = function

    def unregister(self, extension_id: str) -> None:
        self._policies.pop(extension_id, None)

    def decide(self, context: BufferContext) -> BufferPolicy:
        if (not isinstance(context, BufferContext)
                or context.operation not in {"cache_write", "cache_serve", "prefetch"}
                or any(not isinstance(item, str) or not item
                       for item in (context.provider_id, context.capability_id,
                                    context.consumer_id, context.scope_key))):
            return BufferPolicy()
        # No policy, competing extensions or exceptions: fail closed, never
        # assume a licence or privilege because a module was installed.
        if len(self._policies) != 1:
            return BufferPolicy()
        function = next(iter(self._policies.values()))
        try:
            return validate_policy(function(context))
        except Exception:
            return BufferPolicy()


class PolicyControlledBuffer:
    def __init__(self, buffer: IsolatedBuffer,
                 registry: BufferPolicyRegistry) -> None:
        self._buffer = buffer
        self._registry = registry

    def _key(self, context: BufferContext) -> tuple[str, str, str, str]:
        # Cache entries are scoped to consumer and spatial/time identifier.
        return (context.provider_id, context.capability_id,
                context.consumer_id, context.scope_key)

    def write(self, context: BufferContext, payload: bytes, *,
              provider_authorized: bool, prefetch: bool = False) -> bool:
        operation = "prefetch" if prefetch else "cache_write"
        requested = BufferContext(context.provider_id, context.capability_id,
                                  context.consumer_id, context.scope_key, operation)
        return self._buffer.write(self._key(requested), payload,
                                  policy=self._registry.decide(requested),
                                  authorized=provider_authorized, prefetch=prefetch)

    def read(self, context: BufferContext, *,
             provider_authorized: bool) -> bytes | None:
        requested = BufferContext(context.provider_id, context.capability_id,
                                  context.consumer_id, context.scope_key, "cache_serve")
        return self._buffer.read(self._key(requested),
                                 policy=self._registry.decide(requested),
                                 authorized=provider_authorized)

    def policy_changed(self) -> None:
        # Conservative: discard all data when rights change or module unloads.
        self._buffer.clear()
