"""E2E-local conftest should stay minimal.

Prefer adding shared fixtures/helpers to `tests/conftest.py` first.
Only place truly e2e-directory-specific hooks here.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _apply_tmux_invocation_guard_to_all_e2e(tmux_invocation_guard):
    """Enable tmux caller-boundary guard for every e2e test."""
    _ = tmux_invocation_guard
