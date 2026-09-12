"""Define and safely dispatch the read-only repository tools for the spike."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from reposentinel.tools.repository_tools import RepositoryTools

TOOL_NAMES = (
    "get_project_summary",
    "list_tree",
    "get_ast_summary",
    "read_file",
    "search_code",
)

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_project_summary": {
        "type": "function",
        "function": {
            "name": "get_project_summary",
            "description": "Return a compact static summary of the repository.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    "list_tree": {
        "type": "function",
        "function": {
            "name": "list_tree",
            "description": "List included repository-relative files.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    "get_ast_summary": {
        "type": "function",
        "function": {
            "name": "get_ast_summary",
            "description": (
                "Return syntax-only facts for one repository-relative Python file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative Python file path.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "read_file": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one repository-relative text file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative file path.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "search_code": {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Find a literal, case-sensitive string in repository files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Non-empty literal string to search for.",
                    }
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
    },
}


def build_tool_schemas(tool_names: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Return OpenAI-compatible schemas for the selected repository tools.

    Args:
        tool_names: Tool names to expose. All read-only tools are returned when
            omitted.

    Returns:
        Function schemas in deterministic tool-name order.

    Raises:
        ValueError: If a requested tool is not supported by the spike.
    """
    selected_names = TOOL_NAMES if tool_names is None else tuple(tool_names)
    unsupported = set(selected_names) - set(TOOL_NAMES)
    if unsupported:
        unsupported_names = ", ".join(sorted(unsupported))
        raise ValueError(f"Unsupported repository tool: {unsupported_names}")
    return [_TOOL_SCHEMAS[name] for name in selected_names]


def execute_tool(
    repository_tools: RepositoryTools, tool_name: str, arguments: dict[str, object]
) -> object:
    """Validate and execute one read-only repository tool call.

    Args:
        repository_tools: Tools bound to the selected repository root.
        tool_name: Name returned by the model.
        arguments: Decoded JSON arguments returned by the model.

    Returns:
        The selected ``RepositoryTools`` result.

    Raises:
        ValueError: If the tool name or arguments are unsupported or invalid.
    """
    if tool_name not in TOOL_NAMES:
        raise ValueError(f"Unsupported repository tool: {tool_name}")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object")
    if tool_name in {"get_project_summary", "list_tree"}:
        _require_no_arguments(arguments)
        if tool_name == "get_project_summary":
            return repository_tools.get_project_summary()
        return repository_tools.list_tree()

    argument_name = "keyword" if tool_name == "search_code" else "path"
    argument_value = _require_string_argument(arguments, argument_name)
    if tool_name == "get_ast_summary":
        return repository_tools.get_ast_summary(argument_value)
    if tool_name == "read_file":
        return repository_tools.read_file(argument_value)
    return repository_tools.search_code(argument_value)


def _require_no_arguments(arguments: dict[str, object]) -> None:
    if arguments:
        argument_names = ", ".join(sorted(arguments))
        raise ValueError(f"This tool does not accept arguments: {argument_names}")


def _require_string_argument(arguments: dict[str, object], name: str) -> str:
    if set(arguments) != {name}:
        raise ValueError(f"This tool requires exactly one '{name}' argument")
    value = arguments[name]
    if not isinstance(value, str) or not value:
        raise ValueError(f"'{name}' must be a non-empty string")
    return value
