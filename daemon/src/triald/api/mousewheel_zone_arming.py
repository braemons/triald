# SPDX-License-Identifier: AGPL-3.0-or-later
"""Arming a trial's zone set on mousewheeld: interaction D.

mousewheeld decides zones on its own board, in the scan that sees the count,
and puts a hit on a TTL line into statemachined and the DAQ — the fast bus. What
it needs from triald is only *which* set to arm before a trial, and that is
this file: one call per trial, and the trial type's `mousewheel_zone_set` is
the whole of what crosses (`contracts/INTERACTIONS.md` §3 D-F).

**The trial type still does not cross.** mousewheeld is told a set's name, an
origin — here, always the current position — and a label, `trial 42`, which
it stores and hands back unread. It stays trial-blind, as statemachined does.

**A refusal is a configuration error, not a trial that ran unzoned.** A name
mousewheeld does not have, a set that does not compile against its calibration,
a board that never confirmed: all of them raise, so a session stops on the
first trial rather than recording an evening of trials that never had the zones
they claim.

What is not here yet is E, the path back: mousewheeld has no marks or path ring
(its `dev/PLAN.md` M2), so there is nothing to read into the record.
"""

from __future__ import annotations

from typing import Any

from mousewheeld_client import ArmOrigin, DaemonRefusedTheRequest, MousewheeldClient

from triald.executor import ExecutorError

__all__ = ["MousewheelZoneArming"]


class MousewheelZoneArming:
    """One mousewheeld, addressed by `host` or `host:port` (8083 by default)."""

    def __init__(self, address: str, client: MousewheeldClient | Any = None) -> None:
        self.address = address
        self.wheel = client if client is not None else MousewheeldClient(address)

    def arm_for_trial(self, trial_id: int, zone_set: str) -> None:
        """Arm `zone_set` for trial `trial_id`, measured from where the wheel is
        now. An empty name disarms, so a trial type with no zones does not run
        under the previous trial's."""
        try:
            if zone_set:
                self.wheel.arm(zone_set, origin=ArmOrigin.CURRENT, label=f"trial {trial_id}")
            else:
                self.wheel.disarm()
        except DaemonRefusedTheRequest as refusal:
            raise ExecutorError(
                f"mousewheeld at {self.address} refused zone set {zone_set!r} "
                f"for trial {trial_id}: {refusal}"
            ) from refusal

    def close(self) -> None:
        self.wheel.close()
