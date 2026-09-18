# SPDX-License-Identifier: AGPL-3.0-or-later
"""Joining a display's frame-numbered facts to a trial.

Integers in, a verdict out. The stimulus server has never heard of a trial and
never will; what is tested here is the side that does the joining, which is the
only side that knows where a trial's boundaries are.
"""

from __future__ import annotations

from triald.stimulus import FrameLossAccount


def test_a_clean_window_reports_nothing():
    account = FrameLossAccount(first_frame=1000)
    window = account.close(last_frame=1120)

    assert window.lost_frames == 0
    assert window.had_loss is False
    assert window.as_report() is None


def test_a_loss_inside_the_window_is_reported_with_the_frame_it_happened_at():
    account = FrameLossAccount(first_frame=1000)
    account.note_loss(frame=1042, count=1)
    window = account.close(last_frame=1120)

    assert window.lost_frames == 1
    assert window.first_loss_at == 1042
    assert window.as_report().frame == 1042


def test_the_first_loss_is_the_one_recorded():
    # The record answers "where did this trial first go wrong", which is the
    # question somebody asks when looking at one; a later loss adds nothing.
    account = FrameLossAccount(first_frame=1000)
    account.note_loss(frame=1042)
    account.note_loss(frame=1099, count=3)
    window = account.close(last_frame=1120)

    assert window.first_loss_at == 1042
    assert window.lost_frames == 4


def test_a_loss_before_the_window_belongs_to_whatever_came_before():
    # Attributing it here is the same mislabelling a late outcome would be, and
    # the inter-trial interval is exactly where a rig drops frames.
    account = FrameLossAccount(first_frame=1000)
    account.note_loss(frame=980)
    window = account.close(last_frame=1120)

    assert window.lost_frames == 0
    assert window.as_report() is None


def test_a_loss_at_the_first_frame_is_inside_the_window():
    # The boundary is inclusive: the frame the trial was configured at is the
    # first frame it could have been rendered on.
    account = FrameLossAccount(first_frame=1000)
    account.note_loss(frame=1000)
    assert account.close(last_frame=1010).lost_frames == 1


# -- uncertainty, which is the interesting half ---------------------------------


def test_an_uncertain_window_is_reported_as_lost():
    """The asymmetry that matters. Reporting 'no loss' for a trial nobody was
    watching is a false negative, and a false negative here keeps a trial in a
    dataset that should have been refused. A false positive costs one trial."""
    account = FrameLossAccount(first_frame=1000)
    account.note_uncertainty("the subscription dropped events")
    window = account.close(last_frame=1120)

    assert window.lost_frames == 0
    assert window.uncertain is True
    assert window.had_loss is True
    assert window.as_report() is not None


def test_an_uncertain_window_with_no_observed_loss_names_the_windows_start():
    # There is no frame to point at, so the report points at the trial's first
    # frame rather than inventing one.
    account = FrameLossAccount(first_frame=1000)
    account.note_uncertainty()
    assert account.close(last_frame=1120).as_report().frame == 1000


def test_uncertainty_is_one_way():
    # Nothing later can restore confidence in a window that was not fully
    # observed, so a clean run of events after a gap must not clear it.
    account = FrameLossAccount(first_frame=1000)
    account.note_uncertainty()
    account.note_loss(frame=1001)
    assert account.close(last_frame=1010).uncertain is True


def test_a_frame_counter_going_backwards_is_uncertainty_not_an_error():
    # It happens exactly once: the display restarted. The trial ran; what is
    # unknown is whether it was rendered cleanly.
    account = FrameLossAccount(first_frame=1000)
    window = account.close(last_frame=4)

    assert window.uncertain is True
    assert window.had_loss is True


def test_a_zero_or_negative_count_changes_nothing():
    account = FrameLossAccount(first_frame=1000)
    account.note_loss(frame=1010, count=0)
    assert account.close(last_frame=1020).lost_frames == 0


# -- the shape of the report ----------------------------------------------------


def test_the_interval_is_zero_because_the_display_has_no_idea_what_one_is():
    # Intervals are the within-trial state machine's notion. What the display
    # knows is which *frame*, and that is what is recorded.
    account = FrameLossAccount(first_frame=1000)
    account.note_loss(frame=1042)
    assert account.close(last_frame=1120).as_report().interval == 0
