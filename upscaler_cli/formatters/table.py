"""Human-readable table output formatter."""

from typing import Any, Dict, List, Optional


def format_table(
    data: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    max_width: int = 40,
) -> str:
    """Format a list of dicts as an aligned text table.

    Args:
        data: List of row dicts.
        columns: Column keys to display. If None, uses keys from first row.
        max_width: Max width per column (truncates with ...).

    Returns:
        Formatted table string.
    """
    if not data:
        return "No data."

    if columns is None:
        columns = list(data[0].keys())

    # Calculate column widths
    widths = {col: len(col) for col in columns}
    for row in data:
        for col in columns:
            val = str(row.get(col, ""))
            widths[col] = min(max(widths[col], len(val)), max_width)

    # Build header
    header = "  ".join(col.ljust(widths[col]) for col in columns)
    separator = "  ".join("-" * widths[col] for col in columns)

    # Build rows
    rows = []
    for row in data:
        cells = []
        for col in columns:
            val = str(row.get(col, ""))
            if len(val) > widths[col]:
                val = val[: widths[col] - 3] + "..."
            cells.append(val.ljust(widths[col]))
        rows.append("  ".join(cells))

    return "\n".join([header, separator] + rows)
