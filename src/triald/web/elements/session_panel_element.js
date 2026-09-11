// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `<triald-session>` -- what is running, what it decided last, and the
// controls to arm, stop and record. Driving a trial with no hardware
// attached is `<triald-debug>`'s job, kept separate for the reason
// statemachined splits Session from Recording: this panel is what a rig
// (with triald actually driving the loop) looks like, and the debug panel
// is the bench instrument a rig does not need mounted at all.
//
// **Everything here goes through `dev/API.md`.**
//
// Several slots, painted by different things, for the reason
// statemachined's session panel gives: the live state arrives on a
// WebSocket several times a second and must never touch a field a person is
// mid-edit on, so the state slot and the controls slots are separate subtrees.

import { BasePanelElement, defineElementOnce } from "./base_panel_element.js";

export class SessionPanelElement extends BasePanelElement {
  constructor() {
    super();
    this.state = null;
    this.stopReasonInput = "stopped by the operator";
  }

  renderShell() {
    this.failureSlot = this.make("div", { class: "failure-slot" });
    this.liveSlot = this.make("div");
    this.lifecycleSlot = this.make("div");
    this.recordingSlot = this.make("div");
    this.currentSlot = this.make("div");
    this.lastSlot = this.make("div");
    this.root.replaceChildren(
      this.make("section", {}, [
        this.make("h2", {}, [this.make("span", { text: "Session" })]),
        this.make("p", {
          class: "muted",
          text:
            "triald decides what trial runs next and remembers what happened; it holds no " +
            "hardware link of its own. On a rig, vstimd's armed animations chain and the " +
            "microcontroller names the outcome -- they agree through trigger edges. Arming " +
            "here is the bench equivalent of what a rig does on its own.",
        }),
        this.failureSlot,
        this.make("h3", { text: "Now" }),
        this.liveSlot,
        this.make("h3", { text: "Session lifecycle" }),
        this.lifecycleSlot,
        this.make("h3", { text: "Recording" }),
        this.recordingSlot,
        this.make("h3", { text: "Trial in flight" }),
        this.currentSlot,
        this.make("h3", { text: "The last trial" }),
        this.lastSlot,
      ]),
    );
  }

  async start() {
    this.paintLive();
    this.paintLifecycle();
    this.paintRecording();
    this.paintCurrent();
    this.paintLast();
    this.openStateStream();
  }

  openStateStream() {
    const socket = this.trackSocket(this.api.openStateStream());
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      this.state = message.state ?? message;
      this.paintLive();
      this.paintLifecycle();
      this.paintRecording();
      this.paintCurrent();
      this.paintLast();
      this.clearFailure();
    });
    socket.addEventListener("close", () => {
      // Reopen unless this panel is going away. A stream that dies quietly
      // when the daemon restarts leaves a page that looks live and is not.
      if (this.isConnected && this.openSockets.includes(socket)) {
        this.openSockets = this.openSockets.filter((each) => each !== socket);
        setTimeout(() => {
          if (this.isConnected) this.openStateStream();
        }, 1000);
      }
    });
  }

  // ------------------------------------------------------------- painting ---

  paintLive() {
    this.liveSlot.replaceChildren(this.liveState());
  }

  liveState() {
    const state = this.state;
    if (state === null) return this.make("p", { class: "muted", text: "waiting for a frame..." });
    const progress = state.set_progress;
    return this.fieldList([
      [
        "running",
        state.running
          ? this.make("span", { class: "pill good", text: "running" })
          : this.make("span", { class: "pill", text: "idle" }),
      ],
      [
        "recording",
        state.recording
          ? this.make("span", { class: "pill good", text: state.paused ? "paused" : "recording" })
          : this.make("span", { class: "pill", text: "off" }),
      ],
      ["stop reason", state.stop_reason ?? "-"],
      ["set", state.set_name],
      [
        "set progress",
        progress
          ? `${progress.accepted_trials} accepted, ${progress.hits} hits` +
            (progress.target != null ? ` / ${progress.target} (${progress.criterion})` : "")
          : "-",
      ],
      ["rounds", `${state.rounds_completed} of ${state.rounds_configured}`],
      ["trials remaining this round", state.trials_remaining],
      ["trials started", state.trials_started],
      [
        "totals",
        `${state.totals.accepted} accepted / ${state.totals.total} reported` +
          (state.totals.hit_rate != null ? `, hit rate ${(state.totals.hit_rate * 100).toFixed(1)}%` : ""),
      ],
      ["policy", `${state.policy.name} (${state.policy.origin})`],
    ]);
  }

  paintLifecycle() {
    this.lifecycleSlot.replaceChildren(this.lifecycleControls());
  }

  lifecycleControls() {
    const state = this.state;
    const running = state !== null && state.running;
    return this.make("div", {}, [
      this.make("div", { class: "row" }, [
        this.make("button", {
          class: running ? "" : "primary",
          text: "arm",
          disabled: running,
          onClick: () => this.attempt(() => this.api.arm()),
        }),
        this.make("input", {
          type: "text",
          value: this.stopReasonInput,
          style: "width:16rem",
          onInput: (event) => {
            this.stopReasonInput = event.target.value;
          },
        }),
        this.make("button", {
          text: "stop",
          disabled: !running,
          onClick: () => this.attempt(() => this.api.stop(this.stopReasonInput)),
        }),
      ]),
      this.make("p", {
        class: "muted",
        text:
          "Arming validates the config and the active set's switch chain and starts a new " +
          "session with counters at zero. On a rig triald arms itself; this is the bench " +
          "equivalent.",
      }),
    ]);
  }

  paintRecording() {
    this.recordingSlot.replaceChildren(this.recordingControls());
  }

  recordingControls() {
    const state = this.state;
    const recording = state !== null && state.recording;
    const paused = state !== null && state.paused;
    return this.make("div", { class: "row" }, [
      this.make("button", {
        class: recording ? "" : "primary",
        text: "start",
        disabled: recording,
        onClick: () => this.attempt(() => this.api.startRecording()),
      }),
      this.make("button", {
        text: "pause",
        disabled: !recording || paused,
        onClick: () => this.attempt(() => this.api.pauseRecording()),
      }),
      this.make("button", {
        text: "resume",
        disabled: !recording || !paused,
        onClick: () => this.attempt(() => this.api.resumeRecording()),
      }),
      this.make("button", {
        text: "stop",
        disabled: !recording,
        onClick: () => this.attempt(() => this.api.stopRecording()),
      }),
    ]);
  }

  paintCurrent() {
    this.currentSlot.replaceChildren(this.currentTrial());
  }

  currentTrial() {
    const current = this.state && this.state.current;
    if (!current) return this.make("p", { class: "muted", text: "no trial in flight" });
    return this.fieldList([
      ["trial", current.trial_number],
      ["type", `${current.trial_type_name} (index ${current.trial_type_index})`],
      ["set", current.set_name],
      ["state graph", current.statemachine_graph || "(whatever the executor has loaded)"],
      ["reward", `${current.reward_ms} ms`],
      ["recording", current.recording ? "yes" : "no"],
      ["started", current.started_at],
      ["deadline", current.deadline ?? "none -- no cap configured"],
    ]);
  }

  paintLast() {
    this.lastSlot.replaceChildren(this.lastTrial());
  }

  lastTrial() {
    const last = this.state && this.state.last;
    if (!last) return this.make("p", { class: "muted", text: "no trial has finished on this connection" });
    return this.fieldList([
      ["trial", last.trial.trial_number],
      ["type", last.trial.trial_type_name],
      [
        "outcome",
        this.make("span", {
          class: last.outcome.name === "HIT" ? "pill good" : "pill",
          text: last.outcome.name,
        }),
      ],
      [
        "accepted",
        last.accepted
          ? this.make("span", { class: "pill good", text: "accepted" })
          : this.make("span", { class: "pill warn", text: last.refusal_reason ?? "counted only" }),
      ],
      ["ended", last.ended_at],
    ]);
  }
}

defineElementOnce("triald-session", SessionPanelElement);
