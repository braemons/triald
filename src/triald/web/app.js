/*
 * The session view, in one file and no framework.
 *
 * The shape is deliberately dull: one WebSocket delivers a whole
 * SessionStateModel on every change, `render()` draws it, and every control
 * POSTs and then waits for the next frame rather than predicting one. There is
 * no client-side model of the session, so the page cannot disagree with the
 * daemon about what is happening - which is the failure mode that matters when
 * somebody is deciding whether to keep an animal working.
 *
 * The one exception is an input the user is typing into: `render()` leaves the
 * focused element alone, or a slow reply would eat a keystroke.
 */

const $ = (id) => document.getElementById(id);

/** The last state frame. Read by the handlers; never written by them. */
let state = null;
let sets = null;
let freeRunning = false;

/* -- talking to the daemon ------------------------------------------------ */

async function call(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    // The daemon's refusals are written to be shown to a person, so show them.
    const detail = payload?.detail ?? payload?.error ?? response.statusText;
    banner(typeof detail === "string" ? detail : JSON.stringify(detail));
    throw new Error(detail);
  }
  clearBanner();
  return payload;
}

/** Fire and forget: a refusal is already on screen, and there is nothing to add. */
const send = (method, path, body) => call(method, path, body).catch(() => {});

function banner(message, kind = "error") {
  const el = $("banner");
  el.textContent = message;
  el.className = kind === "info" ? "banner info" : "banner";
  el.hidden = false;
}

function clearBanner() {
  $("banner").hidden = true;
}

/* -- the state stream ----------------------------------------------------- */

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/api/stream`);

  socket.onopen = () => {
    $("link-state").textContent = "live";
  };
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.kind === "state") {
      state = message.state;
      render();
      refreshSets();
    }
  };
  socket.onclose = () => {
    // The daemon restarts more often than the browser tab does, so reconnect
    // rather than making somebody press reload.
    $("link-state").textContent = "reconnecting…";
    setTimeout(connect, 1000);
  };
  socket.onerror = () => socket.close();
}

async function refreshSets() {
  sets = await call("GET", "/api/sets").catch(() => null);
  if (sets) renderSets();
}

/* -- vocabulary ----------------------------------------------------------- */

/*
 * The counters table's columns, in the order VStim's Trial Type Manager shows
 * them. The header is the abbreviation an experimenter already reads; the title
 * is the outcome's real name, because nobody should have to remember that
 * "VRloss" is a lost video frame.
 */
const OUTCOME_COLUMNS = [
  ["HIT", "Hit", "Correct response"],
  ["WRONG_RESPONSE", "Wrong", "Wrong response"],
  ["EARLY_HIT", "EHit", "Correct response on an early-release occasion"],
  ["EARLY_WRONG_RESPONSE", "EWrong", "Wrong response on an early-release occasion"],
  ["EARLY", "Early", "Responded before the window opened"],
  ["LATE", "Late", "Responded after the window closed"],
  ["EYE_ERROR", "Eye", "Gaze left the fixation window"],
  ["NOT_STARTED", "NoStart", "A start signal was required and never given"],
  ["INEXPECTED_START_SIGNAL", "Inexp", "Start signal in an interval that is not a start interval"],
  ["WRONG_START_SIGNAL", "WrgStrt", "The wrong start signal was given"],
  ["CANCELLED", "Canc", "Aborted by the experimenter"],
];

/** Outcome buttons for driving one trial by hand, with their .tdr codes. */
const OUTCOMES = [
  ["HIT", 1],
  ["WRONG_RESPONSE", 2],
  ["EARLY_HIT", 3],
  ["EARLY_WRONG_RESPONSE", 4],
  ["EARLY", 5],
  ["LATE", 6],
  ["EYE_ERROR", 7],
  ["NOT_STARTED", 0],
  ["INEXPECTED_START_SIGNAL", 8],
  ["WRONG_START_SIGNAL", 9],
];

const ORDERINGS = [
  ["random_in_round", "Random in round", "One round in the bag: every round holds exactly the configured weights."],
  ["random_in_experiment", "Random in experiment", "Every round in the bag at once: the experiment is balanced, single rounds are not."],
  ["ascending", "Ascending", "Lowest trial type index first, strictly in order."],
  ["descending", "Descending", "Highest trial type index first - the mirror of ascending."],
  ["random_with_replacement", "Random with replacement", "Each trial an independent draw on the weights. Runs of one condition are longer than people expect."],
];

const CRITERIA = [
  ["accepted_trials", "accepted trials"],
  ["hits", "hits"],
  ["all_trials", "all completed trials"],
];

/** The eleven accept flags, plus the two vetoes that cut across every outcome. */
const ACCEPT_FIELDS = [
  ["hit", "Hit"],
  ["wrong_response", "Wrong"],
  ["early_hit", "Early hit"],
  ["early_wrong_response", "Early wrong"],
  ["early", "Early"],
  ["late", "Late"],
  ["eye_error", "Eye error"],
  ["not_started", "Not started"],
  ["inexpected_start_signal", "Inexp. start"],
  ["wrong_start_signal", "Wrong start"],
  ["cancelled", "Cancelled"],
];

const SIM_FIELDS = [
  ["hit_rate", "hit rate"],
  ["not_started_rate", "not started"],
  ["eye_error_rate", "eye error"],
  ["early_rate", "early"],
  ["frame_loss_rate", "frame loss"],
  ["imprecise_fixation_rate", "imprecise fix."],
];

/* -- rendering ------------------------------------------------------------ */

function render() {
  if (!state) return;
  renderPills();
  renderCurrent();
  renderFacts();
  renderCounters();
  renderTrialLog();
  renderConfig();
  renderButtons();
}

function renderPills() {
  const pills = [];
  pills.push(state.running ? ["running", "on"] : [state.armed ? "stopped" : "not armed", ""]);
  if (state.recording) pills.push(["recording", "rec"]);
  else if (state.paused) pills.push(["paused", "warn"]);
  if (state.policy.origin !== "default") pills.push([`policy: ${state.policy.name}`, ""]);
  if (state.policy_errors.length) pills.push([`${state.policy_errors.length} policy errors`, "warn"]);

  $("status-pills").innerHTML = pills
    .map(([text, cls]) => `<span class="pill ${cls}">${escape(text)}</span>`)
    .join("");
}

function renderCurrent() {
  const el = $("current-trial");
  const trial = state.current;
  if (trial) {
    el.textContent =
      `trial ${trial.trial_number} · ${trial.set_name} / ${trial.trial_type_name || `#${trial.trial_type_index}`}\n` +
      `no. ${trial.trial_type_number}${trial.statemachine_graph ? ` · ${trial.statemachine_graph}` : ""} · ${trial.reward_ms} ms` +
      (trial.recording ? " · recording" : trial.paused ? " · pausing" : "");
    return;
  }
  const last = state.last;
  if (last) {
    const mark = last.accepted ? "accepted" : `not accepted — ${last.refusal_reason}`;
    el.textContent = `between trials\nlast: ${last.outcome.name}, ${mark}`;
    return;
  }
  el.textContent = state.stop_reason ? `stopped: ${state.stop_reason}` : "between trials";
}

function renderFacts() {
  const p = state.set_progress;
  const facts = [
    ["set", state.set_name],
    ["trials started", state.trials_started],
    ["round", `${state.rounds_completed} / ${state.rounds_configured}`],
    ["left in round", `${state.trials_remaining} / ${state.trials_per_round}`],
    ["accepted", `${state.totals.accepted} of ${state.totals.total}`],
    ["hit rate", state.totals.hit_rate === null ? "–" : pct(state.totals.hit_rate)],
    ["in this set", `${p.accepted_trials} acc · ${p.hits} hits`],
    ["seed", state.seed],
  ];
  if (state.stop_reason) facts.push(["stopped", state.stop_reason]);

  $("session-facts").innerHTML = facts
    .map(([k, v]) => `<dt>${escape(k)}</dt><dd>${escape(String(v))}</dd>`)
    .join("");
}

function renderCounters() {
  const rows = state.counters;
  const extended = state.config.extend_trial_type_number;

  const header =
    "<thead><tr>" +
    th("No.", "left") +
    th("Trial type", "left name") +
    th("#Trials", "", "Weight: how many of this type make one round") +
    th("Graph", "", "Name of the state graph this type runs") +
    th("Rew", "", "Reward the type is worth, in ms") +
    th("Remain", "sep", "Still to run in the round or experiment") +
    th("P(next)", "", "Chance of being drawn next by the ordering") +
    th("All", "sep", "Every outcome reported — counted") +
    th("Accept", "", "Outcomes that consumed a slot in the round — accepted") +
    OUTCOME_COLUMNS.map(([, short, title], i) => th(short, i === 0 ? "sep" : "", title)).join("") +
    th("VRloss", "sep", "Trials that lost at least one video frame") +
    "</tr></thead>";

  const body = rows
    .map((row) => {
      const cells = [
        td(extended ? row.trial_type_number : row.index, "left"),
        td(row.name || `type ${row.index}`, "left name"),
        td(row.trials_per_round),
        td(row.statemachine_graph || "–", "left"),
        td(row.reward_ms),
        td(row.remaining, "sep"),
        `<td class="p-next">${row.p_next > 0 ? pct(row.p_next) : "–"}</td>`,
        td(row.total, "sep"),
        td(row.accepted),
        ...OUTCOME_COLUMNS.map(([key], i) => td(row.by_outcome[key] ?? 0, i === 0 ? "sep" : "")),
        td(row.frame_loss, "sep"),
      ];
      return `<tr>${cells.join("")}</tr>`;
    })
    .join("");

  const t = state.totals;
  const total =
    "<tr class='total'>" +
    [
      td("", "left"),
      td("Total", "left name"),
      td(state.trials_per_round),
      td(""),
      td(""),
      td(state.trials_remaining, "sep"),
      td(""),
      td(t.total, "sep"),
      td(t.accepted),
      ...OUTCOME_COLUMNS.map(([key], i) => td(t.by_outcome[key] ?? 0, i === 0 ? "sep" : "")),
      td(t.frame_loss, "sep"),
    ].join("") +
    "</tr>";

  $("counters").innerHTML = `${header}<tbody>${body}${total}</tbody>`;
  $("counters-note").textContent = extended
    ? "counters banked per set — trial type numbers extended by the set number"
    : "one counter bank shared by every set";
}

function renderTrialLog() {
  const rows = [...state.recent].reverse();
  if (!rows.length) {
    $("trial-log").innerHTML = "<tbody><tr><td class='left'>no trials yet</td></tr></tbody>";
    return;
  }
  const header =
    "<thead><tr>" +
    th("#", "left") +
    th("Set", "left") +
    th("Type", "left") +
    th("Outcome", "left") +
    th("RT") +
    th("A", "", "Accepted — did it consume a slot in the round?") +
    th("Why not", "left") +
    "</tr></thead>";
  const body = rows
    .map((r) => {
      const mark = r.accepted
        ? "<span class='accepted-mark'>✓</span>"
        : "<span class='refused-mark'>✗</span>";
      return (
        "<tr>" +
        td(r.trial.trial_number, "left") +
        td(r.trial.set_name, "left") +
        td(r.trial.trial_type_name || r.trial.trial_type_index, "left") +
        td(r.outcome.name, "left") +
        td(r.outcome.reaction_time_ms === null ? "–" : r.outcome.reaction_time_ms.toFixed(0)) +
        `<td>${mark}</td>` +
        td(r.refusal_reason ?? "", "left") +
        "</tr>"
      );
    })
    .join("");
  $("trial-log").innerHTML = `${header}<tbody>${body}</tbody>`;
}

function renderConfig() {
  const c = state.config;
  set("cfg-ordering", c.ordering);
  set("cfg-rounds", c.rounds);
  check("cfg-avoid-repeat", c.avoid_repeat);
  check("cfg-extend", c.extend_trial_type_number);
  check("cfg-stop-rounds", c.stop_when_rounds_done);
  check("cfg-stop-after-on", c.stop_after_trials !== null);
  set("cfg-stop-after", c.stop_after_trials ?? 100);
  set("cfg-stop-criterion", c.stop_criterion);
  $("cfg-stop-after").disabled = c.stop_after_trials === null;
  $("cfg-stop-criterion").disabled = c.stop_after_trials === null;

  const help = ORDERINGS.find(([value]) => value === c.ordering);
  $("ordering-help").textContent = help ? help[2] : "";

  // Arm-time settings are refused while a session runs; grey them out rather
  // than letting somebody press one and read a refusal.
  $("cfg-extend").disabled = state.running;

  for (const [field] of ACCEPT_FIELDS) check(`acc-${field}`, c.acceptance[field]);
  check("acc-frame_loss", c.acceptance.frame_loss);
  check("acc-imprecise_fixation", c.acceptance.imprecise_fixation);
}

function renderButtons() {
  $("btn-arm").disabled = state.running;
  $("btn-stop").disabled = !state.running;
  $("btn-rec-start").disabled = !state.running || state.recording;
  $("btn-rec-pause").disabled = !state.running || !state.recording;
  $("btn-rec-resume").disabled = !state.running || !state.paused;
  $("btn-rec-stop").disabled = !state.running || (!state.recording && !state.paused);

  const inFlight = state.current !== null;
  $("btn-next-trial").disabled = !state.running || inFlight;
  $("btn-cancel-trial").disabled = !inFlight;
  for (const button of document.querySelectorAll("#outcome-buttons button")) {
    button.disabled = !inFlight;
  }
  for (const button of document.querySelectorAll("[data-step]")) {
    button.disabled = !state.running || inFlight;
  }
  $("btn-free-run").disabled = !state.running;
  $("btn-free-run").classList.toggle("active", freeRunning);
  $("btn-free-run").textContent = freeRunning ? "Stop free run" : "Free run";
}

function renderSets() {
  $("chain-problem").hidden = !sets.chain_problem;
  $("chain-problem").textContent = sets.chain_problem ?? "";

  $("sets").innerHTML = sets.sets
    .map((s) => {
      const rule = s.switch_rule;
      const active = s.active;
      const progress = active && state ? state.set_progress : null;

      // Only the loaded set has progress towards its rule - every other set's
      // block starts from nothing whenever it is loaded, so showing 0/20 next
      // to one would read as "started and got nowhere" rather than "not
      // started".
      const armed = rule.enabled && rule.target && rule.count > 0;
      let ruleLine;
      if (armed && progress) {
        ruleLine =
          `after <strong>${progress.reached}/${rule.count}</strong> ${labelOf(CRITERIA, rule.criterion)} ` +
          `→ <strong>${escape(rule.target)}</strong>`;
      } else if (armed) {
        ruleLine =
          `after <strong>${rule.count}</strong> ${labelOf(CRITERIA, rule.criterion)} ` +
          `→ <strong>${escape(rule.target)}</strong>`;
      } else {
        ruleLine = "no switch rule — the sequence ends here";
      }

      const fraction = armed && progress ? Math.min(1, progress.reached / rule.count) : 0;

      return `
        <div class="set ${active ? "active" : ""}">
          <div class="set-head">
            <span class="set-name">${escape(s.name)}</span>
            <span class="set-meta">#${s.set_number} · ${s.trial_types.length} types · ${s.trials_per_round}/round</span>
          </div>
          <div class="set-rule">${ruleLine}</div>
          ${armed && progress ? `<div class="bar-track"><div class="bar-fill" style="width:${(fraction * 100).toFixed(1)}%"></div></div>` : ""}
          ${s.runnable ? "" : "<div class='set-rule'><em>every weight is zero — this set cannot run</em></div>"}
          <div class="btn-row">
            <button data-load-set="${escape(s.name)}" ${active || !s.runnable ? "disabled" : ""}>Load</button>
          </div>
        </div>`;
    })
    .join("");

  for (const button of document.querySelectorAll("[data-load-set]")) {
    button.onclick = () => send("POST", `/api/sets/${encodeURIComponent(button.dataset.loadSet)}/load`);
  }
}

/* -- building the static controls ----------------------------------------- */

function buildControls() {
  $("cfg-ordering").innerHTML = ORDERINGS.map(
    ([value, label]) => `<option value="${value}">${label}</option>`,
  ).join("");
  $("cfg-stop-criterion").innerHTML = CRITERIA.map(
    ([value, label]) => `<option value="${value}">${label}</option>`,
  ).join("");

  $("acceptance").innerHTML =
    ACCEPT_FIELDS.map(
      ([field, label]) =>
        `<label><input type="checkbox" id="acc-${field}" data-accept="${field}" />${label}</label>`,
    ).join("") +
    `<div class="veto">
       <label><input type="checkbox" id="acc-frame_loss" data-accept="frame_loss" />with frame loss</label>
       <label><input type="checkbox" id="acc-imprecise_fixation" data-accept="imprecise_fixation" />with imprecise fixation</label>
     </div>`;

  $("outcome-buttons").innerHTML = OUTCOMES.map(
    ([name, code]) =>
      `<button data-outcome="${name}" title="code ${code}">${name.toLowerCase().replace(/_/g, " ")}</button>`,
  ).join("");

  $("sim-sliders").innerHTML = SIM_FIELDS.map(
    ([field, label]) =>
      `<label for="sim-${field}">${label}</label>
       <output id="out-${field}"></output>
       <input id="sim-${field}" data-sim="${field}" type="range" min="0" max="1" step="0.01"
              style="grid-column: 1 / -1" />`,
  ).join("");
}

/* -- wiring --------------------------------------------------------------- */

function wire() {
  $("btn-arm").onclick = () => send("POST", "/api/session/arm");
  $("btn-stop").onclick = () => send("POST", "/api/session/stop");
  $("btn-rec-start").onclick = () => send("POST", "/api/session/recording/start");
  $("btn-rec-pause").onclick = () => send("POST", "/api/session/recording/pause");
  $("btn-rec-resume").onclick = () => send("POST", "/api/session/recording/resume");
  $("btn-rec-stop").onclick = () => send("POST", "/api/session/recording/stop");
  $("btn-reset-rounds").onclick = () => send("POST", "/api/config/reset-rounds");
  $("btn-reset-counters").onclick = () => send("POST", "/api/config/reset-counters");

  for (const button of document.querySelectorAll("[data-step]")) {
    button.onclick = () =>
      send("POST", "/api/debug/step", { trials: Number(button.dataset.step) });
  }

  $("btn-free-run").onclick = async () => {
    const status = await call("PUT", "/api/debug/free-run", {
      running: !freeRunning,
      interval_ms: Number($("free-run-interval").value) || 250,
    }).catch(() => null);
    if (status) {
      freeRunning = status.running;
      renderButtons();
    }
  };

  $("btn-next-trial").onclick = () => send("POST", "/api/trial/next");
  $("btn-cancel-trial").onclick = () =>
    send("POST", "/api/trial/cancel", { reason: "cancelled from the web UI" });

  for (const button of document.querySelectorAll("[data-outcome]")) {
    button.onclick = () =>
      send("POST", "/api/trial/outcome", {
        // The daemon refuses an outcome for any trial but the one in flight.
        trial_id: state?.current?.trial_number ?? 0,
        outcome: button.dataset.outcome,
        manipulandum: "SIMULATED",
        // Both modifiers can veto an otherwise accepted outcome on their own,
        // which is the thing this pair of checkboxes exists to demonstrate.
        precise_fixation: !$("mod-imprecise").checked,
        frame_loss: $("mod-frame-loss").checked ? { interval: 0, frame: 0 } : null,
        simulated: true,
      });
  }

  const patch = (body) => send("PATCH", "/api/config", body);

  $("cfg-ordering").onchange = (e) => patch({ ordering: e.target.value });
  $("cfg-rounds").onchange = (e) => patch({ rounds: Number(e.target.value) });
  $("cfg-avoid-repeat").onchange = (e) => patch({ avoid_repeat: e.target.checked });
  $("cfg-extend").onchange = (e) => patch({ extend_trial_type_number: e.target.checked });
  $("cfg-stop-rounds").onchange = (e) => patch({ stop_when_rounds_done: e.target.checked });
  $("cfg-stop-criterion").onchange = (e) => patch({ stop_criterion: e.target.value });

  // stop_after_trials carries its own "off": null means no limit, and 0 is how
  // the wire says "clear it" - see ConfigPatch.
  const stopAfter = () =>
    patch({
      stop_after_trials: $("cfg-stop-after-on").checked
        ? Number($("cfg-stop-after").value) || 1
        : 0,
    });
  $("cfg-stop-after-on").onchange = stopAfter;
  $("cfg-stop-after").onchange = stopAfter;

  for (const box of document.querySelectorAll("[data-accept]")) {
    box.onchange = () => {
      const acceptance = { ...state.config.acceptance };
      for (const b of document.querySelectorAll("[data-accept]")) {
        acceptance[b.dataset.accept] = b.checked;
      }
      patch({ acceptance });
    };
  }

  for (const slider of document.querySelectorAll("[data-sim]")) {
    slider.oninput = () => {
      $(`out-${slider.dataset.sim}`).textContent = Number(slider.value).toFixed(2);
    };
    slider.onchange = async () => {
      const settings = {};
      for (const s of document.querySelectorAll("[data-sim]")) {
        settings[s.dataset.sim] = Number(s.value);
      }
      await send("PUT", "/api/debug/sim", settings);
    };
  }
}

async function loadSim() {
  const sim = await call("GET", "/api/debug/sim").catch(() => null);
  if (!sim) return;
  for (const [field] of SIM_FIELDS) {
    $(`sim-${field}`).value = sim[field];
    $(`out-${field}`).textContent = Number(sim[field]).toFixed(2);
  }
}

/* -- small helpers -------------------------------------------------------- */

const escape = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const pct = (fraction) => `${(fraction * 100).toFixed(1)}%`;

const th = (label, cls = "", title = "") =>
  `<th class="${cls}"${title ? ` title="${escape(title)}"` : ""}>${escape(label)}</th>`;

const td = (value, cls = "") => {
  const zero = value === 0 ? " zero" : "";
  return `<td class="${cls}${zero}">${escape(value)}</td>`;
};

const labelOf = (pairs, value) => pairs.find(([v]) => v === value)?.[1] ?? value;

/** Set a control's value, unless somebody is typing into it. */
function set(id, value) {
  const el = $(id);
  if (el !== document.activeElement) el.value = value;
}

function check(id, value) {
  const el = $(id);
  if (el && el !== document.activeElement) el.checked = value;
}

buildControls();
wire();
loadSim();
connect();
refreshSets();
