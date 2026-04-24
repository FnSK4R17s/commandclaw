"""Tests for commandclaw.hatching — identity model, collection, and file writing."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from commandclaw.hatching import HatchIdentity, collect_hatch_input, write_identity_file

# ============================================================
# HatchIdentity model
# ============================================================


class TestHatchIdentity:
    def test_valid_identity(self) -> None:
        h = HatchIdentity(name="Claw", emoji="*", creature="familiar", vibe="curious")
        assert h.name == "Claw"
        assert h.creature == "familiar"

    def test_name_is_stripped(self) -> None:
        h = HatchIdentity(name="  Claw  ")
        assert h.name == "Claw"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Name is required"):
            HatchIdentity(name="")

    def test_whitespace_only_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Name is required"):
            HatchIdentity(name="   ")

    def test_optional_fields_default_empty(self) -> None:
        h = HatchIdentity(name="Claw")
        assert h.emoji == ""
        assert h.creature == ""
        assert h.vibe == ""


# ============================================================
# collect_hatch_input
# ============================================================


class TestCollectHatchInput:
    def test_happy_path(self) -> None:
        inputs = iter(["Claw", "*", "familiar", "curious", "I'm a dev"])
        result = collect_hatch_input("test-agent", input_fn=lambda _: next(inputs))

        assert result is not None
        identity, intro = result
        assert identity.name == "Claw"
        assert identity.emoji == "*"
        assert identity.creature == "familiar"
        assert identity.vibe == "curious"
        assert intro == "I'm a dev"

    def test_empty_name_reprompts(self) -> None:
        inputs = iter(["", "", "Claw", "", "", "", "hi"])
        result = collect_hatch_input("test-agent", input_fn=lambda _: next(inputs))

        assert result is not None
        assert result[0].name == "Claw"

    def test_all_optional_fields_blank(self) -> None:
        inputs = iter(["Claw", "", "", "", ""])
        result = collect_hatch_input("test-agent", input_fn=lambda _: next(inputs))

        assert result is not None
        identity, intro = result
        assert identity.emoji == ""
        assert identity.creature == ""
        assert identity.vibe == ""
        assert intro == ""

    def test_eof_returns_none(self) -> None:
        def raise_eof(_: str) -> str:
            raise EOFError

        result = collect_hatch_input("test-agent", input_fn=raise_eof)
        assert result is None

    def test_keyboard_interrupt_returns_none(self) -> None:
        def raise_kb(_: str) -> str:
            raise KeyboardInterrupt

        result = collect_hatch_input("test-agent", input_fn=raise_kb)
        assert result is None

    def test_print_fn_receives_output(self) -> None:
        inputs = iter(["Claw", "", "", "", "hello"])
        printed: list[str] = []
        collect_hatch_input(
            "my-agent",
            input_fn=lambda _: next(inputs),
            print_fn=lambda *args: printed.append(" ".join(str(a) for a in args)),
        )
        assert any("my-agent" in line for line in printed)


# ============================================================
# write_identity_file
# ============================================================


class TestWriteIdentityFile:
    def test_writes_identity_fields(self, tmp_path: Path) -> None:
        identity = HatchIdentity(name="Claw", emoji="*", creature="robot", vibe="calm")
        write_identity_file(tmp_path, identity)

        content = (tmp_path / "IDENTITY.md").read_text()
        assert "**Name:** Claw" in content
        assert "**Creature:** robot" in content
        assert "**Vibe:** calm" in content
        assert "**Emoji:** *" in content

    def test_defaults_for_optional_fields(self, tmp_path: Path) -> None:
        identity = HatchIdentity(name="Claw")
        write_identity_file(tmp_path, identity)

        content = (tmp_path / "IDENTITY.md").read_text()
        assert "(choose your own)" in content

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / "IDENTITY.md").write_text("old content")
        identity = HatchIdentity(name="New")
        write_identity_file(tmp_path, identity)

        content = (tmp_path / "IDENTITY.md").read_text()
        assert "old content" not in content
        assert "**Name:** New" in content
