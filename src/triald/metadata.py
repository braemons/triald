"""Session metadata: who, what, which machines, and anything else a lab needs.

A session record has to be readable years later by somebody who was not there.
That means it carries more than trials: the subject, the experimenter, what kind
of session it was, which devices were involved and what version they were, and
whatever else a particular lab needs to write down.

**triald never interprets custom fields.** :attr:`SessionMetadata.extra`,
:attr:`Device.info` and a :class:`SessionEvent`'s ``data`` are stored and handed
back verbatim, exactly like :attr:`~triald.trialtypes.TrialType.params`. The
daemon has no business knowing what an electrode depth is.

Field names follow **NWB** (Neurodata Without Borders) where NWB has one -
``subject_id``, ``species``, ``sex``, ``experimenter``, ``lab``, ``institution``,
``session_description``. The lab's recordings end up in NWB or beside something
that is, and a mechanical name-for-name conversion is worth more than names we
happen to prefer.

The three-tier grouping is VStim's, from ``VStim::SessionMetadata``, and is kept
because it says what the UI should do with each field: fill it in silently, fill
it in but ask for confirmation, or ask outright.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from typing import Any

#: Largest custom payload accepted, serialised, per event or per metadata block.
#:
#: Somebody will eventually try to put an array in here. A record is an index of
#: what happened, not a place to keep data - refusing early, with a message that
#: says where the data belongs instead, is kinder than a 40 GB trials.jsonl.
MAX_CUSTOM_BYTES = 64 * 1024


class MetadataError(ValueError):
    """A metadata or event payload was rejected."""


def check_payload(data: Any, *, what: str) -> dict[str, Any]:
    """Check that `data` is a JSON-serialisable dict within the size cap.

    Raises:
        MetadataError: if it is not a dict, will not serialise, or is too large.
    """
    if not isinstance(data, dict):
        raise MetadataError(f"{what} must be a dict, got {type(data).__name__}")

    # Strict: no `default=str` fallback. Stringifying would let a set through as
    # "{1, 2, 3}" and read it back as a string - silent corruption of a record
    # nobody will re-check for years. Refusing at the point of the mistake is the
    # whole job. The writer keeps a `default=str` backstop so a session never
    # dies over serialisation, but nothing checked here should ever reach it.
    try:
        encoded = json.dumps(data)
    except (TypeError, ValueError) as exc:
        raise MetadataError(
            f"{what} is not JSON-serialisable: {exc}. Only types that survive a "
            f"round trip are allowed - use an ISO 8601 string for a datetime and "
            f"a list for a set."
        ) from exc

    size = len(encoded.encode("utf-8"))
    if size > MAX_CUSTOM_BYTES:
        raise MetadataError(
            f"{what} is {size} bytes, over the {MAX_CUSTOM_BYTES}-byte limit. "
            f"A session record indexes what happened; bulk data belongs in its "
            f"own file, referenced from here by path."
        )
    return data


@dataclasses.dataclass(slots=True)
class Subject:
    """Who was in the rig. Field names follow NWB's ``Subject``."""

    subject_id: str = ""
    species: str = ""
    sex: str = ""
    """NWB convention: 'M', 'F', 'U' (unknown) or 'O' (other)."""

    age: str = ""
    """ISO 8601 duration, as NWB expects - 'P90D' for 90 days."""

    genotype: str = ""
    strain: str = ""
    description: str = ""

    weight_g: float | None = None
    """Weight at the start of the session. VStim's ``subjectWeightG``."""

    extra: dict[str, Any] = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        return {k: v for k, v in d.items() if v not in ("", None, {})}


@dataclasses.dataclass(slots=True)
class Device:
    """One thing that took part in the session.

    Every daemon and instrument that touched the session should appear here, so
    the record says what produced it without anybody having to remember. A rig
    typically registers vstimd, the behaviour microcontroller, the DAQ card, the
    eye tracker and the acquisition system.

    `info` is free-form and never interpreted - firmware hashes, display modes,
    sampling rates, serial numbers.
    """

    name: str
    role: str = ""
    """What it did: 'stimulus', 'behaviour', 'acquisition', 'eye', 'reward'."""

    version: str = ""
    host: str = ""
    serial: str = ""
    info: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        check_payload(self.info, what=f"device {self.name!r} info")

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(slots=True)
class SessionMetadata:
    """Everything about a session that is not a trial.

    Grouped as VStim groups it, because the grouping tells the UI what to do:

    * **automatic** - filled in by the daemon; never prompted for.
    * **automatic with review** - filled in from the rig config, shown for
      confirmation, because a stale experimenter name is worse than a blank one.
    * **manual** - asked for outright.
    """

    # -- automatic --------------------------------------------------------------
    session_id: str = ""
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None
    host: str = ""
    software: dict[str, str] = dataclasses.field(default_factory=dict)
    """Name and version of triald and anything else that produced this record."""

    devices: list[Device] = dataclasses.field(default_factory=list)

    # -- automatic with review --------------------------------------------------
    experimenter: str = ""
    lab: str = ""
    institution: str = ""
    subject: Subject = dataclasses.field(default_factory=Subject)

    # -- manual -----------------------------------------------------------------
    session_type: str = ""
    """'training', 'recording', 'testing' - whatever the lab distinguishes."""

    session_description: str = ""
    experiment_description: str = ""
    keywords: list[str] = dataclasses.field(default_factory=list)
    notes: str = ""

    has_electrophysiology: bool = False
    has_imaging: bool = False
    has_eye_data: bool = False
    has_video: bool = False
    has_other_data: bool = False
    """VStim's has* flags: what else was recorded alongside, for finding sessions
    later without opening every one of them."""

    total_reward_ml: float | None = None

    # -- anything else ----------------------------------------------------------
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)
    """Whatever this lab needs that triald has never heard of.

    Namespace your keys - ``{"bremen": {"electrode_depth_um": 1420}}`` - so a
    field triald adds later cannot collide with one of yours.
    """

    def __post_init__(self) -> None:
        check_payload(self.extra, what="session metadata extra")

    def add_device(self, device: Device) -> None:
        self.devices.append(device)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "host": self.host,
            "software": self.software,
            "devices": [d.as_dict() for d in self.devices],
            "experimenter": self.experimenter,
            "lab": self.lab,
            "institution": self.institution,
            "subject": self.subject.as_dict(),
            "session_type": self.session_type,
            "session_description": self.session_description,
            "experiment_description": self.experiment_description,
            "keywords": self.keywords,
            "notes": self.notes,
            "has_electrophysiology": self.has_electrophysiology,
            "has_imaging": self.has_imaging,
            "has_eye_data": self.has_eye_data,
            "has_video": self.has_video,
            "has_other_data": self.has_other_data,
            "total_reward_ml": self.total_reward_ml,
            "extra": self.extra,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class SessionEvent:
    """Something that happened during a session which is not a trial.

    An experimenter's note, a manual reward, a device reporting its state, a
    correction to metadata entered at the start. Appended to ``events.jsonl``
    with the trial it happened during, so it can be lined up with the trial
    stream afterwards.

    **Corrections are appended, never applied in place.** Realising at trial 50
    that the subject ID was typed wrong produces a new event, not a rewritten
    manifest - the same reason a trial record is never edited.
    """

    kind: str
    """What sort of event. Bare names are triald's own - ``note``, ``reward``,
    ``metadata``, ``device``, ``policy``, ``error``. Namespace anything of your
    own with a dot: ``bremen.electrode_depth``."""

    data: dict[str, Any] = dataclasses.field(default_factory=dict)
    source: str = "experimenter"
    """Who said so: ``experimenter``, ``triald``, ``vstimd``, ``mcu``, a client."""

    at: dt.datetime | None = None
    trial_number: int | None = None
    """The trial in flight when this happened, or None between trials."""

    def __post_init__(self) -> None:
        if not self.kind:
            raise MetadataError("an event needs a kind")
        check_payload(self.data, what=f"event {self.kind!r} data")

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat() if self.at else None,
            "trial_number": self.trial_number,
            "kind": self.kind,
            "source": self.source,
            "data": self.data,
        }
