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
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum, IntEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import DEFAULT_PORT, TrialdClient
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
    commands.add_parser("session-config", help="the declarative settings")

    sets = commands.add_parser("sets", help="the sets, their rules and the chain")
    set_actions = sets.add_subparsers(dest="action", required=True)
    set_actions.add_parser("list", help="every set, which is active, and the chain")
    set_get = set_actions.add_parser("get", help="one set")
    set_get.add_argument("name")
    set_remove = set_actions.add_parser("rm", help="delete a set that is not loaded")
    set_remove.add_argument("name")
    set_load = set_actions.add_parser("load", help="make a set active")
    set_load.add_argument("name")
    commands.add_parser("counters", help="the per-trial-type tally of the active set")

    watch = commands.add_parser("watch", help="follow the state stream until interrupted")
    watch.add_argument(
        "--summary",
        action="store_true",
        help="one line per frame instead of the whole state",
    )

    commands.add_parser("arm", help="build a session and start it")
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
    except (KeyboardInterrupt, BrokenPipeError):
        return ExitStatus.INTERRUPTED


def _run(rig: TrialdClient, arguments) -> int:
    match arguments.command:
        case "state":
            _print(rig.read_state())
        case "session-config":
            _print(rig.read_config())
        case "sets":
            return _sets(rig, arguments)
        case "counters":
            _print(rig.read_state().counters)
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
    return ExitStatus.OK


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
