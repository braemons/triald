# SPDX-License-Identifier: AGPL-3.0-or-later
"""The session's declarative settings, and a partial update to them."""

from __future__ import annotations

from typing import Any

from triald.counters import TrialCountCriterion
from triald.outcomes import AcceptancePolicy
from triald.selection import Ordering
from triald.session import SessionConfig
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    common_pb2,
    config_pb2,
)

#: The acceptance flags, in the order the message declares them. Derived from
#: the message rather than written twice: `tools/check_outcomes.py` already
#: holds these names to the outcome enum, so a new outcome cannot reach here
#: without a flag, and a flag cannot arrive here without an outcome.
ACCEPTANCE_FLAGS = tuple(field.name for field in config_pb2.Acceptance.DESCRIPTOR.fields)

#: What each wire enum value means to the daemon. `UNSPECIFIED` is not in the
#: tables: it means the field was omitted, and what an omitted criterion means
#: depends on where it was omitted, so each caller says.
_CRITERIA = {
    common_pb2.TRIAL_COUNT_CRITERION_ACCEPTED_TRIALS: TrialCountCriterion.ACCEPTED_TRIALS,
    common_pb2.TRIAL_COUNT_CRITERION_HITS: TrialCountCriterion.HITS,
    common_pb2.TRIAL_COUNT_CRITERION_ALL_TRIALS: TrialCountCriterion.ALL_TRIALS,
}
_ORDERINGS = {
    common_pb2.ORDERING_RANDOM_IN_ROUND: Ordering.RANDOM_IN_ROUND,
    common_pb2.ORDERING_RANDOM_IN_EXPERIMENT: Ordering.RANDOM_IN_EXPERIMENT,
    common_pb2.ORDERING_ASCENDING: Ordering.ASCENDING,
    common_pb2.ORDERING_DESCENDING: Ordering.DESCENDING,
    common_pb2.ORDERING_RANDOM_WITH_REPLACEMENT: Ordering.RANDOM_WITH_REPLACEMENT,
}
_CRITERIA_TO_WIRE = {value: key for key, value in _CRITERIA.items()}
_ORDERINGS_TO_WIRE = {value: key for key, value in _ORDERINGS.items()}


class Refused(ValueError):
    """A message this daemon understood the shape of but not the meaning of."""


def criterion_from_wire(
    value: int, *, when_omitted: TrialCountCriterion
) -> TrialCountCriterion:
    if value == common_pb2.TRIAL_COUNT_CRITERION_UNSPECIFIED:
        return when_omitted
    try:
        return _CRITERIA[value]
    except KeyError:
        raise Refused(f"{value} is not a criterion this daemon knows") from None


def ordering_from_wire(value: int) -> Ordering:
    if value == common_pb2.ORDERING_UNSPECIFIED:
        return Ordering.RANDOM_IN_ROUND
    try:
        return _ORDERINGS[value]
    except KeyError:
        raise Refused(f"{value} is not an ordering this daemon knows") from None


def acceptance_to_wire(policy: AcceptancePolicy) -> config_pb2.Acceptance:
    return config_pb2.Acceptance(**{name: getattr(policy, name) for name in ACCEPTANCE_FLAGS})


def acceptance_from_wire(message: config_pb2.Acceptance) -> AcceptancePolicy:
    """Absent means "leave it at the default", which is what `AcceptancePolicy`
    already holds — so only the flags actually present are passed."""
    return AcceptancePolicy(
        **{name: getattr(message, name) for name in ACCEPTANCE_FLAGS if message.HasField(name)}
    )


def session_config_to_wire(config: SessionConfig) -> config_pb2.SessionConfig:
    message = config_pb2.SessionConfig(
        initial_set=config.initial_set,
        ordering=_ORDERINGS_TO_WIRE[config.ordering],
        rounds=config.rounds,
        avoid_repeat=config.avoid_repeat,
        acceptance=acceptance_to_wire(config.acceptance),
        trial_cap_ms=config.trial_cap_ms,
        stop_when_rounds_done=config.stop_when_rounds_done,
        stop_criterion=_CRITERIA_TO_WIRE[config.stop_criterion],
        extend_trial_type_number=config.extend_trial_type_number,
    )
    if config.stop_after_trials is not None:
        message.stop_after_trials = config.stop_after_trials
    if config.seed is not None:
        message.seed = config.seed
    return message


def config_patch_from_wire(message: config_pb2.ConfigPatch) -> dict[str, Any]:
    """The fields actually present, ready for `Session.reconfigure`.

    `stop_after_trials` is the exception the shape cannot express: absent means
    "leave it alone", and on the config it patches absent *is* a value meaning
    "no limit" — so zero is how a caller clears it.
    """
    changes: dict[str, Any] = {}
    if message.HasField("ordering"):
        changes["ordering"] = ordering_from_wire(message.ordering)
    if message.HasField("rounds"):
        changes["rounds"] = message.rounds
    if message.HasField("avoid_repeat"):
        changes["avoid_repeat"] = message.avoid_repeat
    if message.HasField("acceptance"):
        changes["acceptance"] = acceptance_from_wire(message.acceptance)
    if message.HasField("trial_cap_ms"):
        changes["trial_cap_ms"] = message.trial_cap_ms
    if message.HasField("stop_when_rounds_done"):
        changes["stop_when_rounds_done"] = message.stop_when_rounds_done
    if message.HasField("stop_after_trials"):
        changes["stop_after_trials"] = message.stop_after_trials or None
    if message.HasField("stop_criterion"):
        changes["stop_criterion"] = criterion_from_wire(
            message.stop_criterion, when_omitted=TrialCountCriterion.ACCEPTED_TRIALS
        )
    if message.HasField("initial_set"):
        changes["initial_set"] = message.initial_set
    if message.HasField("extend_trial_type_number"):
        changes["extend_trial_type_number"] = message.extend_trial_type_number
    if message.HasField("seed"):
        changes["seed"] = message.seed
    return changes


def config_update_to_wire(update) -> config_pb2.ConfigUpdateResult:
    """What a config change did, and the config it left behind."""
    return config_pb2.ConfigUpdateResult(
        changed=list(update.changed),
        bag_rebuilt=update.bag_rebuilt,
        config=session_config_to_wire(update.config),
    )
