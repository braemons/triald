# SPDX-License-Identifier: AGPL-3.0-or-later
"""Protobuf's JSON mapping, with this API's settings pinned in one place.

The types are generated from `proto/triald/v1/`, and their JSON is the wire:
the console panels are served as written with no build step, `curl` has to
work at three in the morning, and MATLAB has `webread` and nothing else. So the
mapping is the serialisation format rather than a sideline, and its options are
part of the interface rather than details.

**They are not the same options in every language, which is the trap.** Rust's
`pbjson` strips an enum's prefix by default and Python's `json_format` does not;
Python omits a field at its default and so does Rust until told otherwise. Two
clients generated from one `.proto` can therefore disagree about the same byte.
mousewheeld pins the same three settings in `tools/protogen`, and
`tests/test_wire_json.py` here holds this side to them by printing the bytes.

Nothing outside `triald.api` imports this or the generated types. They are the
shapes on the wire; `triald.api.convert` is the seam, and `triald.state` and its
neighbours are what the daemon thinks in.
"""

from __future__ import annotations

from typing import TypeVar

from google.protobuf import json_format
from google.protobuf.message import Message

M = TypeVar("M", bound=Message)


def to_json(message: Message) -> str:
    """One wire message, as the bytes a client will read."""
    return json_format.MessageToJson(
        message,
        # **Emit a field holding its default.**
        #
        # The mapping omits it, so a session that has not started would answer
        # without a `running` at all and every consumer would read `undefined`
        # at exactly the moment a rig is sitting waiting to be armed. A reading
        # of false is a reading.
        #
        # This does not print an unset `optional` field: there, absence is the
        # value, and `stop_after_trials` absent genuinely means no limit.
        always_print_fields_with_no_presence=True,
        # Names come from `json_name` in the `.proto`, which is where the
        # family's rule that a quantity spells its unit survives contact with
        # camelCase. Not `preserving_proto_field_name`: that would make this
        # side right by a Python-only flag while a client generated anywhere
        # else stayed wrong.
        preserving_proto_field_name=False,
        # Enum values by name — `HIT`, not `1`. The names are the `.tdr`
        # taxonomy and are a wire contract in their own right.
        use_integers_for_enums=False,
    )


def from_json(text: str | bytes, message_type: type[M]) -> M:
    """One wire message, parsed, refusing anything it does not understand.

    Unknown fields are an error rather than ignored: a typo in a config
    somebody edits by hand should be a message naming the field, not a setting
    that silently did nothing. `contracts/INTERACTIONS.md` §11 puts it as a
    rule — a request refuses what it does not understand, a response ignores it
    — and this parses requests.

    Raises `json_format.ParseError`, which `triald.api.app` turns into this
    API's own refusal shape.
    """
    return json_format.Parse(text, message_type(), ignore_unknown_fields=False)
