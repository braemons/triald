# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the stimulus display saw during a trial, and whether it matters.

A stimulus server renders and states facts about frames: this one was presented,
that one was missed. It has no idea what a trial is, and it must not -- a
renderer with a trial concept is a renderer with session state to keep in sync
and a way to mislabel data it never understood.

**So the join is triald's.** A trial is a window of frames: note the frame index
when the trial is configured, note it again when the trial ends, and any loss
reported between the two belongs to that trial. triald is the only side that
knows where those boundaries are, because triald is the side that decides what a
trial is.

**And the verdict is triald's too.** Frame loss can veto acceptance on its own
(`AcceptancePolicy.frame_loss`), which makes "did this trial lose a frame" a
decision about the experiment, not a fact about the GPU. The stimulus server
states the fact and judges nothing.

Nothing here imports anything. Frames in, a
:class:`~triald.outcomes.FrameLoss` out, so this is testable with integers --
no ZMQ, no protobuf, no renderer.
"""

from __future__ import annotations

import dataclasses

from triald.outcomes import FrameLoss


@dataclasses.dataclass(frozen=True, slots=True)
class FrameWindow:
    """The span of frames a trial occupied, and what was lost inside it.

    Built by :class:`FrameLossAccount` rather than by hand: the whole point is
    that the boundaries come from the same clock the losses do.
    """

    first_frame: int
    """The display's frame index when the trial was configured."""

    last_frame: int
    """The display's frame index when the trial ended."""

    lost_frames: int
    """How many frames the display reported missing inside the window."""

    first_loss_at: int | None = None
    """The frame index of the first loss, or None if there was none."""

    uncertain: bool = False
    """Whether the account is known to be incomplete.

    True when the subscription lost events, or the display restarted, during the
    window. **A trial whose frame record is uncertain is reported as having lost
    a frame**, because the alternative is reporting "no loss" for a trial nobody
    was watching -- and a false negative here is a trial silently kept in a
    dataset that should have been refused.
    """

    @property
    def had_loss(self) -> bool:
        return self.lost_frames > 0 or self.uncertain

    def as_report(self) -> FrameLoss | None:
        """The modifier for an outcome report, or None if the window was clean.

        `FrameLoss.interval` is 0: intervals are the within-trial state machine's
        idea, and the display has never heard of them. What is known is *which
        frame*, and that is what is recorded.
        """
        if not self.had_loss:
            return None
        return FrameLoss(
            interval=0,
            frame=self.first_loss_at if self.first_loss_at is not None else self.first_frame,
        )


class FrameLossAccount:
    """Frame loss over one trial's window, accumulated as events arrive.

    Fed from a subscription to the display's event stream; nothing here knows
    what a socket is. One instance per trial::

        account = FrameLossAccount(first_frame=display_frame_now())
        # ... while the trial runs, for each event:
        account.note_loss(frame=..., count=...)
        # ... when it ends:
        window = account.close(last_frame=display_frame_now())
    """

    def __init__(self, first_frame: int) -> None:
        self.first_frame = first_frame
        self._lost = 0
        self._first_loss_at: int | None = None
        self._uncertain = False

    def note_loss(self, frame: int, count: int = 1) -> None:
        """The display reported `count` frames missed at `frame`.

        A loss before the window opened is ignored rather than counted: it
        belongs to whatever came before this trial, and attributing it here is
        the same mislabelling a late outcome would be.
        """
        if frame < self.first_frame or count <= 0:
            return
        self._lost += count
        if self._first_loss_at is None:
            self._first_loss_at = frame

    def note_uncertainty(self, reason: str = "") -> None:
        """Something happened that means this account may be incomplete.

        The subscription lost events, or the display restarted mid-trial. It is
        one-way: nothing later can restore confidence in a window that was not
        fully observed.
        """
        self._uncertain = True

    def close(self, last_frame: int) -> FrameWindow:
        """Finish the window at `last_frame` and give what it holds.

        A `last_frame` before `first_frame` means the display's frame counter
        went backwards, which happens exactly once: it restarted. That is
        uncertainty, not an error -- the trial ran, and what is unknown is
        whether it was rendered cleanly.
        """
        if last_frame < self.first_frame:
            self._uncertain = True
            last_frame = self.first_frame
        return FrameWindow(
            first_frame=self.first_frame,
            last_frame=last_frame,
            lost_frames=self._lost,
            first_loss_at=self._first_loss_at,
            uncertain=self._uncertain,
        )
