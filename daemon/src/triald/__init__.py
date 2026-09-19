# SPDX-License-Identifier: AGPL-3.0-or-later
"""triald - a scriptable trial control daemon for brain research.

Decides what trial runs next, records what happened, and lets an experimenter
write the decision in Python. Part of the braemons family, alongside vstimd,
which owns everything with a frame deadline.

The public surface is what a policy needs:

    from triald import Policy, TrialOutcome

    class Alternating(Policy):
        def select_trial(self, state):
            return "b" if state.last and state.last.spec.trial_type_name == "a" else "a"
"""

from __future__ import annotations

# **The generated types are private and stay private.** They are the shapes on
# the wire; `triald.api.convert` is the seam, and nothing a person imports from
# `triald` is a protobuf message.
#
# They live in `_proto/`, and they reach each other by an absolute path inside
# it — `from triald._proto.triald.v1 import common_pb2`. `make proto` rewrites
# protoc's own `from triald.v1 import ...` into that, because protoc roots an
# import at the proto path and `triald` is this package.
#
# This line used to extend `__path__` instead, so that `triald.v1` resolved at
# runtime. It worked, and no static checker could follow it — every import site
# carried a suppression saying so. It also could not work at all once a
# second proto package arrived: `braemons/v1/trial_outcome.proto` is the
# taxonomy both this daemon and statemachined speak, and `from braemons.v1
# import ...` has no package here to hang off.
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

#: Read from the installed distribution rather than written here, because the
#: version comes from the git tag and is stamped into pyproject.toml at build
#: time (packaging/scripts/git-version.sh). A literal here would be a second
#: place to forget. `0.0.0+unknown` means this is a checkout that was never
#: installed -- which is what `python -c "import triald"` from src/ is.
try:
    __version__ = _installed_version("triald")
except PackageNotFoundError:  # pragma: no cover - only outside an install
    __version__ = "0.0.0+unknown"

from triald.adaptive import Staircase, WeightedUpDown
from triald.behaviour import (
    BehaviourSource,
    BehaviourSourceError,
    SimulatedBehaviourSource,
    TrialParameters,
)
from triald.counters import ResultCount, TrialCountCriterion
from triald.metadata import (
    Device,
    MetadataError,
    SessionEvent,
    SessionMetadata,
    Subject,
)
from triald.outcomes import (
    AcceptancePolicy,
    FrameLoss,
    Manipulandum,
    OutcomeReport,
    TrialOutcome,
)
from triald.policy import DeclarativePolicy, Policy, PolicyError, load_policy
from triald.recording import (
    RecordingError,
    SessionRecorder,
    read_events,
    read_manifest,
    read_session,
)
from triald.selection import Ordering, TrialBag
from triald.session import Session, SessionConfig, SessionError
from triald.state import SessionState, SetProgress, TrialRecord, TrialSpec
from triald.trialtypes import (
    SwitchRule,
    TrialType,
    TrialTypeSet,
    TrialTypeStore,
)

__all__ = [
    "AcceptancePolicy",
    "BehaviourSource",
    "BehaviourSourceError",
    "DeclarativePolicy",
    "Device",
    "FrameLoss",
    "Manipulandum",
    "MetadataError",
    "Ordering",
    "OutcomeReport",
    "Policy",
    "PolicyError",
    "RecordingError",
    "ResultCount",
    "Session",
    "SessionConfig",
    "SessionError",
    "SessionEvent",
    "SessionMetadata",
    "SessionRecorder",
    "SessionState",
    "SetProgress",
    "SimulatedBehaviourSource",
    "Staircase",
    "Subject",
    "SwitchRule",
    "TrialBag",
    "TrialCountCriterion",
    "TrialOutcome",
    "TrialParameters",
    "TrialRecord",
    "TrialSpec",
    "TrialType",
    "TrialTypeSet",
    "TrialTypeStore",
    "WeightedUpDown",
    "__version__",
    "load_policy",
    "read_events",
    "read_manifest",
    "read_session",
]
