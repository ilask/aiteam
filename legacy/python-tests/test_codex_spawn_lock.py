from __future__ import annotations

import re
import threading
import time
from types import SimpleNamespace

import tmux_ai_team.cli as cli


def _codex_args(*, name: str):
    return SimpleNamespace(
        session=None,
        id=None,
        name=name,
        command="codex -p aiteam",
        cwd=None,
        layout="vertical",
        tiled=False,
        split_from=None,
        focus="stay",
        quiet=True,
        print_selector=False,
        json=False,
        if_exists="error",
    )


def test_cmd_codex_parallel_calls_allocate_distinct_ids(monkeypatch) -> None:
    try:
        import fcntl
    except ImportError:
        import pytest
        pytest.skip("fcntl not available on this platform (e.g. Windows), lock is a no-op")

    # Purpose: concurrent codex spawns should serialize ID allocation to avoid duplicate codex:1.
    monkeypatch.setattr(cli, "_resolve_session", lambda _s: "demo")

    state_lock = threading.Lock()
    allocated_ids: list[str] = []

    def _fake_list_codex_panes(_session: str):
        with state_lock:
            ids_snapshot = list(allocated_ids)
        out = []
        for idx, cid in enumerate(ids_snapshot):
            out.append((cid, f"n{cid}", SimpleNamespace(pane_id=f"%{idx}", pane_index=idx, pane_title=f"codex#{cid}:n{cid}")))
        return out

    def _fake_cmd_add(add_args) -> int:  # noqa: ANN001
        m = re.match(r"^codex#([^:]+):", add_args.name or "")
        assert m is not None
        cid = m.group(1)
        # Slow down creation so an unlocked implementation would race on id allocation.
        time.sleep(0.05)
        with state_lock:
            allocated_ids.append(cid)
        return 0

    monkeypatch.setattr(cli, "_list_codex_panes", _fake_list_codex_panes)
    monkeypatch.setattr(cli, "cmd_add", _fake_cmd_add)

    rc_list: list[int] = []

    def _run(name: str) -> None:
        rc_list.append(cli.cmd_codex(_codex_args(name=name)))

    t1 = threading.Thread(target=_run, args=("a",))
    t2 = threading.Thread(target=_run, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(rc_list) == [0, 0]
    with state_lock:
        assert sorted(allocated_ids, key=int) == ["1", "2"]
