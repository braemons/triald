# SPDX-License-Identifier: AGPL-3.0-or-later
"""Joining a display's events to a trial, with no display in sight.

The source is a protocol, so these run on lists of made-up events. What is
worth testing is not that ZMQ delivers bytes -- vstimd's own suite does that
against a real socket -- but that the *attribution* is right: that loss inside a
window lands on that trial, that loss outside it lands on nobody, and that a
window nobody fully watched is reported as dirty rather than clean.

That last one is the asymmetry the whole module turns on. A false positive costs
one trial. A false negative keeps a bad trial in the dataset, where it is
invisible.
"""

from __future__ import annotations

import dataclasses
import threading

from triald.api.stimulus_subscriber import TOPICS, StimulusObserver


@dataclasses.dataclass
class Dropped:
    count: int


@dataclasses.dataclass
class FakeEvent:
    frame: int
    topic: str = "frame.dropped"
    missed_before: int = 0
    payload: object = None


def dropped(frame: int, count: int = 1, *, missed_before: int = 0) -> FakeEvent:
    return FakeEvent(frame=frame, missed_before=missed_before, payload=Dropped(count))


class FakeSource:
    """A display that hands over a fixed list of events and then goes quiet."""

    def __init__(self, events: list[object] | None = None) -> None:
        self.events = list(events or [])
        self.closed = False
        self.drained = threading.Event()

    def receive(self, timeout_ms: int | None = None) -> object | None:
        if not self.events:
            self.drained.set()
            return None
        return self.events.pop(0)

    def close(self) -> None:
        self.closed = True


def feed(observer: StimulusObserver, source: FakeSource) -> None:
    """Push everything the source holds through the observer, on this thread.

    The loop runs on a thread of its own in production; driving it directly here
    keeps these tests free of sleeps, which are the usual way a test of a
    background thread becomes a test of a machine's load.
    """
    while source.events:
        event = source.receive()
        if event is not None:
            observer._account_for(event)


# ── What belongs to a trial ───────────────────────────────────────────────────


def test_loss_inside_the_window_belongs_to_the_trial():
    source = FakeSource([dropped(105), dropped(112, count=2)])
    observer = StimulusObserver(source)
    observer.open_window(first_frame=100)
    feed(observer, source)

    window = observer.close_window(last_frame=120)
    assert window is not None
    assert window.lost_frames == 3
    assert window.first_loss_at == 105
    assert window.had_loss


def test_loss_before_the_window_belongs_to_nobody():
    """Attributing a previous trial's loss here is the same mislabelling a late
    outcome would be."""
    source = FakeSource([dropped(40)])
    observer = StimulusObserver(source)
    observer.open_window(first_frame=100)
    feed(observer, source)

    window = observer.close_window(last_frame=120)
    assert window is not None
    assert window.lost_frames == 0
    assert not window.had_loss


def test_events_outside_any_window_are_read_and_dropped():
    """Reading between trials is not waste: it is what keeps the subscription
    from falling behind, and falling behind loses events silently."""
    source = FakeSource([dropped(10), dropped(20)])
    observer = StimulusObserver(source)
    feed(observer, source)  # no window open

    assert observer.close_window(last_frame=30) is None
    assert observer.last_frame_seen == 20, "still read, so the socket stays drained"


def test_a_clean_trial_reports_nothing_to_modify_the_outcome():
    source = FakeSource([])
    observer = StimulusObserver(source)
    observer.open_window(first_frame=200)
    window = observer.close_window(last_frame=260)

    assert window is not None
    assert not window.had_loss
    assert window.as_report() is None


# ── What is unknown is not what is clean ──────────────────────────────────────


def test_a_gap_in_the_stream_makes_the_window_uncertain():
    """The subscriber missed events it will never see again, so it cannot call
    the window clean -- and uncertain reports as loss."""
    source = FakeSource([dropped(105, missed_before=4)])
    observer = StimulusObserver(source)
    observer.open_window(first_frame=100)
    feed(observer, source)

    window = observer.close_window(last_frame=120)
    assert window is not None
    assert window.uncertain
    assert window.had_loss, "a window nobody fully watched is not a clean window"


def test_a_gap_makes_a_window_dirty_even_with_no_loss_reported():
    """The case the asymmetry exists for: nothing was *seen* to be lost."""
    source = FakeSource([FakeEvent(frame=105, topic="server.started", missed_before=2)])
    observer = StimulusObserver(source)
    observer.open_window(first_frame=100)
    feed(observer, source)

    window = observer.close_window(last_frame=120)
    assert window is not None
    assert window.lost_frames == 0
    assert window.had_loss
    report = window.as_report()
    assert report is not None, "reported as loss, because it cannot be ruled out"


def test_a_restart_mid_trial_is_uncertainty_and_not_a_crash():
    """A display that restarted raises on the next receive. The trial still ran;
    what is unknown is whether it was rendered cleanly."""
    observer = StimulusObserver(FakeSource())
    observer.open_window(first_frame=100)
    observer._note_uncertainty("server restarted")

    window = observer.close_window(last_frame=120)
    assert window is not None
    assert window.uncertain


def test_a_frame_counter_that_went_backwards_is_uncertainty():
    observer = StimulusObserver(FakeSource())
    observer.open_window(first_frame=900)
    window = observer.close_window(last_frame=5)

    assert window is not None
    assert window.uncertain, "the only way a frame index falls is a restart"


# ── Bookkeeping ───────────────────────────────────────────────────────────────


def test_an_overlapping_window_discards_the_earlier_one_rather_than_merging():
    """Two open windows means the session loop lost a trial. Merging would put
    one trial's frame loss on another's record, which is worse than losing it."""
    source = FakeSource([dropped(105)])
    observer = StimulusObserver(source)
    observer.open_window(first_frame=100)
    feed(observer, source)
    observer.open_window(first_frame=200)

    window = observer.close_window(last_frame=260)
    assert window is not None
    assert window.first_frame == 200
    assert window.lost_frames == 0


def test_closing_twice_gives_nothing_the_second_time():
    observer = StimulusObserver(FakeSource())
    observer.open_window(first_frame=1)
    assert observer.close_window(last_frame=2) is not None
    assert observer.close_window(last_frame=3) is None


def test_only_the_two_topics_that_matter_are_subscribed():
    """Not the presented-frame heartbeat: it arrives at the refresh rate, this
    side discards every one, and a subscriber that falls behind loses events."""
    assert TOPICS == ("frame.dropped", "server.started")
    assert "frame.presented" not in TOPICS


def test_closing_the_observer_closes_the_source():
    source = FakeSource()
    observer = StimulusObserver(source)
    observer.close()
    assert source.closed


def test_the_thread_runs_and_stops():
    """The one test that uses the real loop, because `start`/`close` is the part
    the others bypass."""
    source = FakeSource([dropped(105)])
    observer = StimulusObserver(source)
    observer.open_window(first_frame=100)
    observer.start()
    assert source.drained.wait(timeout=2.0), "the loop never drained the source"
    observer.close()

    window = observer.close_window(last_frame=120)
    assert window is not None
    assert window.lost_frames == 1
    assert source.closed
