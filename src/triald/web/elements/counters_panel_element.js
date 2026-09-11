// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `<triald-counters>` -- the per-trial-type tally table, the columns VStim's
// Trial Type Manager showed. **Counted is not accepted**: `total` is every
// reported outcome, `accepted` is the ones that consumed a slot in the round
// and moved the set towards its switch rule -- see triald's CLAUDE.md.

import { BasePanelElement, defineElementOnce } from "./base_panel_element.js";

/// [wire key, column header, title] -- the header is the abbreviation an
/// experimenter already reads; the title is the outcome's full name.
const OUTCOME_COLUMNS = [
  ["HIT", "Hit", "Correct response"],
  ["WRONG_RESPONSE", "Wrong", "Wrong response"],
  ["EARLY_HIT", "EHit", "Correct response on an early-release occasion"],
  ["EARLY_WRONG_RESPONSE", "EWrong", "Wrong response on an early-release occasion"],
  ["EARLY", "Early", "Responded before the window opened"],
  ["LATE", "Late", "Responded after the window closed"],
  ["EYE_ERROR", "Eye", "Gaze left the fixation window"],
  ["NOT_STARTED", "NoStart", "A start signal was required and never given"],
  ["UNEXPECTED_START_SIGNAL", "Unexp", "Start signal in an interval that is not a start interval"],
  ["WRONG_START_SIGNAL", "WrgStrt", "The wrong start signal was given"],
  ["CANCELLED", "Canc", "Aborted by the experimenter"],
  [
    "NEVER_FINISHED",
    "Never",
    "triald's own verdict: the trial started and its cap expired with nothing saying how it ended",
  ],
];

function pct(fraction) {
  return `${(fraction * 100).toFixed(1)}%`;
}

export class CountersPanelElement extends BasePanelElement {
  constructor() {
    super();
    this.state = null;
  }

  renderShell() {
    this.failureSlot = this.make("div", { class: "failure-slot" });
    this.tableSlot = this.make("div", { text: "waiting for a frame..." });
    this.noteSlot = this.make("p", { class: "muted" });
    this.resetSlot = this.make("div", { class: "row" });
    this.root.replaceChildren(
      this.make("section", {}, [
        this.make("h2", {}, [this.make("span", { text: "Counters" })]),
        this.failureSlot,
        this.make("div", { class: "scroller" }, [this.tableSlot]),
        this.noteSlot,
        this.resetSlot,
      ]),
    );
    this.resetSlot.replaceChildren(
      this.make("button", {
        text: "reset rounds",
        title: "Refill the bag and clear the round and set-progress counters.",
        onClick: () => this.attempt(() => this.api.resetRounds()),
      }),
      this.make("button", {
        text: "reset counters",
        title: "Clear every outcome tally, in every set. The bag and round are left alone.",
        onClick: () => this.attempt(() => this.api.resetCounters()),
      }),
    );
  }

  async start() {
    this.openStateStream();
  }

  openStateStream() {
    const socket = this.trackSocket(this.api.openStateStream());
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      this.state = message.state ?? message;
      this.paint();
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

  paint() {
    const state = this.state;
    if (state === null) return;
    const extended = state.config.extend_trial_type_number;

    const headerCells = [
      this.make("th", { text: extended ? "No." : "#" }),
      this.make("th", { text: "Trial type" }),
      this.make("th", { text: "#Trials", title: "Weight: how many of this type make one round" }),
      this.make("th", { text: "Graph", title: "State graph this type runs; blank means whatever the executor has loaded" }),
      this.make("th", { text: "Rew", title: "Reward the type is worth, in ms" }),
      this.make("th", { text: "Remain", title: "Still to run in the round" }),
      this.make("th", { text: "P(next)", title: "Chance of being drawn next by the ordering" }),
      this.make("th", { text: "All", title: "Every outcome reported -- counted" }),
      this.make("th", { text: "Accept", title: "Outcomes that consumed a slot in the round" }),
      ...OUTCOME_COLUMNS.map(([, short, title]) => this.make("th", { text: short, title })),
      this.make("th", { text: "VRloss", title: "Trials that lost at least one video frame" }),
    ];

    const rows = state.counters.map((row) =>
      this.make("tr", {}, [
        this.make("td", { text: extended ? row.trial_type_number : row.index }),
        this.make("td", { text: row.name || `type ${row.index}` }),
        this.make("td", { text: row.trials_per_round }),
        this.make("td", { text: row.statemachine_graph || "-" }),
        this.make("td", { text: row.reward_ms }),
        this.make("td", { text: row.remaining }),
        this.make("td", { text: row.p_next > 0 ? pct(row.p_next) : "-" }),
        this.make("td", { text: row.total }),
        this.make("td", { text: row.accepted }),
        ...OUTCOME_COLUMNS.map(([key]) => this.make("td", { text: row.by_outcome[key] ?? 0 })),
        this.make("td", { text: row.frame_loss }),
      ]),
    );

    const t = state.totals;
    const totalRow = this.make("tr", { style: "font-weight:600" }, [
      this.make("td", {}),
      this.make("td", { text: "Total" }),
      this.make("td", { text: state.trials_per_round }),
      this.make("td", {}),
      this.make("td", {}),
      this.make("td", { text: state.trials_remaining }),
      this.make("td", {}),
      this.make("td", { text: t.total }),
      this.make("td", { text: t.accepted }),
      ...OUTCOME_COLUMNS.map(([key]) => this.make("td", { text: t.by_outcome[key] ?? 0 })),
      this.make("td", { text: t.frame_loss }),
    ]);

    this.tableSlot.replaceChildren(
      this.make("table", {}, [
        this.make("thead", {}, [this.make("tr", {}, headerCells)]),
        this.make("tbody", {}, [...rows, totalRow]),
      ]),
    );
    this.noteSlot.textContent = extended
      ? "counters banked per set -- trial type numbers extended by the set number"
      : "one counter bank shared by every set";
  }
}

defineElementOnce("triald-counters", CountersPanelElement);
