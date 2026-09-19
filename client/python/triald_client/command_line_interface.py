# SPDX-License-Identifier: AGPL-3.0-or-later
"""`trialctl` — one rig's trial control, from a terminal.

Named without the `d`: the daemon is `triald` and it installs a binary of that
name on every rig this would also be installed on. Two different programs
answering to one word is a bug report about the wrong one.

**This is a view onto the client and holds no logic of its own.** Anything it
can work out, `TrialdClient` could have; anything it decided would be a second
opinion about a session that already has one.

Everything prints JSON, so it pipes into `jq`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from . import DEFAULT_PORT, TrialdClient
from .daemon_refusals import DaemonRefusedTheRequest


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trialctl",
        description="Talk to a triald. Everything prints JSON, so it pipes into jq.",
    )
    parser.add_argument(
        "--rig",
        default="localhost",
        help=f"host, or host:port (default {DEFAULT_PORT}, one above the browser's)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("state", help="everything true right now")
    commands.add_parser("config", help="the declarative settings")
    commands.add_parser("sets", help="the sets, their rules and the chain")
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

    load = commands.add_parser("load", help="make a set active")
    load.add_argument("name")

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

    arguments = parser.parse_args(argv)

    try:
        with TrialdClient(arguments.rig) as rig:
            # Before anything else, so that "nothing is listening" and "that is
            # the browser's port" are one clear sentence rather than whatever
            # gRPC says about HTTP/2 frames.
            rig.wait_until_ready(timeout_s=5)
            return _run(rig, arguments)
    except DaemonRefusedTheRequest as refusal:
        # To stderr, and JSON, so that a script can read the refusal and a
        # person can read the sentence. The kind is what a script switches on.
        print(
            json.dumps(
                {"error": refusal.error, "detail": refusal.detail, "status": refusal.status}
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130


def _run(rig: TrialdClient, arguments) -> int:
    match arguments.command:
        case "state":
            _print(rig.read_state())
        case "config":
            _print(rig.read_config())
        case "sets":
            _print(rig.read_sets())
        case "counters":
            _print(rig.read_state().counters)
        case "watch":
            _watch(rig, summary=arguments.summary)
        case "arm":
            _print(rig.arm())
        case "stop":
            _print(rig.stop(arguments.reason))
        case "load":
            _print(rig.load_set(arguments.name))
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
    return 0


def _policy(rig: TrialdClient, arguments) -> int:
    match arguments.action:
        case "show":
            _print(rig.read_policy(with_source=True))
        case "check":
            # The source text, never the path: the rig is not this machine, and
            # a filename cannot answer "which version ran on Tuesday".
            result = rig.check_policy(arguments.path.stem, arguments.path.read_text())
            _print(result)
            return 0 if result.ok else 1
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
            _print(state)
            sys.stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
