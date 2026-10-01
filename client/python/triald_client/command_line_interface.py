# SPDX-License-Identifier: AGPL-3.0-or-later
"""`trialctl` — one rig's trial control, from a terminal.

Named without the `d`: the daemon is `triald` and it installs a binary of that
name on every rig this would also be installed on. Two different programs
answering to one word is a bug report about the wrong one.

**This is a view onto the client and holds no logic of its own.** Anything it
can work out, `TrialdClient` could have; anything it decided would be a second
opinion about a session that already has one.

It follows the family's rules for a `<name>ctl` (`contracts/DAEMON_LAYOUT.md`):
`--rig`, then `$BRAEMONS_RIG`, then localhost; JSON on stdout, one compact
object per line for a stream; a refusal as one JSON object on stderr, with an
exit status a script can switch on and a sentence a person can read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
import typing
from collections.abc import Sequence
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from enum import Enum, IntEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import DEFAULT_PORT, TrialdClient
from .api_types import ConfigPatch, OutcomeReport, SimSettings, TrialOutcome, TrialTypeSet
from .daemon_refusals import DaemonRefusedTheRequest

RIG_ENVIRONMENT_VARIABLE = "BRAEMONS_RIG"


class ExitStatus(IntEnum):
    """The same numbers from every `<name>ctl` in the family."""

    OK = 0
    FAILURE = 1
    USAGE = 2
    UNAVAILABLE = 3
    TIMED_OUT = 4
    REFUSED = 5
    NOT_FOUND = 6
    INTERRUPTED = 130


_EXIT_STATUS_FOR_REFUSAL = {
    "unavailable": ExitStatus.UNAVAILABLE,
    "deadline_exceeded": ExitStatus.TIMED_OUT,
    "not_found": ExitStatus.NOT_FOUND,
}


def _plain(value):
    """A dataclass tree as JSON.

    Enums print as their short name — the one this client speaks — except
    `TrialOutcome`, which is an `IntEnum` and prints as the `.tdr` code, since
    that is the number every analysis script already reads.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {name: _plain(field) for name, field in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _build(kind, value):
    """JSON into one of the client's types: the inverse of `_plain`.

    An `IntEnum` takes its name as well as its number, so `hit` and `1` are the
    same outcome; anything else is the value `_plain` prints. A field the type
    does not have is refused rather than dropped, because a misspelt setting
    that silently does nothing is the worst way for a patch to fail.
    """
    origin = typing.get_origin(kind)
    if origin in (typing.Union, types.UnionType):
        if value is None:
            return None
        (inner,) = [one for one in typing.get_args(kind) if one is not type(None)]
        return _build(inner, value)
    if origin is tuple:
        return tuple(_build(typing.get_args(kind)[0], one) for one in value)
    if isinstance(kind, type) and is_dataclass(kind):
        if not isinstance(value, dict):
            raise ValueError(f"{kind.__name__} is a JSON object, not {value!r}")
        unknown = sorted(set(value) - {one.name for one in fields(kind)})
        if unknown:
            raise ValueError(f"{kind.__name__} has no field {', '.join(unknown)}")
        hints = typing.get_type_hints(kind)
        return kind(**{name: _build(hints[name], one) for name, one in value.items()})
    if isinstance(kind, type) and issubclass(kind, IntEnum) and isinstance(value, str):
        try:
            return kind[value.upper()]
        except KeyError:
            names = ", ".join(one.name.lower() for one in kind)
            raise ValueError(f"{value!r} is not a {kind.__name__}: one of {names}") from None
    if isinstance(kind, type) and issubclass(kind, Enum):
        return kind(value)
    return value


def _fields(pairs: Sequence[str]) -> dict:
    """`NAME=VALUE` arguments as a JSON object. The value is JSON when it parses
    as JSON and text when it does not, so `note=late again` needs no quotes and
    `rounds=3` is a number."""
    parsed = {}
    for pair in pairs:
        name, separator, text = pair.partition("=")
        if not separator:
            raise ValueError(f"expected NAME=VALUE, not {pair!r}")
        try:
            parsed[name] = json.loads(text)
        except json.JSONDecodeError:
            parsed[name] = text
    return parsed


def _read(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def _print(value) -> None:
    print(json.dumps(_plain(value), indent=2))


def _print_line(value) -> None:
    """One compact object per line, flushed: this is what somebody leaves
    running in a second terminal, and a state that arrives four kilobytes late
    is not a state."""
    print(json.dumps(_plain(value)), flush=True)


def _fail(error: str, detail: str, exit_status: ExitStatus, **more) -> int:
    print(json.dumps({"error": error, "detail": detail, **more}), file=sys.stderr)
    return exit_status


def _client_version() -> str:
    try:
        return version("triald-client")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trialctl",
        description="Talk to a triald. Everything prints JSON, so it pipes into jq.",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"trialctl {_client_version()}"
    )
    parser.add_argument(
        "--rig",
        default=os.environ.get(RIG_ENVIRONMENT_VARIABLE) or "localhost",
        help=f"host, or host:port (default ${RIG_ENVIRONMENT_VARIABLE}, then localhost; "
        f"port {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="how long to wait for the daemon to answer (default %(default)s)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("state", help="everything true right now")
    session_config = commands.add_parser("session-config", help="the declarative settings")
    session_config_actions = session_config.add_subparsers(dest="action")
    session_config_set = session_config_actions.add_parser(
        "set", help="change some of them, e.g. rounds=3 ordering=ascending"
    )
    session_config_set.add_argument("fields", nargs="+", metavar="NAME=VALUE")

    sets = commands.add_parser("sets", help="the sets, their rules and the chain")
    set_actions = sets.add_subparsers(dest="action", required=True)
    set_actions.add_parser("list", help="every set, which is active, and the chain")
    set_get = set_actions.add_parser("get", help="one set")
    set_get.add_argument("name")
    set_remove = set_actions.add_parser("rm", help="delete a set that is not loaded")
    set_remove.add_argument("name")
    set_load = set_actions.add_parser("load", help="make a set active")
    set_load.add_argument("name")
    set_put = set_actions.add_parser("put", help="add or replace a set from a JSON file")
    set_put.add_argument("file", help="the set as `sets get` prints it, or - for stdin")
    set_put.add_argument("--name", help="store a copy under this name; default: its own")
    commands.add_parser("counters", help="the per-trial-type tally of the active set")
    reset = commands.add_parser("reset", help="start the rounds again, or clear the counters")
    reset.add_argument("what", choices=["rounds", "counters"])

    watch = commands.add_parser("watch", help="follow the state stream until interrupted")
    watch.add_argument(
        "--summary",
        action="store_true",
        help="one line per frame instead of the whole state",
    )

    commands.add_parser("arm", help="build a session and start it")

    trial = commands.add_parser("trial", help="run one trial by hand: next, report, cancel")
    trial_actions = trial.add_subparsers(dest="action", required=True)
    trial_actions.add_parser("next", help="select the next trial and print its spec")
    trial_report = trial_actions.add_parser("report", help="report how a trial ended")
    trial_report.add_argument("trial_number", type=int, help="from the spec `trial next` gave")
    trial_report.add_argument("outcome", help="a name (hit, early, ...) or its .tdr code")
    trial_report.add_argument(
        "fields", nargs="*", metavar="NAME=VALUE", help="the rest, e.g. reaction_time_ms=412"
    )
    trial_cancel = trial_actions.add_parser("cancel", help="abandon the trial in flight")
    trial_cancel.add_argument("reason", nargs="?", default="cancelled from trialctl")

    stop = commands.add_parser("stop", help="end the session")
    stop.add_argument("reason", nargs="?", default="stopped from trialctl")

    recording = commands.add_parser("recording", help="start, pause, resume or stop recording")
    recording.add_argument("action", choices=["start", "pause", "resume", "stop"])

    note = commands.add_parser("note", help="append a note to the event stream")
    note.add_argument("text")

    policy = commands.add_parser("policy", help="read, check, load or clear the policy")
    policy_actions = policy.add_subparsers(dest="action", required=True)
    policy_actions.add_parser("show", help="what is loaded")
    policy_check = policy_actions.add_parser("check", help="import and smoke-run a .py")
    policy_check.add_argument("path", type=Path)
    policy_load = policy_actions.add_parser("load", help="check a .py, then load it")
    policy_load.add_argument("path", type=Path)
    policy_actions.add_parser("clear", help="back to the declarative behaviour")

    step = commands.add_parser("step", help="run trials against the simulated subject")
    step.add_argument("trials", nargs="?", type=int, default=1)

    sim = commands.add_parser("sim", help="the simulated subject's dials, and free-running it")
    sim_actions = sim.add_subparsers(dest="action", required=True)
    sim_actions.add_parser("show", help="the dials")
    sim_set = sim_actions.add_parser("set", help="move some dials, e.g. hit_rate=0.9")
    sim_set.add_argument("fields", nargs="+", metavar="NAME=VALUE")
    free_run = sim_actions.add_parser("free-run", help="step the subject on a timer")
    free_run.add_argument("switch", choices=["status", "start", "stop"])
    free_run.add_argument("--interval-ms", type=int, default=250)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)

    try:
        with TrialdClient(arguments.rig) as rig:
            # Before anything else, so that "nothing is listening" and "that is
            # the browser's port" are one clear sentence rather than whatever
            # gRPC says about HTTP/2 frames.
            rig.wait_until_ready(timeout_s=arguments.timeout)
            return _run(rig, arguments)
    except DaemonRefusedTheRequest as refusal:
        # To stderr, and JSON, so that a script can read the refusal and a
        # person can read the sentence. The kind is what a script switches on.
        return _fail(
            refusal.error,
            refusal.detail,
            _EXIT_STATUS_FOR_REFUSAL.get(refusal.status, ExitStatus.REFUSED),
            status=refusal.status,
        )
    except TimeoutError as problem:
        return _fail("unavailable", str(problem), ExitStatus.UNAVAILABLE)
    except OSError as problem:
        return _fail("unreadable", str(problem), ExitStatus.FAILURE)
    except (ValueError, TypeError) as problem:
        return _fail("usage", str(problem), ExitStatus.USAGE)
    except (KeyboardInterrupt, BrokenPipeError):
        return ExitStatus.INTERRUPTED


def _run(rig: TrialdClient, arguments) -> int:
    match arguments.command:
        case "state":
            _print(rig.read_state())
        case "session-config" if arguments.action == "set":
            _print(rig.update_config(_build(ConfigPatch, _fields(arguments.fields))))
        case "session-config":
            _print(rig.read_config())
        case "sets":
            return _sets(rig, arguments)
        case "counters":
            _print(rig.read_state().counters)
        case "reset":
            _print(rig.reset_rounds() if arguments.what == "rounds" else rig.reset_counters())
        case "trial":
            return _trial(rig, arguments)
        case "watch":
            _watch(rig, summary=arguments.summary)
        case "arm":
            _print(rig.arm())
        case "stop":
            _print(rig.stop(arguments.reason))
        case "recording":
            _print(
                {
                    "start": rig.start_recording,
                    "pause": rig.pause_recording,
                    "resume": rig.resume_recording,
                    "stop": rig.stop_recording,
                }[arguments.action]()
            )
        case "note":
            rig.note(arguments.text)
        case "policy":
            return _policy(rig, arguments)
        case "step":
            _print(rig.step(arguments.trials))
        case "sim":
            _sim(rig, arguments)
    return ExitStatus.OK


def _sets(rig: TrialdClient, arguments) -> int:
    match arguments.action:
        case "list":
            _print(rig.read_sets())
        case "get":
            named = [one for one in rig.read_sets().sets if one.name == arguments.name]
            if not named:
                return _fail(
                    "no_such_set", f"no set named {arguments.name!r}", ExitStatus.NOT_FOUND
                )
            _print(named[0])
        case "rm":
            _print(rig.delete_set(arguments.name))
        case "load":
            _print(rig.load_set(arguments.name))
        case "put":
            plain = json.loads(_read(arguments.file))
            if arguments.name:
                # A copy under a new name, not a mismatch: the daemon refuses a
                # set stored under a name it does not carry.
                plain["name"] = arguments.name
            _print(rig.write_set(_build(TrialTypeSet, plain)))
    return ExitStatus.OK


def _trial(rig: TrialdClient, arguments) -> int:
    match arguments.action:
        case "next":
            _print(rig.next_trial())
        case "report":
            report = _build(
                OutcomeReport,
                {**_fields(arguments.fields), "outcome": _outcome(arguments.outcome)},
            )
            _print(rig.report_outcome(arguments.trial_number, report))
        case "cancel":
            _print(rig.cancel_trial(arguments.reason))
    return ExitStatus.OK


def _outcome(text: str) -> TrialOutcome:
    """`hit`, `HIT` or `1`: the name a person types or the code a `.tdr` holds."""
    return _build(TrialOutcome, int(text) if text.lstrip("-").isdigit() else text)


def _sim(rig: TrialdClient, arguments) -> None:
    match arguments.action:
        case "show":
            _print(rig.read_sim())
        case "set":
            # Over what is there now, so that naming one dial leaves the others
            # where somebody put them rather than back at their defaults.
            current = _plain(rig.read_sim())
            _print(rig.write_sim(_build(SimSettings, {**current, **_fields(arguments.fields)})))
        case "free-run":
            if arguments.switch == "status":
                _print(rig.read_free_run())
            else:
                running = arguments.switch == "start"
                _print(rig.write_free_run(running, arguments.interval_ms))


def _policy(rig: TrialdClient, arguments) -> int:
    match arguments.action:
        case "show":
            _print(rig.read_policy(with_source=True))
        case "check":
            # The source text, never the path: the rig is not this machine, and
            # a filename cannot answer "which version ran on Tuesday".
            result = rig.check_policy(arguments.path.stem, arguments.path.read_text())
            _print(result)
            return ExitStatus.OK if result.ok else ExitStatus.REFUSED
        case "load":
            _print(rig.load_policy(arguments.path.stem, arguments.path.read_text()))
        case "clear":
            _print(rig.clear_policy())
    return 0


def _watch(rig: TrialdClient, *, summary: bool) -> None:
    """Follow the stream until Ctrl-C.

    Line-buffered on purpose: this is what somebody leaves running in a second
    terminal, and a state that arrives four kilobytes late is not a state.
    """
    for state in rig.watch_states():
        if summary:
            trial = state.current.trial_number if state.current else "-"
            totals = state.totals
            print(
                f"{'running' if state.running else 'idle':8} "
                f"set {state.set_name:16} trial {trial:>6} "
                f"{totals.accepted if totals else 0} accepted"
                f" / {totals.total if totals else 0} reported",
                flush=True,
            )
        else:
            _print_line(state)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
