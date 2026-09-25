# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interaction D: triald names a zone set, mousewheeld arms it for the trial.

Against a fake client, so it runs without a wheel; `contracts/e2e-tests` runs
the same class against a real mousewheeld. mousewheeld-client is in the serve
extra, like every other wire dependency here.
"""

from __future__ import annotations

import pytest

mousewheeld_client = pytest.importorskip(
    "mousewheeld_client", reason="mousewheeld-client is in the serve extra"
)

from triald.api.mousewheel_zone_arming import MousewheelZoneArming  # noqa: E402
from triald.executor import ExecutorError  # noqa: E402


class FakeWheel:
    def __init__(self, refuse: bool = False) -> None:
        self.calls: list[tuple] = []
        self.refuse = refuse

    def arm(self, zone_set, *, origin, label):
        if self.refuse:
            raise mousewheeld_client.DaemonRefusedTheRequest(
                "not_found", "no_such_zone_set", f"no zone set named {zone_set}"
            )
        self.calls.append(("arm", zone_set, origin, label))

    def disarm(self):
        self.calls.append(("disarm",))


def test_a_named_zone_set_is_armed_from_where_the_wheel_is_labelled_with_the_trial():
    wheel = FakeWheel()
    MousewheelZoneArming("rig", client=wheel).arm_for_trial(42, "goal")
    assert wheel.calls == [("arm", "goal", mousewheeld_client.ArmOrigin.CURRENT, "trial 42")]


def test_a_trial_type_with_no_zone_set_disarms_rather_than_inheriting_the_last():
    wheel = FakeWheel()
    MousewheelZoneArming("rig", client=wheel).arm_for_trial(43, "")
    assert wheel.calls == [("disarm",)]


def test_a_refusal_is_an_executor_error_naming_the_set_and_the_trial():
    arming = MousewheelZoneArming("rig-3.local", client=FakeWheel(refuse=True))
    with pytest.raises(ExecutorError, match=r"'goal' for trial 7"):
        arming.arm_for_trial(7, "goal")
