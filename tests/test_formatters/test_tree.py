"""Tests for upscaler_cli.formatters.tree module."""

from upscaler_cli.formatters.tree import format_tree


def test_tree_single_node():
    """Root node only renders title, type, and id."""
    node = {"id": "1", "title": "Root", "type": "folder"}
    result = format_tree(node)

    assert result == "Root (folder) [1]"


def test_tree_nested():
    """Root with 2 children, one having a grandchild."""
    node = {
        "id": "1",
        "title": "Root",
        "type": "folder",
        "children": [
            {
                "id": "2",
                "title": "Child A",
                "type": "file",
                "children": [
                    {"id": "4", "title": "Grandchild", "type": "file"},
                ],
            },
            {"id": "3", "title": "Child B", "type": "file"},
        ],
    }
    result = format_tree(node)
    lines = result.split("\n")

    assert len(lines) == 4
    assert "Root" in lines[0]
    assert "Child A" in lines[1]
    assert "Grandchild" in lines[2]
    assert "Child B" in lines[3]


def test_tree_uses_connectors():
    """Tree output uses └── and ├── connector characters."""
    node = {
        "id": "1",
        "title": "Root",
        "type": "folder",
        "children": [
            {"id": "2", "title": "First", "type": "file"},
            {"id": "3", "title": "Last", "type": "file"},
        ],
    }
    result = format_tree(node)

    assert "├── " in result  # non-last sibling
    assert "└── " in result  # last sibling
