// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `<triald-debug>` -- driving the real trial loop with a simulated subject,
// for a bench with no vstimd and no microcontroller attached.
//
// **Nothing here is a second code path.** `step` and `free-run` both call
// `runner.run_trial` through `/api/debug/step` and `/api/debug/free-run`,
// exactly the four calls a rig makes with `SimulatedBehaviourSource` standing
// in for the microcontroller. "Report one outcome by hand" is the one thing a
// rig cannot do through this panel -- `/api/trial/next` and
// `/api/trial/outcome` are the same two calls a rig's behaviour source makes,
// used here to demonstrate the accept/refuse decision one trial at a time.

import { BasePanelElement, defineElementOnce } from "./base_panel_element.js";

/// Outcome buttons for reporting one trial by hand, with their `.tdr` codes --
/// see triald.outcomes.TrialOutcome. Never renumbered; see triald's CLAUDE.md.
const OUTCOMES = [
  ["HIT", 1],
  ["WRONG_RESPONSE", 2],
  ["EARLY_HIT", 3],
  ["EARLY_WRONG_RESPONSE", 4],
  ["EARLY", 5],
  ["LATE", 6],
  ["EYE_ERROR", 7],
  ["NOT_STARTED", 0],
  ["UNEXPECTED_START_SIGNAL", 8],
  ["WRONG_START_SIGNAL", 9],
];

/// The synthetic subject's dials -- see triald.behaviour and SimSettingsModel.
const SIM_FIELDS = [
  ["hit_rate", "hit rate"],
  ["not_started_rate", "not started"],
  ["eye_error_rate", "eye error"],
  ["early_rate", "early"],
  ["frame_loss_rate", "frame loss"],
  ["imprecise_fixation_rate", "imprecise fixation"],
];

export class DebugPanelElement extends BasePanelElement {
  constructor() {
    super();
    this.state = null;
    this.sim = null;
    this.freeRun = null;
    this.stepCount = 10;
    this.imprecise = false;
    this.frameLoss = false;
  }

  renderShell() {
    this.failureSlot = this.make("div", { class: "failure-slot" });
    this.stepSlot = this.make("div");
    this.simSlot = this.make("div");
    this.manualSlot = this.make("div");
    this.root.replaceChildren(
      this.make("section", {}, [
        this.make("h2", {}, [this.make("span", { text: "Simulated subject" })]),
        this.make("p", {
          class: "muted",
          text:
            "Drives triald's real trial loop with a synthetic subject in place of vstimd and a " +
            "microcontroller -- triald sim's fastest feedback loop, from a browser. Nothing " +
            "here reaches a rig.",
        }),
        this.failureSlot,
        this.make("h3", { text: "Run trials" }),
        this.stepSlot,
        this.make("h3", { text: "The subject's dials" }),
        this.simSlot,
        this.make("h3", { text: "One trial by hand" }),
        this.manualSlot,
      ]),
    );
  }

  async start() {
    this.paintStep();
    this.paintManual();
    await this.attempt(async () => {
      this.sim = await this.api.readSim();
      this.paintSim();
    });
    this.openStateStream();
    this.pollEvery(2, async () => {
      this.freeRun = await this.api.readFreeRun();
      this.paintStep();
    });
  }

  openStateStream() {
    const socket = this.trackSocket(this.api.openStateStream());
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      this.state = message.state ?? message;
      this.paintManual();
    });
    socket.addEventListener("close", () => {
      if (this.isConnected && this.openSockets.includes(socket)) {
        this.openSockets = this.openSockets.filter((each) => each !== socket);
        setTimeout(() => {
          if (this.isConnected) this.openStateStream();
        }, 1000);
      }
    });
  }

  // ------------------------------------------------------------- painting ---

  paintStep() {
    this.stepSlot.replaceChildren(this.stepControls());
  }

  stepControls() {
    const freeRun = this.freeRun;
    const running = freeRun !== null && freeRun.running;
    return this.make("div", { class: "row" }, [
      this.make("span", { class: "muted", text: "trials" }),
      this.make("input", {
        type: "number",
        min: "1",
        max: "10000",
        value: String(this.stepCount),
        onInput: (event) => {
          this.stepCount = Number(event.target.value) || 1;
        },
      }),
      this.make("button", {
        class: "primary",
        text: "run",
        onClick: () => this.attempt(() => this.api.step(this.stepCount)),
      }),
      this.make("span", { class: "spacer" }),
      this.make("button", {
        class: running ? "" : "primary",
        text: running ? "stop free-running" : "free-run",
        onClick: () =>
          this.attempt(async () => {
            this.freeRun = await this.api.setFreeRun(!running, freeRun ? freeRun.interval_ms : 250);
            this.paintStep();
          }),
      }),
      freeRun
        ? this.make("span", {
            class: running ? "good" : "muted",
            text: running ? `every ${freeRun.interval_ms} ms` : "not free-running",
          })
        : this.make("span"),
    ]);
  }

  paintSim() {
    this.simSlot.replaceChildren(this.simControls());
  }

  simControls() {
    const sim = this.sim;
    if (sim === null) return this.make("p", { class: "muted", text: "reading the dials..." });
    const rows = SIM_FIELDS.map(([field, label]) => {
      const output = this.make("output", { text: Number(sim[field]).toFixed(2) });
      const slider = this.make("input", {
        type: "range",
        min: "0",
        max: "1",
        step: "0.01",
        value: String(sim[field]),
        style: "grid-column:1/-1",
        onInput: (event) => {
          output.textContent = Number(event.target.value).toFixed(2);
        },
        onChange: () => this.commitSim(),
      });
      slider.dataset.simField = field;
      return this.make("div", { class: "row" }, [
        this.make("span", { class: "muted", style: "width:8rem", text: label }),
        output,
        slider,
      ]);
    });
    return this.make("div", {}, rows);
  }

  async commitSim() {
    const settings = {};
    for (const slider of this.simSlot.querySelectorAll("[data-sim-field]")) {
      settings[slider.dataset.simField] = Number(slider.value);
    }
    const saved = await this.attempt(() => this.api.setSim(settings));
    if (saved !== null) this.sim = saved;
  }

  paintManual() {
    this.repaintPreservingFocus(() => this.manualSlot.replaceChildren(this.manualControls()));
  }

  manualControls() {
    const state = this.state;
    const inFlight = state !== null && state.current !== null;
    const running = state !== null && state.running;
    return this.make("div", {}, [
      this.make("div", { class: "row" }, [
        this.make("button", {
          text: "next trial",
          disabled: !running || inFlight,
          onClick: () => this.attempt(() => this.api.nextTrial()),
        }),
        this.make("button", {
          text: "cancel trial",
          disabled: !inFlight,
          onClick: () => this.attempt(() => this.api.cancelTrial("cancelled from the console")),
        }),
      ]),
      this.make("div", { class: "row" }, [
        this.make("label", { class: "row", style: "gap:0.25rem" }, [
          this.make("input", {
            type: "checkbox",
            checked: this.imprecise,
            onChange: (event) => {
              this.imprecise = event.target.checked;
            },
          }),
          this.make("span", { text: "imprecise fixation" }),
        ]),
        this.make("label", { class: "row", style: "gap:0.25rem" }, [
          this.make("input", {
            type: "checkbox",
            checked: this.frameLoss,
            onChange: (event) => {
              this.frameLoss = event.target.checked;
            },
          }),
          this.make("span", { text: "frame loss" }),
        ]),
      ]),
      this.make("div", { class: "row" }, [
        ...OUTCOMES.map(([name, code]) =>
          this.make("button", {
            text: name.toLowerCase().replace(/_/g, " "),
            title: `code ${code}`,
            disabled: !inFlight,
            onClick: () =>
              this.attempt(() =>
                this.api.reportOutcome({
                  // Addresses the message, not part of the outcome: a report
                  // that arrives late must be refused rather than attributed
                  // to the trial after the one it belongs to.
                  trial_id: state.current.trial_number,
                  outcome: name,
                  manipulandum: "SIMULATED",
                  precise_fixation: !this.imprecise,
                  frame_loss: this.frameLoss ? { interval: 0, frame: 0 } : null,
                  simulated: true,
                }),
              ),
          }),
        ),
      ]),
      this.make("p", {
        class: "muted",
        text:
          "Both modifiers can veto an otherwise-accepted outcome on their own -- that is what " +
          "the two checkboxes are here to show. See triald's CLAUDE.md: counted is not accepted.",
      }),
    ]);
  }
}

defineElementOnce("triald-debug", DebugPanelElement);
