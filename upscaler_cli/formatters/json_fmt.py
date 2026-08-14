"""Structured JSON output formatter."""

import json
from typing import Any


def format_json(data: Any, compact: bool = False) -> str:
    """Format data as JSON string.

    Args:
        data: Any JSON-serializable data.
        compact: If True, no indentation (for piping). If False, pretty-print.

    Returns:
        JSON string.
    """
    if compact:
        return json.dumps(data, default=str, ensure_ascii=False)
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


def output(data: Any, json_mode: bool, human_formatter=None, **kwargs) -> str:
    """Dispatch output to JSON or human formatter.

    Args:
        data: Data to format.
        json_mode: If True, output JSON. If False, use human_formatter.
        human_formatter: Callable(data, **kwargs) -> str for human output.
        **kwargs: Passed to human_formatter.

    Returns:
        Formatted string.
    """
    if json_mode:
        return format_json(data, compact=True)
    if human_formatter:
        return human_formatter(data, **kwargs)
    return format_json(data, compact=False)
