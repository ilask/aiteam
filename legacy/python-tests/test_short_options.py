from __future__ import annotations

import argparse

import tmux_ai_team.cli as cli


def _iter_parsers(parser: argparse.ArgumentParser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield sub


def _subparser(root: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    for action in root._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise AssertionError(f"subparser not found: {name}")


def _short_opt_for_dest(parser: argparse.ArgumentParser, dest: str) -> str:
    for action in parser._actions:
        if action.dest != dest:
            continue
        for opt in action.option_strings:
            if opt.startswith("-") and not opt.startswith("--"):
                return opt
    raise AssertionError(f"short option not found for dest: {dest}")


def test_every_long_option_has_short_alias() -> None:
    parser = cli.build_parser()
    for p in _iter_parsers(parser):
        seen_short = set()
        for action in p._actions:
            long_opts = [o for o in action.option_strings if o.startswith("--")]
            if not long_opts:
                continue
            short_opts = [o for o in action.option_strings if o.startswith("-") and not o.startswith("--")]
            assert short_opts, f"{p.prog}: missing short for {long_opts}"

            # Strict rule: short must be the initial derived from long flag.
            expected = cli._strict_short_flag(long_opts[0])
            assert short_opts[0] == expected, f"{p.prog}: expected {expected} for {long_opts[0]}, got {short_opts[0]}"

            # Strict rule: no short collisions inside the same parser.
            assert short_opts[0] not in seen_short, f"{p.prog}: duplicate short option {short_opts[0]}"
            seen_short.add(short_opts[0])


def test_start_accepts_short_options() -> None:
    parser = cli.build_parser()
    start = _subparser(parser, "start")

    short_main = _short_opt_for_dest(start, "main")
    short_attach = _short_opt_for_dest(start, "attach")
    short_session = _short_opt_for_dest(start, "session")

    args = parser.parse_args(["start", short_main, "codex", short_attach, short_session, "demo"])
    assert args.main == "codex"
    assert args.attach is True
    assert args.session == "demo"


def test_send_accepts_short_options_in_mutually_exclusive_group() -> None:
    parser = cli.build_parser()
    send = _subparser(parser, "send")

    short_session = _short_opt_for_dest(send, "session")
    short_to = _short_opt_for_dest(send, "to")
    short_text = _short_opt_for_dest(send, "text")

    args = parser.parse_args(["send", short_session, "s", short_to, "p", short_text, "hello"])
    assert args.session == "s"
    assert args.to == "p"
    assert args.text == "hello"


def test_send_session_is_optional() -> None:
    parser = cli.build_parser()
    send = _subparser(parser, "send")

    short_to = _short_opt_for_dest(send, "to")
    short_text = _short_opt_for_dest(send, "text")

    args = parser.parse_args(["send", short_to, "p", short_text, "hello"])
    assert args.session is None
    assert args.to == "p"
    assert args.text == "hello"


def test_collision_raises_error_immediately() -> None:
    parser = argparse.ArgumentParser(prog="x")
    cli._enable_auto_short_options(parser)
    parser.add_argument("--alpha")
    try:
        parser.add_argument("--another")
        raise AssertionError("Expected ValueError for short option collision")
    except ValueError as e:
        assert "Short option collision" in str(e)
