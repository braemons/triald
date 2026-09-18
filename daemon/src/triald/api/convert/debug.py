# SPDX-License-Identifier: AGPL-3.0-or-later
"""The synthetic subject, and the timer that steps it."""

from __future__ import annotations

import dataclasses

from triald.v1 import debug_pb2


def sim_settings_to_wire(settings) -> debug_pb2.SimSettings:
    return debug_pb2.SimSettings(**dataclasses.asdict(settings))


def sim_settings_from_wire(message: debug_pb2.SimSettings, settings_type):
    """A whole settings block, not a patch: the panel sends every slider.

    `settings_type` is passed in rather than imported so this module does not
    depend on the service layer that owns it — the seam points one way.
    """
    return settings_type(
        hit_rate=message.hit_rate,
        not_started_rate=message.not_started_rate,
        eye_error_rate=message.eye_error_rate,
        early_rate=message.early_rate,
        frame_loss_rate=message.frame_loss_rate,
        imprecise_fixation_rate=message.imprecise_fixation_rate,
        hit_rate_by_type=dict(message.hit_rate_by_type),
    )


def free_run_to_wire(status) -> debug_pb2.FreeRunStatus:
    return debug_pb2.FreeRunStatus(running=status.running, interval_ms=status.interval_ms)
