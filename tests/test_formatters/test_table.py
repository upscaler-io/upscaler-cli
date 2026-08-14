"""Tests for upscaler_cli.formatters.table module."""

from upscaler_cli.formatters.table import format_table


def test_table_basic():
    """Format a 2-row table with header, separator, and data rows."""
    data = [
        {"name": "Alice", "age": "30"},
        {"name": "Bob", "age": "25"},
    ]
    result = format_table(data)
    lines = result.split("\n")

    assert len(lines) == 4  # header + separator + 2 rows
    assert "name" in lines[0]
    assert "age" in lines[0]
    assert set(lines[1].replace(" ", "")) == {"-"}
    assert "Alice" in lines[2]
    assert "Bob" in lines[3]


def test_table_custom_columns():
    """Only specified columns appear in the output."""
    data = [
        {"name": "Alice", "age": "30", "email": "alice@example.com"},
    ]
    result = format_table(data, columns=["name", "email"])
    lines = result.split("\n")

    assert "name" in lines[0]
    assert "email" in lines[0]
    assert "age" not in lines[0]


def test_table_empty_data():
    """Empty data list returns 'No data.'."""
    result = format_table([])
    assert result == "No data."


def test_table_truncation():
    """Values longer than max_width are truncated with '...'."""
    data = [
        {"value": "a" * 50},
    ]
    result = format_table(data, max_width=10)
    lines = result.split("\n")

    # Data row should contain truncated value ending with "..."
    data_row = lines[2]
    assert "..." in data_row
    assert len(data_row.strip()) <= 10
