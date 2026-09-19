// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `<triald-config>` -- the declarative half of one experiment: ordering,
// rounds, avoid-repeat, the stop rules, and the eleven-plus-two acceptance
// flags. Two levels, no DSL (triald's CLAUDE.md): everything here is data the
// web UI can edit; a policy is real Python and has no element of its own.

import { BasePanelElement, defineElementOnce } from "./base_panel_element.js";

// The wire values are the proto's own enum value names (`triald.v1.Ordering`),
// because that is what protobuf's JSON mapping puts on the wire and reads back.
// Spelling them out here rather than deriving them from the descriptor keeps
// the label and the help text beside the value they describe -- and a value
// that ever stops existing fails loudly, at the select, rather than silently
// selecting nothing.
const ORDERINGS = [
  ["ORDERING_RANDOM_IN_ROUND", "Random in round", "One round in the bag: every round holds exactly the configured weights."],
  [
    "ORDERING_RANDOM_IN_EXPERIMENT",
    "Random in experiment",
    "Every round in the bag at once: the experiment is balanced, single rounds are not.",
  ],
  ["ORDERING_ASCENDING", "Ascending", "Lowest trial type index first, strictly in order."],
  ["ORDERING_DESCENDING", "Descending", "Highest trial type index first -- the mirror of ascending."],
  [
    "ORDERING_RANDOM_WITH_REPLACEMENT",
    "Random with replacement",
    "Each trial an independent draw on the weights. Runs of one condition are longer than people expect.",
  ],
];

const CRITERIA = [
  ["TRIAL_COUNT_CRITERION_ACCEPTED_TRIALS", "accepted trials"],
  ["TRIAL_COUNT_CRITERION_HITS", "hits"],
  ["TRIAL_COUNT_CRITERION_ALL_TRIALS", "all completed trials"],
];

const ACCEPT_FIELDS = [
  ["hit", "Hit"],
  ["wrong_response", "Wrong"],
  ["early_hit", "Early hit"],
  ["early_wrong_response", "Early wrong"],
  ["early", "Early"],
  ["late", "Late"],
  ["eye_error", "Eye error"],
  ["not_started", "Not started"],
  ["unexpected_start_signal", "Unexp. start"],
  ["wrong_start_signal", "Wrong start"],
  ["cancelled", "Cancelled"],
  ["never_finished", "Never finished"],
];

export class ConfigPanelElement extends BasePanelElement {
  constructor() {
    super();
    this.config = null;
    this.running = false;
  }

  renderShell() {
    this.failureSlot = this.make("div", { class: "failure-slot" });
    this.bodySlot = this.make("div", { text: "reading the config..." });
    this.root.replaceChildren(
      this.make("section", {}, [
        this.make("h2", {}, [this.make("span", { text: "Config" })]),
        this.make("p", {
          class: "muted",
          text:
            "Arm-time settings (ordering, extend numbering, seed) are refused while a session " +
            "runs -- stop first. The accept flags and stop rules take effect on the next trial.",
        }),
        this.failureSlot,
        this.bodySlot,
      ]),
    );
  }

  async start() {
    await this.attempt(async () => {
      this.config = await this.api.readConfig();
      this.paint();
    });
    this.pollEvery(2, async () => {
      try {
        const state = await this.api.readState();
        this.running = state.running;
      } catch {
        /* shown by the failure slot already */
      }
      // A person's own edit already updated `this.config` optimistically via
      // patch(); polling re-reads it too so a second tab's edit shows up here.
      this.config = await this.api.readConfig();
      this.paint();
    });
  }

  paint() {
    this.repaintPreservingFocus(() => this.bodySlot.replaceChildren(this.body()));
  }

  body() {
    const c = this.config;
    if (c === null) return this.make("p", { class: "muted", text: "reading the config..." });

    const orderingSelect = this.make(
      "select",
      { onChange: (event) => this.patch({ ordering: event.target.value }), disabled: this.running },
      ORDERINGS.map(([value, label]) =>
        this.make("option", { value, text: label, selected: value === c.ordering }),
      ),
    );
    const help = ORDERINGS.find(([value]) => value === c.ordering);

    const stopAfterOn = c.stop_after_trials !== null;

    return this.make("div", {}, [
      this.make("div", { class: "row" }, [
        this.make("span", { class: "muted", text: "ordering" }),
        orderingSelect,
      ]),
      this.make("p", { class: "muted", text: help ? help[2] : "" }),
      this.make("div", { class: "row" }, [
        this.make("span", { class: "muted", text: "rounds" }),
        this.make("input", {
          type: "number",
          min: "1",
          value: String(c.rounds),
          onChange: (event) => this.patch({ rounds: Number(event.target.value) || 1 }),
        }),
        this.checkbox("avoid repeat", c.avoid_repeat, (value) => this.patch({ avoid_repeat: value })),
        this.checkbox(
          "extend trial type numbers",
          c.extend_trial_type_number,
          (value) => this.patch({ extend_trial_type_number: value }),
          this.running,
        ),
      ]),

      this.make("div", { class: "row" }, [
        this.make("span", { class: "muted", text: "trial cap" }),
        this.make("input", {
          type: "number",
          min: "0",
          value: String(c.trial_cap_ms),
          onChange: (event) => this.patch({ trial_cap_ms: Number(event.target.value) || 0 }),
        }),
        this.make("span", { class: "muted", text: "ms (0 = no cap)" }),
      ]),
      this.make("p", {
        class: "muted",
        text:
          "A watchdog, not a paradigm parameter: how long a trial may take before triald gives " +
          "up on hearing about it and records NEVER_FINISHED on its own. Set it to the longest " +
          "a trial could honestly take.",
      }),

      this.make("h3", { text: "Stop rules" }),
      this.make("div", { class: "row" }, [
        this.checkbox(
          "stop when rounds are done",
          c.stop_when_rounds_done,
          (value) => this.patch({ stop_when_rounds_done: value }),
        ),
      ]),
      this.make("div", { class: "row" }, [
        this.checkbox("stop after", stopAfterOn, (value) =>
          this.patch({ stop_after_trials: value ? Number(this.stopAfterInput?.value) || 1 : 0 }),
        ),
        (this.stopAfterInput = this.make("input", {
          type: "number",
          min: "1",
          value: String(c.stop_after_trials ?? 100),
          disabled: !stopAfterOn,
          onChange: (event) =>
            this.patch({ stop_after_trials: Number(event.target.value) || 1 }),
        })),
        this.make(
          "select",
          {
            disabled: !stopAfterOn,
            onChange: (event) => this.patch({ stop_criterion: event.target.value }),
          },
          CRITERIA.map(([value, label]) =>
            this.make("option", { value, text: label, selected: value === c.stop_criterion }),
          ),
        ),
      ]),

      this.make("h3", { text: "Accept" }),
      this.make("p", {
        class: "muted",
        text: "Which outcomes consume a slot in the round. Frame loss and imprecise fixation can veto any of them.",
      }),
      this.make(
        "div",
        { class: "row" },
        ACCEPT_FIELDS.map(([field, label]) =>
          this.checkbox(label, c.acceptance[field], (value) => this.patchAcceptance(field, value)),
        ),
      ),
      this.make("div", { class: "row" }, [
        this.checkbox("with frame loss", c.acceptance.frame_loss, (value) =>
          this.patchAcceptance("frame_loss", value),
        ),
        this.checkbox("with imprecise fixation", c.acceptance.imprecise_fixation, (value) =>
          this.patchAcceptance("imprecise_fixation", value),
        ),
      ]),
    ]);
  }

  checkbox(label, checked, onChange, disabled = false) {
    return this.make("label", { class: "row", style: "gap:0.25rem" }, [
      this.make("input", {
        type: "checkbox",
        checked,
        disabled,
        onChange: (event) => onChange(event.target.checked),
      }),
      this.make("span", { text: label }),
    ]);
  }

  async patch(changes) {
    const result = await this.attempt(() => this.api.patchConfig(changes));
    if (result !== null) {
      this.config = result.config;
      this.paint();
    }
  }

  patchAcceptance(field, value) {
    return this.patch({ acceptance: { ...this.config.acceptance, [field]: value } });
  }
}

defineElementOnce("triald-config", ConfigPanelElement);
