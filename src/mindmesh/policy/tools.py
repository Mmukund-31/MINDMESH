"""Tool registry. Tools are plain (async or sync) Python functions; their signature
becomes a strict Pydantic argument model, so malformed or unexpected arguments are
rejected before any policy check or execution happens."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from ..core.errors import ToolArgumentError


@dataclass
class ToolContext:
    """Injected into tools that declare a ``ctx`` parameter."""

    run_id: str
    project_id: str
    agent: str
    step: int
    memory: Any = None  # MemoryStore
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    fn: Callable[..., Any]
    args_model: type[BaseModel]
    description: str
    side_effect: bool
    timeout_s: float | None
    wants_ctx: bool
    tags: list[str] = field(default_factory=list)

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise ToolArgumentError(f"{self.name}: arguments must be an object")
        try:
            return self.args_model.model_validate(args).model_dump()
        except ValidationError as e:
            errs = "; ".join(f"{'.'.join(map(str, x['loc'])) or '<root>'}: {x['msg']}" for x in e.errors())
            raise ToolArgumentError(f"{self.name}: invalid arguments: {errs}") from None

    def json_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "side_effect": self.side_effect,
            "parameters": self.args_model.model_json_schema(),
        }


def tool(
    name: str | None = None,
    *,
    description: str | None = None,
    side_effect: bool = False,
    timeout_s: float | None = None,
    tags: list[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a function as a MindMesh tool (register it with ``ToolRegistry.register``)."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__mindmesh_tool__ = {  # type: ignore[attr-defined]
            "name": name or fn.__name__,
            "description": description or inspect.getdoc(fn) or "",
            "side_effect": side_effect,
            "timeout_s": timeout_s,
            "tags": tags or [],
        }
        return fn

    return deco


def _args_model(tool_name: str, fn: Callable[..., Any]) -> tuple[type[BaseModel], bool]:
    sig = inspect.signature(fn)
    fields: dict[str, Any] = {}
    wants_ctx = False
    for p in sig.parameters.values():
        if p.name == "ctx":
            wants_ctx = True
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise TypeError(f"tool {tool_name}: *args/**kwargs are not allowed (arguments must be explicit)")
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else Any
        default = p.default if p.default is not inspect.Parameter.empty else ...
        fields[p.name] = (ann, default)
    model = create_model(  # type: ignore[call-overload]
        f"{tool_name.replace('.', '_')}_args",
        __config__=ConfigDict(extra="forbid", strict=True),
        **fields,
    )
    return model, wants_ctx


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, fn: Callable[..., Any], **overrides: Any) -> ToolSpec:
        meta = dict(getattr(fn, "__mindmesh_tool__", {}))
        meta.update({k: v for k, v in overrides.items() if v is not None})
        name = meta.get("name") or fn.__name__
        model, wants_ctx = _args_model(name, fn)
        spec = ToolSpec(
            name=name,
            fn=fn,
            args_model=model,
            description=meta.get("description") or inspect.getdoc(fn) or "",
            side_effect=bool(meta.get("side_effect", False)),
            timeout_s=meta.get("timeout_s"),
            wants_ctx=wants_ctx,
            tags=list(meta.get("tags", [])),
        )
        self._tools[name] = spec
        return spec

    def add(self, spec: ToolSpec) -> ToolSpec:
        """Register a prebuilt spec (integrations that already have an argument model, e.g. LangChain tools).
        ``spec.args_model`` should forbid extra fields, like the models built from function signatures."""
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, names: list[str] | None = None) -> list[ToolSpec]:
        if names is None:
            return [self._tools[n] for n in self.names()]
        return [self._tools[n] for n in names if n in self._tools]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
