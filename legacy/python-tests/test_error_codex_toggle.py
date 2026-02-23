from __future__ import annotations

from argparse import Namespace
from contextlib import contextmanager

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


def test_error_codex_skips_spawn_when_lock_is_busy(monkeypatch) -> None:
    # Purpose: prevent duplicate error panes from concurrent aiteam processes.
    monkeypatch.delenv("AITEAM_ENABLE_ERROR_CODEX", raising=False)
    monkeypatch.delenv("AITEAM_DISABLE_ERROR_CODEX", raising=False)
    monkeypatch.setattr(cli, "_resolve_session", lambda _s: "demo")
    monkeypatch.setattr(cli, "tmux_version", lambda: "3.4")
    monkeypatch.setattr(cli, "_error_codex_already_running", lambda _s: False)

    @contextmanager
    def _busy_lock(_session: str):
        yield False

    monkeypatch.setattr(cli, "_acquire_error_analyzer_lock", _busy_lock)
    monkeypatch.setattr(cli, "split_from", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not split")))

    cli._auto_start_error_analyzer_codex(_args(error_codex=True), error_text="x")


def test_error_codex_rechecks_running_inside_lock(monkeypatch) -> None:
    # Purpose: avoid TOCTOU races by checking existing err pane after lock acquisition.
    monkeypatch.delenv("AITEAM_ENABLE_ERROR_CODEX", raising=False)
    monkeypatch.delenv("AITEAM_DISABLE_ERROR_CODEX", raising=False)
    monkeypatch.setattr(cli, "_resolve_session", lambda _s: "demo")
    monkeypatch.setattr(cli, "tmux_version", lambda: "3.4")

    @contextmanager
    def _held_lock(_session: str):
        yield True

    monkeypatch.setattr(cli, "_acquire_error_analyzer_lock", _held_lock)
    monkeypatch.setattr(cli, "_error_codex_already_running", lambda _s: True)
    monkeypatch.setattr(cli, "split_from", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not split")))

    cli._auto_start_error_analyzer_codex(_args(error_codex=True), error_text="x")
