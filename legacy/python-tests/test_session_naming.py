from __future__ import annotations

from types import SimpleNamespace

import tmux_ai_team.cli as cli


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_repo_name_from_remote_url_variants() -> None:
    assert cli._repo_name_from_remote_url("https://github.com/acme/my-repo.git") == "my-repo"
    assert cli._repo_name_from_remote_url("https://gitlab.com/group/subgroup/repo") == "repo"
    assert cli._repo_name_from_remote_url("git@github.com:acme/ssh-repo.git") == "ssh-repo"
    assert cli._repo_name_from_remote_url("ssh://git@gitlab.com/group/repo.git") == "repo"


def test_git_repo_name_priority_prefers_origin(monkeypatch) -> None:
    cwd = "/tmp/work"
    remotes = ["originx", "upstream", "origin", "origina", "beta"]
    urls = {
        "origin": "https://github.com/acme/repo-origin.git",
        "origina": "https://github.com/acme/repo-origina.git",
        "originx": "https://github.com/acme/repo-originx.git",
        "upstream": "https://github.com/acme/repo-upstream.git",
        "beta": "https://github.com/acme/repo-beta.git",
    }

    monkeypatch.setattr(cli, "_git_remote_names", lambda _cwd: remotes)
    monkeypatch.setattr(cli, "_git_toplevel", lambda _cwd: "/fallback/local-dir")

    def fake_run(args, **_kwargs):
        if args[:3] == ["git", "-C", cwd] and args[3:5] == ["remote", "get-url"]:
            remote = args[5]
            return _cp(stdout=f"{urls[remote]}\n")
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli._git_repo_name(cwd) == "repo-origin"


def test_git_repo_name_priority_prefers_origin_prefix_lexicographically(monkeypatch) -> None:
    cwd = "/tmp/work"
    remotes = ["originb", "upstream", "origina"]
    urls = {
        "origina": "https://github.com/acme/repo-a.git",
        "originb": "https://github.com/acme/repo-b.git",
        "upstream": "https://github.com/acme/repo-upstream.git",
    }

    monkeypatch.setattr(cli, "_git_remote_names", lambda _cwd: remotes)
    monkeypatch.setattr(cli, "_git_toplevel", lambda _cwd: "/fallback/local-dir")

    def fake_run(args, **_kwargs):
        remote = args[5]
        return _cp(stdout=f"{urls[remote]}\n")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli._git_repo_name(cwd) == "repo-a"


def test_git_repo_name_priority_prefers_other_remotes_lexicographically(monkeypatch) -> None:
    cwd = "/tmp/work"
    remotes = ["zeta", "alpha"]
    urls = {
        "alpha": "https://github.com/acme/repo-alpha.git",
        "zeta": "https://github.com/acme/repo-zeta.git",
    }

    monkeypatch.setattr(cli, "_git_remote_names", lambda _cwd: remotes)
    monkeypatch.setattr(cli, "_git_toplevel", lambda _cwd: "/fallback/local-dir")

    def fake_run(args, **_kwargs):
        remote = args[5]
        return _cp(stdout=f"{urls[remote]}\n")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli._git_repo_name(cwd) == "repo-alpha"


def test_git_repo_name_falls_back_to_local_toplevel(monkeypatch) -> None:
    cwd = "/tmp/work"
    monkeypatch.setattr(cli, "_git_remote_names", lambda _cwd: ["origin"])
    monkeypatch.setattr(cli, "_git_toplevel", lambda _cwd: "/projects/local-name")
    monkeypatch.setattr(cli.subprocess, "run", lambda _args, **_kwargs: _cp(returncode=1))
    assert cli._git_repo_name(cwd) == "local-name"


def test_resolve_new_session_name_uses_requested_name(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_git_repo_name", lambda _cwd: "ignored")
    session, is_auto = cli._resolve_new_session_name(requested="myproj", cwd="/tmp/work")
    assert session == "myproj"
    assert is_auto is False


def test_resolve_new_session_name_uses_repo_name_and_sequence(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_git_repo_name", lambda _cwd: "demo-repo")
    existing = {"demo-repo", "demo-repo-2"}
    monkeypatch.setattr(cli, "session_exists", lambda s: s in existing)

    session, is_auto = cli._resolve_new_session_name(requested=None, cwd="/tmp/work")
    assert session == "demo-repo-3"
    assert is_auto is True


def test_resolve_new_session_name_falls_back_to_ai_team(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_git_repo_name", lambda _cwd: None)
    monkeypatch.setattr(cli, "session_exists", lambda s: s == "ai-team")

    session, is_auto = cli._resolve_new_session_name(requested=None, cwd="/tmp/work")
    assert session == "ai-team-2"
    assert is_auto is True
