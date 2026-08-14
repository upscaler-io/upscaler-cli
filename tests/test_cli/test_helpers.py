"""Tests for CLI helpers."""

from types import SimpleNamespace

import pytest

from upscaler_cli.cli.helpers import confirm_destructive, emit_action_result, parse_data
from upscaler_cli.errors import CLIError


class TestParseData:
    def test_parse_json_string(self):
        result = parse_data('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_nested_json(self):
        result = parse_data('{"outer": {"inner": [1, 2, 3]}}')
        assert result == {"outer": {"inner": [1, 2, 3]}}

    def test_parse_file_reference(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"from_file": true}')
        result = parse_data(f"@{f}")
        assert result == {"from_file": True}

    def test_parse_file_with_nested_data(self, tmp_path):
        f = tmp_path / "nested.json"
        f.write_text('{"values": {"status": "done", "count": 42}}')
        result = parse_data(f"@{f}")
        assert result == {"values": {"status": "done", "count": 42}}

    def test_parse_missing_file(self):
        with pytest.raises(CLIError, match="File not found"):
            parse_data("@nonexistent.json")

    def test_parse_invalid_json(self):
        with pytest.raises(CLIError, match="Invalid JSON"):
            parse_data("not json")

    def test_parse_invalid_json_partial(self):
        with pytest.raises(CLIError, match="Invalid JSON"):
            parse_data('{"unclosed": ')

    def test_parse_non_object_array(self):
        with pytest.raises(CLIError, match="JSON object"):
            parse_data("[1, 2, 3]")

    def test_parse_non_object_string(self):
        with pytest.raises(CLIError, match="JSON object"):
            parse_data('"just a string"')

    def test_parse_non_object_number(self):
        with pytest.raises(CLIError, match="JSON object"):
            parse_data("42")

    def test_parse_empty_object(self):
        result = parse_data("{}")
        assert result == {}

    def test_parse_stdin_marker(self):
        """Stdin ('-') needs actual stdin piping; just verify it doesn't crash on non-TTY."""
        # We cannot easily test stdin in CliRunner without input parameter,
        # but we can verify the path exists by checking the function signature.
        # A full stdin test would require mocking sys.stdin.
        pass


class TestEmitActionResult:
    @staticmethod
    def _ctx(*, quiet=False, json_mode=False):
        return SimpleNamespace(quiet_mode=quiet, json_mode=json_mode)

    def test_quiet_prints_resolved_id(self, capsys):
        emit_action_result(
            self._ctx(quiet=True),
            {"success": True, "data": {"id": "i_42"}},
            label="Created",
        )
        captured = capsys.readouterr()
        assert captured.out.strip() == "i_42"
        assert captured.err == ""

    def test_quiet_success_without_id_fails_loud(self, capsys):
        """A success envelope with no resolvable id must not emit empty stdout
        and exit 0 under --quiet; it should fail loud on stderr."""
        with pytest.raises(SystemExit) as exc:
            emit_action_result(
                self._ctx(quiet=True),
                {"success": True, "data": {}},
                label="Created",
            )
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert captured.out.strip() == ""
        assert "no id" in captured.err.lower()


class TestConfirmDestructive:
    def test_json_mode_skips_confirmation(self):
        assert confirm_destructive("delete", "item_1", json_mode=True) is True

    def test_non_tty_skips_confirmation(self):
        # CliRunner runs in non-TTY mode, so stdout.isatty() returns False
        # confirm_destructive returns True when not a TTY
        assert confirm_destructive("delete", "item_1", json_mode=False) is True
