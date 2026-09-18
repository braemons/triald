// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `<triald-sets>` -- every trial-type set in the store, its switch rule, and
// which one is active. Loading a set is here; editing one's trial types is
// not yet an element (see triald's own web UI for the JSON route, or PUT
// `/api/sets/{name}` directly) -- this mirrors what the console needs first:
// seeing what a session will do and switching what is running.

import { BasePanelElement, defineElementOnce } from "./base_panel_element.js";

const CRITERIA_LABELS = {
  accepted_trials: "accepted trials",
  hits: "hits",
  all_trials: "all completed trials",
};

export class SetsPanelElement extends BasePanelElement {
  constructor() {
    super();
    this.sets = null;
    this.progress = null;
  }

  renderShell() {
    this.failureSlot = this.make("div", { class: "failure-slot" });
    this.chainSlot = this.make("div");
    this.listSlot = this.make("div", { text: "reading the sets..." });
    this.root.replaceChildren(
      this.make("section", {}, [
        this.make("h2", {}, [this.make("span", { text: "Sets" })]),
        this.make("p", {
          class: "muted",
          text:
            "A set is a named collection of trial types with a switch rule saying when to " +
            "leave it. Only the active set's progress towards its rule is shown -- every other " +
            "set's block starts from nothing whenever it is loaded.",
        }),
        this.failureSlot,
        this.chainSlot,
        this.listSlot,
      ]),
    );
  }

  async start() {
    await this.refresh();
    this.pollEvery(2, () => this.refresh());
  }

  async refresh() {
    this.sets = await this.api.readSets();
    try {
      const state = await this.api.readState();
      this.progress = state.set_progress;
    } catch {
      this.progress = null;
    }
    this.paint();
  }

  paint() {
    const sets = this.sets;
    this.chainSlot.replaceChildren(
      sets && sets.chain_problem
        ? this.make("p", { class: "bad", text: sets.chain_problem })
        : this.make("div"),
    );
    if (sets === null) return;
    this.listSlot.replaceChildren(...sets.sets.map((set) => this.setCard(set)));
  }

  setCard(set) {
    const rule = set.switch_rule;
    const armed = rule.enabled && rule.target && rule.count > 0;
    const progress = set.active ? this.progress : null;
    const criterion = CRITERIA_LABELS[rule.criterion] ?? rule.criterion;

    let ruleLine;
    if (armed && progress) {
      ruleLine = `after ${progress.reached}/${rule.count} ${criterion} → ${rule.target}`;
    } else if (armed) {
      ruleLine = `after ${rule.count} ${criterion} → ${rule.target}`;
    } else {
      ruleLine = "no switch rule -- the sequence ends here";
    }
    const fraction = armed && progress ? Math.min(1, progress.reached / rule.count) : null;

    return this.make("div", { class: "row", style: "align-items:flex-start;gap:0.75rem" }, [
      this.make("div", { style: "flex:1;min-width:0" }, [
        this.make("div", { class: "row" }, [
          this.make("strong", { text: set.name }),
          set.active ? this.make("span", { class: "pill good", text: "active" }) : this.make("span"),
          this.make("span", {
            class: "muted",
            text: `#${set.set_number} · ${set.trial_types.length} types · ${set.trials_per_round}/round`,
          }),
        ]),
        this.make("div", { class: "muted", text: ruleLine }),
        set.runnable
          ? this.make("div")
          : this.make("div", { class: "warn", text: "every weight is zero -- this set cannot run" }),
        fraction === null
          ? this.make("div")
          : this.make("div", { style: "height:0.35rem;background:var(--panel-border);border-radius:3px;margin-top:0.3rem" }, [
              this.make("div", {
                style: `height:100%;width:${(fraction * 100).toFixed(1)}%;background:var(--accent);border-radius:3px`,
              }),
            ]),
      ]),
      this.make("button", {
        text: "load",
        disabled: set.active || !set.runnable,
        onClick: () => this.attempt(() => this.api.loadSet(set.name)).then(() => this.refresh()),
      }),
    ]);
  }
}

defineElementOnce("triald-sets", SetsPanelElement);
