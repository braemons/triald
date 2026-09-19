from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Manipulandum(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NONE: _ClassVar[Manipulandum]
    LEVER: _ClassVar[Manipulandum]
    TOUCH_BAR: _ClassVar[Manipulandum]
    BUTTON: _ClassVar[Manipulandum]
    JOYSTICK: _ClassVar[Manipulandum]
    GAMEPAD: _ClassVar[Manipulandum]
    SERIAL: _ClassVar[Manipulandum]
    SIMULATED: _ClassVar[Manipulandum]

class TrialCountCriterion(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TRIAL_COUNT_CRITERION_UNSPECIFIED: _ClassVar[TrialCountCriterion]
    TRIAL_COUNT_CRITERION_ACCEPTED_TRIALS: _ClassVar[TrialCountCriterion]
    TRIAL_COUNT_CRITERION_HITS: _ClassVar[TrialCountCriterion]
    TRIAL_COUNT_CRITERION_ALL_TRIALS: _ClassVar[TrialCountCriterion]

class Ordering(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ORDERING_UNSPECIFIED: _ClassVar[Ordering]
    ORDERING_RANDOM_IN_ROUND: _ClassVar[Ordering]
    ORDERING_RANDOM_IN_EXPERIMENT: _ClassVar[Ordering]
    ORDERING_ASCENDING: _ClassVar[Ordering]
    ORDERING_DESCENDING: _ClassVar[Ordering]
    ORDERING_RANDOM_WITH_REPLACEMENT: _ClassVar[Ordering]
NONE: Manipulandum
LEVER: Manipulandum
TOUCH_BAR: Manipulandum
BUTTON: Manipulandum
JOYSTICK: Manipulandum
GAMEPAD: Manipulandum
SERIAL: Manipulandum
SIMULATED: Manipulandum
TRIAL_COUNT_CRITERION_UNSPECIFIED: TrialCountCriterion
TRIAL_COUNT_CRITERION_ACCEPTED_TRIALS: TrialCountCriterion
TRIAL_COUNT_CRITERION_HITS: TrialCountCriterion
TRIAL_COUNT_CRITERION_ALL_TRIALS: TrialCountCriterion
ORDERING_UNSPECIFIED: Ordering
ORDERING_RANDOM_IN_ROUND: Ordering
ORDERING_RANDOM_IN_EXPERIMENT: Ordering
ORDERING_ASCENDING: Ordering
ORDERING_DESCENDING: Ordering
ORDERING_RANDOM_WITH_REPLACEMENT: Ordering

class Error(_message.Message):
    __slots__ = ("error", "detail")
    ERROR_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    error: str
    detail: str
    def __init__(self, error: _Optional[str] = ..., detail: _Optional[str] = ...) -> None: ...

class Ok(_message.Message):
    __slots__ = ("ok",)
    OK_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    def __init__(self, ok: _Optional[bool] = ...) -> None: ...
