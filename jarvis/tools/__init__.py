"""Tool registry. A tool is a plain function returning a string; @tool registers it with the JSON
schema the model sees. `confirm` is either True (always ask the user first) or a function of the
arguments that returns a question to ask, or None when no confirmation is needed."""
from dataclasses import dataclass
from typing import Callable

ConfirmRule = bool | Callable[[dict], str | None] | None


@dataclass
class Tool:
    name: str
    fn: Callable[..., str]
    description: str
    params: dict
    required: list[str]
    confirm: ConfirmRule

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": self.params, "required": self.required},
            },
        }

    def confirmation(self, args: dict) -> str | None:
        if self.confirm is True:
            return f"{self.name}: {args}"
        if callable(self.confirm):
            return self.confirm(args)
        return None


REGISTRY: dict[str, Tool] = {}


def tool(description: str, params: dict | None = None, required: list[str] | None = None,
         confirm: ConfirmRule = None):
    params = params or {}

    def wrap(fn):
        REGISTRY[fn.__name__] = Tool(fn.__name__, fn, description, params,
                                     list(params) if required is None else required, confirm)
        return fn
    return wrap


def string(desc: str) -> dict:
    return {"type": "string", "description": desc}


def integer(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def clip(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def load() -> dict[str, Tool]:
    from . import files, pc, web, memory, google  # noqa: F401  (imported for registration)
    return REGISTRY
