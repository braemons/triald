"""``triald`` on the command line.

Three things matter here and none of them is the daemon itself:

* ``triald sim`` runs a whole session against a synthetic subject with no
  hardware and no vstimd. It is the fastest way to find out that a policy does
  something stupid on trial 300.
* ``triald policy check`` imports a policy and smoke-runs it, so a broken one is
  caught before it is anywhere near an animal.
* ``triald replay`` reruns a recorded session's outcomes through a different
  policy and shows which decisions changed.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

from triald.behaviour import SimulatedBehaviourSource
from triald.policy import DeclarativePolicy, Policy, PolicyError, load_policy
from triald.recording import read_session
from triald.runner import run_session
from triald.selection import Ordering
from triald.session import Session, SessionConfig, SessionError
from triald.state import TrialRecord
from triald.trialtypes import TrialType, TrialTypeSet, TrialTypeStore


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    if args.command == "sim":
        return _cmd_sim(args)
    if args.command == "policy":
        return _cmd_policy(args)
    if args.command == "replay":
        return _cmd_replay(args)

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triald", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    sim = sub.add_parser("sim", help="run a session against a simulated subject")
    sim.add_argument("--config", type=Path, help="session config JSON")
    sim.add_argument("--policy", type=Path, help="policy .py to load")
    sim.add_argument("--trials", type=int, default=200, help="trial ceiling")
    sim.add_argument("--hit-rate", type=float, default=0.75)
    sim.add_argument("--seed", type=int, default=None)
    sim.add_argument("--json", action="store_true", help="summary as JSON")
    sim.add_argument("--trace", action="store_true", help="print every trial")

    policy = sub.add_parser("policy", help="work with policy files")
    policy_sub = policy.add_subparsers(dest="policy_command")
    check = policy_sub.add_parser("check", help="import and smoke-run a policy")
    check.add_argument("path", type=Path)
    check.add_argument("--trials", type=int, default=50)
    check.add_argument(
        "--trial-types",
        help=(
            "comma-separated trial type names to check against, for a policy "
            "that selects by name (e.g. 'contrast_0,contrast_1,contrast_2'). "
            "Without it the built-in demo experiment is used, and a policy that "
            "names types it does not have will fail."
        ),
    )

    replay = sub.add_parser("replay", help="rerun a recorded session")
    replay.add_argument("session", type=Path, help="recorded session directory")
    replay.add_argument("--policy", type=Path, help="policy to replay it through")

    return parser


# -- sim -----------------------------------------------------------------------


def _cmd_sim(args: argparse.Namespace) -> int:
    store, config = _load_config(args.config) if args.config else _demo_experiment()
    if args.seed is not None:
        config.seed = args.seed

    policy: Policy = DeclarativePolicy()
    if args.policy:
        try:
            policy = load_policy(args.policy)
        except PolicyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    session = Session(store, config, policy=policy)
    subject = SimulatedBehaviourSource(hit_rate=args.hit_rate, rng=random.Random(config.seed))

    try:
        session.arm()
    except SessionError as exc:
        print(f"error: the session will not arm: {exc}", file=sys.stderr)
        return 1

    summary = run_session(
        session,
        subject,
        max_trials=args.trials,
        on_trial=_print_trial if args.trace else None,
    )

    if args.json:
        print(json.dumps(summary.as_dict(), indent=2))
    else:
        _print_summary(session, summary)

    for error in session.policy_errors:
        print(f"\npolicy error in {error['hook']} at trial {error['trial_number']}:")
        print(f"  {error['error']}")

    return 1 if session.policy_errors else 0


def _print_trial(record: TrialRecord) -> None:
    mark = "+" if record.accepted else "-"
    print(
        f"{mark} trial {record.spec.trial_number:>5}  "
        f"{record.spec.set_name:<12} {record.spec.trial_type_name:<16} "
        f"{record.report.outcome.name}"
    )


def _print_summary(session: Session, summary: Any) -> None:
    state = session.state()
    print(f"\n  trials run      {summary.trials}")
    print(f"  accepted        {summary.accepted}")
    print(f"  hits            {summary.hits}")
    rate = state.totals.hit_rate
    print(f"  hit rate        {rate:.1%}" if rate is not None else "  hit rate        -")
    print(f"  final set       {summary.final_set}")
    print(f"  stopped because {summary.stop_reason}")
    print(f"  seed            {state.seed}")

    print("\n  outcomes")
    for outcome, n in sorted(state.totals.by_outcome.items()):
        print(f"    {outcome.name:<24} {n:>6}")

    print("\n  per trial type")
    for i, counter in enumerate(state.per_trial_type):
        if counter.total == 0:
            continue
        name = state.trial_type_names[i] if i < len(state.trial_type_names) else ""
        print(
            f"    [{i}] {name:<16} total {counter.total:>5}  "
            f"accepted {counter.accepted:>5}  hits {counter.hits:>5}"
        )


# -- policy check ---------------------------------------------------------------


def _cmd_policy(args: argparse.Namespace) -> int:
    if args.policy_command != "check":
        print("error: use 'triald policy check <path>'", file=sys.stderr)
        return 2

    try:
        policy = load_policy(args.path)
    except PolicyError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1

    print(f"ok    imported {type(policy).__name__} from {args.path}")

    if args.trial_types:
        names = [n.strip() for n in args.trial_types.split(",") if n.strip()]
        store, config = _ad_hoc_experiment(names)
        print(f"ok    checking against {len(names)} trial types")
    else:
        store, config = _demo_experiment()
    session = Session(store, config, policy=policy)
    subject = SimulatedBehaviourSource(rng=random.Random(0))

    try:
        session.arm()
        run_session(session, subject, max_trials=args.trials)
    except (SessionError, Exception) as exc:
        print(f"FAIL  the smoke run raised {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if session.policy_errors:
        print(f"FAIL  {len(session.policy_errors)} policy error(s) in the smoke run:")
        for error in session.policy_errors:
            print(f"        {error['hook']}: {error['error']}")
        return 1

    print(f"ok    {args.trials} simulated trials with no policy errors")
    return 0


# -- replay ---------------------------------------------------------------------


def _cmd_replay(args: argparse.Namespace) -> int:
    trials = read_session(args.session)
    if not trials:
        print(f"error: no trials in {args.session}", file=sys.stderr)
        return 1

    print(f"{len(trials)} trials recorded in {args.session}")
    if not args.policy:
        counts: dict[str, int] = {}
        for t in trials:
            name = str(t["outcome"]["name"])
            counts[name] = counts.get(name, 0) + 1
        for name, n in sorted(counts.items()):
            print(f"  {name:<24} {n:>6}")
        return 0

    print("replaying a recorded session through a new policy is not implemented yet")
    print("(see dev/PLAN.md - it needs the recorded config to rebuild the store)")
    return 2


# -- a small experiment to try things against ------------------------------------


def _demo_experiment() -> tuple[TrialTypeStore, SessionConfig]:
    """A three-set training sequence that walks itself.

    fixation -> one_line -> one_half_cyc, each handing over after enough hits.
    This is the shape a training session actually runs in, and the reason the
    switch rules exist: until now somebody had to load the next set by hand at
    the end of every block.
    """
    from triald.counters import TrialCountCriterion
    from triald.trialtypes import SwitchRule

    def handover(target: str, hits: int) -> SwitchRule:
        return SwitchRule(
            enabled=True,
            criterion=TrialCountCriterion.HITS,
            count=hits,
            target=target,
        )

    store = TrialTypeStore(
        [
            TrialTypeSet(
                name="fixation",
                trial_types=[
                    TrialType(name="fix_only", trials_per_round=4, reward_ms=120),
                    TrialType(name="fix_dim", trials_per_round=2, reward_ms=140),
                ],
                switch_rule=handover("one_line", 20),
            ),
            TrialTypeSet(
                name="one_line",
                trial_types=[
                    TrialType(name="line_0deg", trials_per_round=3, reward_ms=160),
                    TrialType(name="line_90deg", trials_per_round=3, reward_ms=160),
                ],
                switch_rule=handover("one_half_cyc", 20),
            ),
            TrialTypeSet(
                name="one_half_cyc",
                trial_types=[
                    TrialType(name="cyc_left", trials_per_round=3, reward_ms=180),
                    TrialType(name="cyc_right", trials_per_round=3, reward_ms=180),
                ],
            ),
        ]
    )
    config = SessionConfig(
        initial_set="fixation",
        ordering=Ordering.RANDOM_IN_ROUND,
        rounds=5,
        seed=0,
        # These three stages are genuinely different experiments whose trial
        # type 0 have nothing to do with each other, which is exactly what the
        # extension is for: each set then keeps its own counts. With it off the
        # sets would share one counter bank indexed by trial type number, which
        # is right when they run the same conditions and share names (#538) -
        # and misleading here, where they do not.
        extend_trial_type_number=True,
    )
    return store, config


def _ad_hoc_experiment(names: list[str]) -> tuple[TrialTypeStore, SessionConfig]:
    """One set holding exactly `names`, evenly weighted.

    What ``policy check --trial-types`` uses: a policy that selects by name can
    only be smoke-run against a set that has those names in it.
    """
    store = TrialTypeStore(
        [
            TrialTypeSet(
                name="check",
                trial_types=[
                    TrialType(name=n, trials_per_round=1, reward_ms=100) for n in names
                ],
            )
        ]
    )
    return store, SessionConfig(initial_set="check", rounds=1000, seed=0)


def _load_config(path: Path) -> tuple[TrialTypeStore, SessionConfig]:
    raise SystemExit(
        f"loading a session config from {path} is not implemented yet - see "
        f"dev/PLAN.md. Run 'triald sim' with no --config for the demo experiment."
    )


if __name__ == "__main__":
    raise SystemExit(main())
