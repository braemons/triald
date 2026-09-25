# SPDX-License-Identifier: AGPL-3.0-or-later
"""The session config as a file: one experiment's settings and its trial type sets.

`contracts/DAEMON_LAYOUT.md` gives every daemon two configurations, and this is
the second one — the experiment, not the box. The rig config's
`session_config` names one of these, and so does `--session-config`. JSON,
because a person edits it and reviews it in a diff; not protobuf, because it is
a document rather than a message on a wire, and a `.proto` describing it would
be a second description that loses the day it disagrees.

```json
{
  "$schema": "https://github.com/braemons/triald/.../session-config.schema.json",
  "settings": {"initial_set": "fixation", "ordering": "random_in_round", ...},
  "sets": [
    {"name": "fixation",
     "trial_types": [{"name": "fix_only", "trials_per_round": 4, "reward_ms": 120}],
     "switch_rule": {"enabled": true, "criterion": "hits", "count": 20,
                     "target": "one_line"}}
  ]
}
```

**Strict, and it says where.** An unknown key is refused rather than ignored —
`reward_msec` silently doing nothing is a session run with the wrong reward —
and every refusal names the path to the value it is about, `sets[1].
trial_types[0].reward_ms`, because the person reading it has the file open and
nothing else. Omitted keys take the dataclasses' own defaults, so a file says
only what differs.

Written by hand rather than with pydantic because triald's core imports
nothing (`CLAUDE.md`), and the file has five shapes. The JSON Schema committed
beside it, `docs/reference/session-config.schema.json`, is for an editor; a test
holds its property names to this reader's.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from pathlib import Path
from typing import Any

from triald.counters import TrialCountCriterion
from triald.outcomes import AcceptancePolicy
from triald.selection import Ordering
from triald.session import SessionConfig
from triald.trialtypes import SwitchRule, TrialType, TrialTypeSet, TrialTypeStore

#: Top-level keys. `$schema` is allowed so an editor can be pointed at the
#: schema, and is otherwise ignored.
DOCUMENT_KEYS = frozenset({"$schema", "settings", "sets"})


class SessionConfigFileError(ValueError):
    """The file is not a session config this daemon can run, and why."""


def read_session_config_file(path: Path) -> tuple[TrialTypeStore, SessionConfig]:
    """The experiment in `path`, validated. Raises :class:`SessionConfigFileError`."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise SessionConfigFileError(f"{path}: {error.strerror or error}") from None
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise SessionConfigFileError(
            f"{path}: not JSON: {error.msg} at line {error.lineno}, column {error.colno}"
        ) from None
    try:
        return session_config_from_document(document)
    except SessionConfigFileError as error:
        raise SessionConfigFileError(f"{path}: {error}") from None


def write_session_config_file(path: Path, store: TrialTypeStore, config: SessionConfig) -> None:
    """Write the experiment as a file :func:`read_session_config_file` reads back."""
    text = json.dumps(session_config_to_document(store, config), indent=2) + "\n"
    Path(path).write_text(text, encoding="utf-8")


# -- reading ---------------------------------------------------------------------


def session_config_from_document(document: Any) -> tuple[TrialTypeStore, SessionConfig]:
    """The experiment in an already-parsed document."""
    fields = _object(
        document, "the document", DOCUMENT_KEYS, required=frozenset({"settings", "sets"})
    )

    sets_value = fields["sets"]
    if not isinstance(sets_value, list) or not sets_value:
        raise SessionConfigFileError("sets: a list of at least one trial type set")
    store = TrialTypeStore()
    for index, value in enumerate(sets_value):
        where = f"sets[{index}]"
        trial_type_set = _trial_type_set(value, where)
        if trial_type_set.name in store:
            raise SessionConfigFileError(
                f"{where}.name: {trial_type_set.name!r} is the name of an earlier set too"
            )
        store.add(trial_type_set)

    config = _settings(fields["settings"], "settings")
    if config.initial_set not in store:
        raise SessionConfigFileError(
            f"settings.initial_set: no set named {config.initial_set!r} in sets"
        )
    # The same check arming makes, made now: a chain that points at a set that
    # is not there should stop the daemon at startup, not a session overnight.
    for trial_type_set in store.sets():
        problem = store.validate_switch_chain(trial_type_set.name)
        if problem is not None:
            raise SessionConfigFileError(f"sets: {problem}")
    return store, config


def _settings(value: Any, where: str) -> SessionConfig:
    known = {f.name for f in dataclasses.fields(SessionConfig)}
    fields = _object(value, where, known, required=frozenset({"initial_set"}))
    arguments: dict[str, Any] = {}
    for name, given in fields.items():
        at = f"{where}.{name}"
        if name == "initial_set":
            arguments[name] = _string(given, at, allow_empty=False)
        elif name == "ordering":
            arguments[name] = _enum(Ordering, given, at)
        elif name == "stop_criterion":
            arguments[name] = _enum(TrialCountCriterion, given, at)
        elif name == "acceptance":
            arguments[name] = _acceptance(given, at)
        elif name in ("avoid_repeat", "stop_when_rounds_done", "extend_trial_type_number"):
            arguments[name] = _boolean(given, at)
        elif name in ("rounds", "trial_cap_ms"):
            arguments[name] = _integer(given, at, minimum=0)
        elif name in ("stop_after_trials", "seed"):
            arguments[name] = None if given is None else _integer(given, at, minimum=0)
        else:  # pragma: no cover - a field added to SessionConfig and not here
            raise SessionConfigFileError(f"{at}: this reader does not know the field yet")
    return SessionConfig(**arguments)


def _acceptance(value: Any, where: str) -> AcceptancePolicy:
    known = {f.name for f in dataclasses.fields(AcceptancePolicy)}
    fields = _object(value, where, known)
    return AcceptancePolicy(
        **{name: _boolean(given, f"{where}.{name}") for name, given in fields.items()}
    )


def _trial_type_set(value: Any, where: str) -> TrialTypeSet:
    fields = _object(
        value,
        where,
        {"name", "trial_types", "switch_rule"},
        required=frozenset({"name", "trial_types"}),
    )
    name = _string(fields["name"], f"{where}.name", allow_empty=False)
    types_value = fields["trial_types"]
    if not isinstance(types_value, list):
        raise SessionConfigFileError(f"{where}.trial_types: a list of trial types")
    trial_types = [
        _trial_type(item, f"{where}.trial_types[{index}]")
        for index, item in enumerate(types_value)
    ]
    names = [t.name for t in trial_types]
    for index, type_name in enumerate(names):
        if type_name in names[:index]:
            raise SessionConfigFileError(
                f"{where}.trial_types[{index}].name: {type_name!r} appears twice in this set"
            )
    switch_rule = (
        _switch_rule(fields["switch_rule"], f"{where}.switch_rule")
        if "switch_rule" in fields
        else SwitchRule()
    )
    try:
        return TrialTypeSet(name=name, trial_types=trial_types, switch_rule=switch_rule)
    except ValueError as error:
        raise SessionConfigFileError(f"{where}: {error}") from None


def _trial_type(value: Any, where: str) -> TrialType:
    known = {f.name for f in dataclasses.fields(TrialType)}
    fields = _object(value, where, known, required=frozenset({"name"}))
    arguments: dict[str, Any] = {}
    for name, given in fields.items():
        at = f"{where}.{name}"
        if name == "name":
            arguments[name] = _string(given, at, allow_empty=False)
        elif name in ("statemachine_graph", "mousewheel_zone_set"):
            arguments[name] = _string(given, at)
        elif name in ("trials_per_round", "reward_ms"):
            arguments[name] = _integer(given, at, minimum=0)
        elif name == "params":
            # Never interpreted (CLAUDE.md), so any JSON object is fine.
            if not isinstance(given, dict):
                raise SessionConfigFileError(f"{at}: an object")
            arguments[name] = given
        else:  # pragma: no cover - a field added to TrialType and not here
            raise SessionConfigFileError(f"{at}: this reader does not know the field yet")
    return TrialType(**arguments)


def _switch_rule(value: Any, where: str) -> SwitchRule:
    known = {f.name for f in dataclasses.fields(SwitchRule)}
    fields = _object(value, where, known)
    arguments: dict[str, Any] = {}
    for name, given in fields.items():
        at = f"{where}.{name}"
        if name == "enabled":
            arguments[name] = _boolean(given, at)
        elif name == "criterion":
            arguments[name] = _enum(TrialCountCriterion, given, at)
        elif name == "count":
            arguments[name] = _integer(given, at, minimum=0)
        elif name == "target":
            arguments[name] = None if given is None else _string(given, at, allow_empty=False)
    return SwitchRule(**arguments)


# -- the five shapes a value can have ----------------------------------------------


def _object(
    value: Any,
    where: str,
    known: set[str] | frozenset[str],
    required: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SessionConfigFileError(f"{where}: an object")
    unknown = sorted(set(value) - set(known))
    if unknown:
        raise SessionConfigFileError(
            f"{where}: unknown {'key' if len(unknown) == 1 else 'keys'} "
            f"{', '.join(repr(k) for k in unknown)}; known: {', '.join(sorted(known))}"
        )
    missing = sorted(required - set(value))
    if missing:
        raise SessionConfigFileError(f"{where}: missing {', '.join(repr(k) for k in missing)}")
    return {k: v for k, v in value.items() if k != "$schema"}


def _string(value: Any, where: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise SessionConfigFileError(f"{where}: a {'' if allow_empty else 'non-empty '}string")
    return value


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise SessionConfigFileError(f"{where}: true or false")
    return value


def _integer(value: Any, where: str, *, minimum: int) -> int:
    # bool is an int in Python, and `true` is not a number of trials.
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SessionConfigFileError(f"{where}: an integer, at least {minimum}")
    return value


def _enum[E: enum.Enum](kind: type[E], value: Any, where: str) -> E:
    try:
        return kind(value)
    except ValueError:
        choices = ", ".join(repr(member.value) for member in kind)
        raise SessionConfigFileError(f"{where}: one of {choices}") from None


# -- writing ---------------------------------------------------------------------


def session_config_to_document(store: TrialTypeStore, config: SessionConfig) -> dict[str, Any]:
    """The document :func:`session_config_from_document` reads back to the same thing."""
    return {
        "settings": _plain(dataclasses.asdict(config)),
        "sets": [_plain(dataclasses.asdict(s)) for s in store.sets()],
    }


def _plain(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value
