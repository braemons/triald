// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `<triald-trials>` -- the recent finished trials, newest first. `state.recent`
// is the tail of the session's append-only record (triald's CLAUDE.md:
// "records are evidence"), not a separate log this panel keeps itself.

import { BasePanelElement, defineElementOnce } from "./base_panel_element.js";

export class TrialsPanelElement extends BasePanelElement {
  constructor() {
    super();
    this.state = null;
  }

  renderShell() {
    this.failureSlot = this.make("div", { class: "failure-slot" });
    this.tableSlot = this.make("div", { text: "waiting for a frame..." });
    this.root.replaceChildren(
      this.make("section", {}, [
        this.make("h2", {}, [this.make("span", { text: "Trial log" })]),
        this.make("p", {
          class: "muted",
          text: "The last few finished trials, newest first. A check mark means accepted, not merely counted.",
        }),
        this.failureSlot,
        this.make("div", { class: "scroller" }, [this.tableSlot]),
      ]),
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
    const rows = [...state.recent].reverse();
    if (rows.length === 0) {
      this.tableSlot.replaceChildren(this.make("p", { class: "muted", text: "no trials yet" }));
      return;
    }
    this.tableSlot.replaceChildren(
      this.make("table", {}, [
        this.make("thead", {}, [
          this.make("tr", {}, [
            this.make("th", { text: "#" }),
            this.make("th", { text: "set" }),
            this.make("th", { text: "type" }),
            this.make("th", { text: "outcome" }),
            this.make("th", { text: "RT" }),
            this.make("th", { text: "A", title: "Accepted -- did it consume a slot in the round?" }),
            this.make("th", { text: "why not" }),
          ]),
        ]),
        this.make(
          "tbody",
          {},
          rows.map((record) =>
            this.make("tr", {}, [
              this.make("td", { text: record.trial.trial_number }),
              this.make("td", { text: record.trial.set_name }),
              this.make("td", { text: record.trial.trial_type_name || record.trial.trial_type_index }),
              this.make("td", { text: record.outcome.name }),
              this.make("td", {
                text:
                  record.outcome.reaction_time_ms == null
                    ? "-"
                    : record.outcome.reaction_time_ms.toFixed(0),
              }),
              this.make("td", {
                text: record.accepted ? "✓" : "✗",
                class: record.accepted ? "good" : "bad",
              }),
              this.make("td", { text: record.refusal_reason ?? "" }),
            ]),
          ),
        ),
      ]),
    );
  }
}

defineElementOnce("triald-trials", TrialsPanelElement);
