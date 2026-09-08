# SPDX-License-Identifier: AGPL-3.0-or-later
"""Subscribing to a stimulus display, and joining what it saw to a trial.

The other half of :mod:`triald.stimulus`, which does the arithmetic and imports
nothing. This is the part that needs a socket, so it lives in `api/` beside
:mod:`triald.api.statemachine_executor` and for the same reason: triald's core
has no dependencies, and testing the join must not require a renderer.

**The display knows nothing about triald, and this changes nothing about that.**
vstimd publishes on a PUB socket -- connecting is the whole of subscribing, it
keeps no list of who is attached, and a rig with nobody listening renders
exactly the same. Which it does most of the time: it is always on, for
alignment, display checks and luminance, with no session running at all. So
nothing here can ask the display to wait, and nothing here should want to.

**The join is triald's because the boundaries are.** A trial is a window of
frames. This side notes the frame index when a trial is configured and again
when it ends, and everything the display stated in between belongs to that
trial. The display could not do this join if it wanted to -- it has no trial
concept, and giving it one would give it session state to keep in sync and a way
to mislabel data it never understood.

**Optional, and that is load-bearing.** A rig with no display daemon runs triald
unchanged: nothing constructs this unless something asks for it, and the session
loop never learns whether it exists. `vstimd` is an optional dependency for the
same reason.

**Subscribed to exactly two topics.** Frame drops, because those can veto a
trial; and server restarts, because a restart resets the frame counter and a
frame index held across one is a number from a different run. The presented-frame
heartbeat is deliberately not taken: it arrives at the display's refresh rate,
this side would discard every one, and a subscriber that falls behind loses
events silently.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from triald.stimulus import FrameLossAccount, FrameWindow

log = logging.getLogger(__name__)

#: The topics triald takes, and no others. See the module docstring.
TOPICS = ("frame.dropped", "server.started")

#: How long a receive waits before the loop checks whether it should stop.
#: Short enough that closing is prompt, long enough not to spin.
POLL_MILLISECONDS = 250


class StimulusSource(Protocol):
    """What this needs from a display, which is very little.

    A protocol rather than an import so :class:`StimulusObserver` can be tested
    with integers, and so triald never requires the vstimd client to be
    installed in order to be imported. :func:`connect` is the only place the
    real one is named.
    """

    def receive(self, timeout_ms: int | None = None) -> object | None: ...
    def close(self) -> None: ...


def connect(host: str, port: int | None = None) -> StimulusSource:
    """A subscriber on a vstimd's event stream.

    Imported here rather than at module scope: a triald with no display daemon
    in its rig should not need the client installed to start.
    """
    from vstimd.events import DEFAULT_EVENT_PORT, EventSubscriber

    return EventSubscriber(host, port or DEFAULT_EVENT_PORT, topic=list(TOPICS))


class StimulusObserver:
    """Frame-numbered facts from a display, attributed to whatever trial is open.

    One instance per session, one open window at a time::

        observer = StimulusObserver(connect("rig.local"))
        observer.start()
        ...
        observer.open_window(first_frame=display_frame_now())
        # ... the trial runs ...
        window = observer.close_window(last_frame=display_frame_now())

    Outside a window, events are read and dropped. That is not waste: reading is
    what keeps the subscription from falling behind, and a subscriber that falls
    behind loses events **silently** -- so a socket nobody drains between trials
    would make the first trial after a quiet spell the least trustworthy one.
    """

    def __init__(self, source: StimulusSource) -> None:
        self._source = source
        self._lock = threading.Lock()
        self._account: FrameLossAccount | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_frame_seen: int | None = None
        """The frame index of the most recent event, or None before the first.

        Not a substitute for asking the display where it is. It is the best this
        side knows, and between trials it can be arbitrarily stale -- a display
        that dropped no frames and restarted nothing says nothing at all.
        """

    # -- the window ------------------------------------------------------------

    def open_window(self, first_frame: int) -> None:
        """Begin attributing what the display says to a trial starting now.

        An already-open window is closed and discarded rather than merged: two
        overlapping windows means the session loop lost track of a trial, and
        continuing quietly would put one trial's frame loss on another's record.
        """
        with self._lock:
            if self._account is not None:
                log.warning(
                    "stimulus: a frame window was still open at frame %d when "
                    "another opened at %d; the earlier one is discarded",
                    self._account.first_frame,
                    first_frame,
                )
            self._account = FrameLossAccount(first_frame=first_frame)

    def close_window(self, last_frame: int) -> FrameWindow | None:
        """Finish the open window, or None if there was none."""
        with self._lock:
            account, self._account = self._account, None
        return account.close(last_frame=last_frame) if account is not None else None

    # -- the loop --------------------------------------------------------------

    def start(self) -> None:
        """Read the stream on a thread of its own until :meth:`close`.

        A daemon thread: it holds nothing that must be flushed, and a session
        that is shutting down must not wait on a socket to decide it is done.
        """
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="triald-stimulus", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._source.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._source.receive(timeout_ms=POLL_MILLISECONDS)
            except Exception as error:
                # **Never let this kill the session.** A display that restarted
                # raises here, and so does a socket error; neither is a reason
                # to stop running an animal. What it costs is certainty about
                # the window, which is exactly what `note_uncertainty` records.
                self._note_uncertainty(str(error))
                if self._stop.wait(POLL_MILLISECONDS / 1000):
                    return
                continue
            if event is not None:
                self._account_for(event)

    # -- one event -------------------------------------------------------------

    def _account_for(self, event: object) -> None:
        frame = getattr(event, "frame", None)
        if frame is None:
            return
        self.last_frame_seen = frame

        # A gap means this subscriber missed events it will never see again, so
        # the window it spans cannot be called clean. Reporting "no loss" for a
        # trial nobody was fully watching is a false negative, and a false
        # negative keeps a bad trial in the dataset.
        if getattr(event, "missed_before", 0):
            self._note_uncertainty(f"{event.missed_before} events missed")  # type: ignore[attr-defined]

        if getattr(event, "topic", "") != "frame.dropped":
            return
        payload = getattr(event, "payload", None)
        count = getattr(payload, "count", 0)
        with self._lock:
            if self._account is not None:
                self._account.note_loss(frame=frame, count=count)

    def _note_uncertainty(self, reason: str) -> None:
        with self._lock:
            if self._account is not None:
                self._account.note_uncertainty(reason)
