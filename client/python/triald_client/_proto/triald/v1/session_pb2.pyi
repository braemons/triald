import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from triald_client._proto.triald.v1 import common_pb2 as _common_pb2
from triald_client._proto.triald.v1 import config_pb2 as _config_pb2
from triald_client._proto.triald.v1 import policy_pb2 as _policy_pb2
from triald_client._proto.triald.v1 import trial_pb2 as _trial_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ResultCount(_message.Message):
    __slots__ = ("total", "accepted", "remaining", "frame_loss", "by_outcome", "hits", "hit_rate")
    class ByOutcomeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    REMAINING_FIELD_NUMBER: _ClassVar[int]
    FRAME_LOSS_FIELD_NUMBER: _ClassVar[int]
    BY_OUTCOME_FIELD_NUMBER: _ClassVar[int]
    HITS_FIELD_NUMBER: _ClassVar[int]
    HIT_RATE_FIELD_NUMBER: _ClassVar[int]
    total: int
    accepted: int
    remaining: int
    frame_loss: int
    by_outcome: _containers.ScalarMap[str, int]
    hits: int
    hit_rate: float
    def __init__(self, total: _Optional[int] = ..., accepted: _Optional[int] = ..., remaining: _Optional[int] = ..., frame_loss: _Optional[int] = ..., by_outcome: _Optional[_Mapping[str, int]] = ..., hits: _Optional[int] = ..., hit_rate: _Optional[float] = ...) -> None: ...

class CounterRow(_message.Message):
    __slots__ = ("total", "accepted", "remaining", "frame_loss", "by_outcome", "hits", "hit_rate", "index", "trial_type_number", "name", "trials_per_round", "statemachine_graph", "reward_ms", "p_next")
    class ByOutcomeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    REMAINING_FIELD_NUMBER: _ClassVar[int]
    FRAME_LOSS_FIELD_NUMBER: _ClassVar[int]
    BY_OUTCOME_FIELD_NUMBER: _ClassVar[int]
    HITS_FIELD_NUMBER: _ClassVar[int]
    HIT_RATE_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    TRIAL_TYPE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TRIALS_PER_ROUND_FIELD_NUMBER: _ClassVar[int]
    STATEMACHINE_GRAPH_FIELD_NUMBER: _ClassVar[int]
    REWARD_MS_FIELD_NUMBER: _ClassVar[int]
    P_NEXT_FIELD_NUMBER: _ClassVar[int]
    total: int
    accepted: int
    remaining: int
    frame_loss: int
    by_outcome: _containers.ScalarMap[str, int]
    hits: int
    hit_rate: float
    index: int
    trial_type_number: int
    name: str
    trials_per_round: int
    statemachine_graph: str
    reward_ms: int
    p_next: float
    def __init__(self, total: _Optional[int] = ..., accepted: _Optional[int] = ..., remaining: _Optional[int] = ..., frame_loss: _Optional[int] = ..., by_outcome: _Optional[_Mapping[str, int]] = ..., hits: _Optional[int] = ..., hit_rate: _Optional[float] = ..., index: _Optional[int] = ..., trial_type_number: _Optional[int] = ..., name: _Optional[str] = ..., trials_per_round: _Optional[int] = ..., statemachine_graph: _Optional[str] = ..., reward_ms: _Optional[int] = ..., p_next: _Optional[float] = ...) -> None: ...

class SetProgress(_message.Message):
    __slots__ = ("set_name", "accepted_trials", "hits", "all_trials", "criterion", "target", "switch_to", "reached", "fraction")
    SET_NAME_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_TRIALS_FIELD_NUMBER: _ClassVar[int]
    HITS_FIELD_NUMBER: _ClassVar[int]
    ALL_TRIALS_FIELD_NUMBER: _ClassVar[int]
    CRITERION_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    SWITCH_TO_FIELD_NUMBER: _ClassVar[int]
    REACHED_FIELD_NUMBER: _ClassVar[int]
    FRACTION_FIELD_NUMBER: _ClassVar[int]
    set_name: str
    accepted_trials: int
    hits: int
    all_trials: int
    criterion: _common_pb2.TrialCountCriterion
    target: int
    switch_to: str
    reached: int
    fraction: float
    def __init__(self, set_name: _Optional[str] = ..., accepted_trials: _Optional[int] = ..., hits: _Optional[int] = ..., all_trials: _Optional[int] = ..., criterion: _Optional[_Union[_common_pb2.TrialCountCriterion, str]] = ..., target: _Optional[int] = ..., switch_to: _Optional[str] = ..., reached: _Optional[int] = ..., fraction: _Optional[float] = ...) -> None: ...

class SessionState(_message.Message):
    __slots__ = ("running", "armed", "recording", "paused", "stop_reason", "current", "last", "set_name", "set_progress", "rounds_completed", "rounds_configured", "trials_per_round", "trials_remaining", "totals", "counters", "trials_started", "seed", "config", "policy", "policy_errors", "recent")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    ARMED_FIELD_NUMBER: _ClassVar[int]
    RECORDING_FIELD_NUMBER: _ClassVar[int]
    PAUSED_FIELD_NUMBER: _ClassVar[int]
    STOP_REASON_FIELD_NUMBER: _ClassVar[int]
    CURRENT_FIELD_NUMBER: _ClassVar[int]
    LAST_FIELD_NUMBER: _ClassVar[int]
    SET_NAME_FIELD_NUMBER: _ClassVar[int]
    SET_PROGRESS_FIELD_NUMBER: _ClassVar[int]
    ROUNDS_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    ROUNDS_CONFIGURED_FIELD_NUMBER: _ClassVar[int]
    TRIALS_PER_ROUND_FIELD_NUMBER: _ClassVar[int]
    TRIALS_REMAINING_FIELD_NUMBER: _ClassVar[int]
    TOTALS_FIELD_NUMBER: _ClassVar[int]
    COUNTERS_FIELD_NUMBER: _ClassVar[int]
    TRIALS_STARTED_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    POLICY_FIELD_NUMBER: _ClassVar[int]
    POLICY_ERRORS_FIELD_NUMBER: _ClassVar[int]
    RECENT_FIELD_NUMBER: _ClassVar[int]
    running: bool
    armed: bool
    recording: bool
    paused: bool
    stop_reason: str
    current: _trial_pb2.TrialSpec
    last: _trial_pb2.TrialRecord
    set_name: str
    set_progress: SetProgress
    rounds_completed: int
    rounds_configured: int
    trials_per_round: int
    trials_remaining: int
    totals: ResultCount
    counters: _containers.RepeatedCompositeFieldContainer[CounterRow]
    trials_started: int
    seed: int
    config: _config_pb2.SessionConfig
    policy: _policy_pb2.PolicyInfo
    policy_errors: _containers.RepeatedCompositeFieldContainer[_policy_pb2.PolicyError]
    recent: _containers.RepeatedCompositeFieldContainer[_trial_pb2.TrialRecord]
    def __init__(self, running: _Optional[bool] = ..., armed: _Optional[bool] = ..., recording: _Optional[bool] = ..., paused: _Optional[bool] = ..., stop_reason: _Optional[str] = ..., current: _Optional[_Union[_trial_pb2.TrialSpec, _Mapping]] = ..., last: _Optional[_Union[_trial_pb2.TrialRecord, _Mapping]] = ..., set_name: _Optional[str] = ..., set_progress: _Optional[_Union[SetProgress, _Mapping]] = ..., rounds_completed: _Optional[int] = ..., rounds_configured: _Optional[int] = ..., trials_per_round: _Optional[int] = ..., trials_remaining: _Optional[int] = ..., totals: _Optional[_Union[ResultCount, _Mapping]] = ..., counters: _Optional[_Iterable[_Union[CounterRow, _Mapping]]] = ..., trials_started: _Optional[int] = ..., seed: _Optional[int] = ..., config: _Optional[_Union[_config_pb2.SessionConfig, _Mapping]] = ..., policy: _Optional[_Union[_policy_pb2.PolicyInfo, _Mapping]] = ..., policy_errors: _Optional[_Iterable[_Union[_policy_pb2.PolicyError, _Mapping]]] = ..., recent: _Optional[_Iterable[_Union[_trial_pb2.TrialRecord, _Mapping]]] = ...) -> None: ...

class StreamFrame(_message.Message):
    __slots__ = ("sequence", "at", "state")
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    AT_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    sequence: int
    at: _timestamp_pb2.Timestamp
    state: SessionState
    def __init__(self, sequence: _Optional[int] = ..., at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., state: _Optional[_Union[SessionState, _Mapping]] = ...) -> None: ...

class NoteRequest(_message.Message):
    __slots__ = ("text",)
    TEXT_FIELD_NUMBER: _ClassVar[int]
    text: str
    def __init__(self, text: _Optional[str] = ...) -> None: ...
