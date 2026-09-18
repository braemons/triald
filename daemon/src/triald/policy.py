# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scripting surface: a policy is a Python class with optional hooks.

The declarative config covers what VStim's dialogs cover - orderings, weights,
accept flags, round counts, switch rules. A policy is for everything past that:
staircases, adaptive difficulty, curricula, stopping criteria nobody anticipated.

Every hook is optional. Omit one and the declarative behaviour stands, which
means the smallest useful policy overrides a single method.

The rule that shapes this whole module: **a scripting bug must never end a
session.** There is an animal in the rig. Every hook is invoked through
:func:`safe_call`, which catches everything, logs it with a full traceback, and
returns a fallback so the session carries on with the declarative behaviour.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
import traceback
import types
from pathlib import Path
from typing import Any

from triald.state import SessionState, TrialRecord

log = logging.getLogger(__name__)


class Policy:
    """Base class for trial selection logic. Subclass and override what you need.

    Hooks are called in the order they appear here. A hook that raises is logged
    and ignored; the daemon falls back to its declarative behaviour for that
    trial and keeps going.
    """

    def on_session_start(self, state: SessionState) -> None:
        """Called once, after the session is armed and before the first trial."""

    def select_trial(self, state: SessionState) -> str | int | None:
        """Choose the next trial type.

        Returns:
            A trial type name, an index into the active set, or None to let the
            declarative ordering make the choice. Returning None is the normal
            thing for a policy that only wants :meth:`on_outcome`.
        """
        return None

    def on_outcome(self, record: TrialRecord, state: SessionState) -> None:
        """Called after every trial, accepted or not.

        Check ``record.accepted`` before updating anything that should only move
        on trials that counted - a staircase that steps on refused trials will
        drift in ways that are very hard to see afterwards.
        """

    def on_set_switch(self, from_set: str, to_set: str, state: SessionState) -> None:
        """Called after the active trial type set has been switched."""

    def should_stop(self, state: SessionState) -> bool:
        """Return True to end the session after the trial that just finished."""
        return False

    def snapshot(self) -> dict[str, object] | None:
        """State to attach to each trial record and show in the web UI.

        Anything JSON-serialisable. This is what makes an adaptive session
        reconstructable afterwards, so return the variables that actually drove
        the decisions - a staircase's level and run length, not a summary.
        """
        return None


class DeclarativePolicy(Policy):
    """The do-nothing policy. Every decision falls to the declarative config."""


def safe_call[T](
    fn: Any,
    *args: Any,
    fallback: T,
    hook: str,
    on_error: Any = None,
    **kwargs: Any,
) -> T:
    """Call a policy hook, surviving anything it does.

    Args:
        fallback: returned when the hook raises.
        hook: name used in the log message and handed to `on_error`.
        on_error: optional ``(hook, exception, formatted_traceback) -> None``,
            used to surface the failure in the web UI against the trial that
            raised it.

    Returns:
        The hook's return value, or `fallback` if it raised.
    """
    try:
        return fn(*args, **kwargs)  # type: ignore[no-any-return]
    except Exception as exc:
        formatted = traceback.format_exc()
        log.error(
            "policy hook %s raised %s: %s - falling back to the declarative "
            "behaviour for this trial\n%s",
            hook,
            type(exc).__name__,
            exc,
            formatted,
        )
        if on_error is not None:
            try:
                on_error(hook, exc, formatted)
            except Exception:
                log.exception("policy error reporter raised; ignoring")
        return fallback


class PolicyError(Exception):
    """A policy could not be loaded, or failed its checks."""


def load_policy(source: str | Path) -> Policy:
    """Import `source` and instantiate the single :class:`Policy` subclass in it.

    Args:
        source: path to a ``.py`` file.

    Raises:
        PolicyError: if the file will not import, or does not contain exactly one
            concrete Policy subclass.
    """
    path = Path(source).resolve()
    if not path.is_file():
        raise PolicyError(f"no such policy file: {path}")

    spec = importlib.util.spec_from_file_location(f"triald_policy_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise PolicyError(f"{path} is not importable as a Python module")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PolicyError(f"{path} raised on import: {type(exc).__name__}: {exc}") from exc

    found = _policy_classes(module)
    if not found:
        raise PolicyError(
            f"{path} defines no Policy subclass. A policy is a class that "
            f"inherits from triald.Policy."
        )
    if len(found) > 1:
        names = ", ".join(c.__name__ for c in found)
        raise PolicyError(f"{path} defines more than one Policy subclass: {names}")

    try:
        return found[0]()
    except Exception as exc:
        raise PolicyError(
            f"{found[0].__name__} could not be constructed: {type(exc).__name__}: {exc}"
        ) from exc


def _policy_classes(module: types.ModuleType) -> list[type[Policy]]:
    return [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, Policy)
        and obj is not Policy
        and obj is not DeclarativePolicy
        and obj.__module__ == module.__name__
    ]
