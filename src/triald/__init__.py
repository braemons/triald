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
    "load_policy",
    "read_events",
    "read_manifest",
    "read_session",
]
