from __future__ import annotations

from argparse import Namespace

import tmux_ai_team.cli as cli


def _args(**overrides):
    base = {
        "error_codex": False,
        "no_error_codex": False,
        "_exit_code": 1,
        "session": "demo",
        "_argv": [],
    }
    base.update(overrides)
    return Namespace(**base)


def test_error_codex_default_is_disabled(monkeypatch) -> None:
    monkeypatch.delenv("AITEAM_ENABLE_ERROR_CODEX", raising=False)
    monkeypatch.delenv("AITEAM_DISABLE_ERROR_CODEX", raising=False)
    monkeypatch.setattr(cli, "_resolve_session", lambda _s: (_ for _ in ()).throw(AssertionError("must not run")))

    cli._auto_start_error_analyzer_codex(_args(), error_text="x")


def test_error_codex_enabled_by_flag_attempts_resolution(monkeypatch) -> None:
    monkeypatch.delenv("AITEAM_ENABLE_ERROR_CODEX", raising=False)
    monkeypatch.delenv("AITEAM_DISABLE_ERROR_CODEX", raising=False)

    called = []
    monkeypatch.setattr(cli, "_resolve_session", lambda _s: called.append(True) or "demo")
    monkeypatch.setattr(cli, "tmux_version", lambda: (_ for _ in ()).throw(RuntimeError("stop")))

    cli._auto_start_error_analyzer_codex(_args(error_codex=True), error_text="x")

    assert called == [True]


def test_no_error_codex_overrides_enable(monkeypatch) -> None:
    monkeypatch.setenv("AITEAM_ENABLE_ERROR_CODEX", "1")
    monkeypatch.setattr(cli, "_resolve_session", lambda _s: (_ for _ in ()).throw(AssertionError("must not run")))

    cli._auto_start_error_analyzer_codex(_args(error_codex=True, no_error_codex=True), error_text="x")
