"""Indented tree view formatter for asset hierarchies."""

from typing import Any, Dict


def format_tree(
    node: Dict[str, Any],
    indent: int = 0,
    prefix: str = "",
    is_last: bool = True,
) -> str:
    """Format a hierarchy node as an indented tree view.

    Args:
        node: Dict with 'id', 'title', 'type', and optional 'children' list.
        indent: Current indentation level.
        prefix: Line prefix for tree drawing characters.
        is_last: Whether this is the last sibling.

    Returns:
        Multi-line tree string.
    """
    connector = "└── " if is_last else "├── "
    node_id = node.get("id", "")
    title = node.get("title", "Untitled")
    node_type = node.get("type", node.get("assetType", ""))

    if indent == 0:
        line = f"{title} ({node_type}) [{node_id}]"
    else:
        line = f"{prefix}{connector}{title} ({node_type}) [{node_id}]"

    lines = [line]

    children = node.get("children", [])
    child_prefix = prefix + ("    " if is_last else "│   ")

    for i, child in enumerate(children):
        child_lines = format_tree(
            child,
            indent=indent + 1,
            prefix=child_prefix,
            is_last=(i == len(children) - 1),
        )
        lines.append(child_lines)

    return "\n".join(lines)
