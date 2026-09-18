// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The one place in the UI that knows a network exists.
//
// Every element takes a `base` attribute rather than assuming same-origin,
// because the point of the `/elements/` contract is that a console served
// from somewhere else can drop `<triald-session>` into its own page. An
// element that called `fetch("/api/state")` would work perfectly on triald's
// own page and silently talk to the console's host everywhere else.
//
// Routes here mirror dev/API.md exactly; a panel is written against this
// client and never against a URL of its own.

/// A refusal from the daemon: an `ErrorModel` with a 4xx status.
export class DaemonRefusedTheRequest extends Error {
  constructor(status, body) {
    const detail = (body && body.detail) || `HTTP ${status}`;
    super(detail);
    this.name = "DaemonRefusedTheRequest";
    this.status = status;
    this.code = (body && body.error) || "http_error";
    this.detail = detail;
    this.context = (body && body.context) || "";
  }
}

export class DaemonApiClient {
  constructor(baseUrl) {
    this.baseUrl = (baseUrl || "").replace(/\/+$/, "");
  }

  urlFor(path) {
    return `${this.baseUrl}${path}`;
  }

  /// The WebSocket origin, derived from `base` and falling back to this
  /// page's. A relative `base` is the normal case on triald's own page, and
  /// `new URL(path, location.href)` is what turns it into something `new
  /// WebSocket()` will accept -- it refuses a relative URL outright.
  webSocketUrlFor(path) {
    const absolute = new URL(this.urlFor(path), globalThis.location?.href ?? "http://localhost/");
    absolute.protocol = absolute.protocol === "https:" ? "wss:" : "ws:";
    return absolute.toString();
  }

  async request(method, path, body) {
    const response = await fetch(this.urlFor(path), {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let parsed = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = null;
    }
    if (!response.ok) {
      // FastAPI's own 422 shape names the field in `detail`, which is an
      // array rather than a sentence. Flatten it here so a panel has one
      // thing to show whichever half refused it.
      if (parsed && Array.isArray(parsed.detail)) {
        const first = parsed.detail[0] || {};
        parsed = {
          error: "validation_failed",
          detail: first.msg || "the request did not validate",
          context: (first.loc || []).join("."),
        };
      }
      throw new DaemonRefusedTheRequest(response.status, parsed);
    }
    return parsed;
  }

  get(path) {
    return this.request("GET", path);
  }

  post(path, body) {
    return this.request("POST", path, body === undefined ? {} : body);
  }

  put(path, body) {
    return this.request("PUT", path, body);
  }

  patch(path, body) {
    return this.request("PATCH", path, body);
  }

  delete(path) {
    return this.request("DELETE", path);
  }

  // ------------------------------------------------------------- the API ---

  readState() {
    return this.get("/api/state");
  }

  openStateStream() {
    return new WebSocket(this.webSocketUrlFor("/api/stream"));
  }

  // -- session lifecycle --------------------------------------------------

  arm() {
    return this.post("/api/session/arm");
  }

  stop(reason) {
    const query = reason ? `?reason=${encodeURIComponent(reason)}` : "";
    return this.post(`/api/session/stop${query}`);
  }

  startRecording() {
    return this.post("/api/session/recording/start");
  }

  pauseRecording() {
    return this.post("/api/session/recording/pause");
  }

  resumeRecording() {
    return this.post("/api/session/recording/resume");
  }

  stopRecording() {
    return this.post("/api/session/recording/stop");
  }

  // -- the trial loop -------------------------------------------------------

  nextTrial() {
    return this.post("/api/trial/next");
  }

  reportOutcome(report) {
    return this.post("/api/trial/outcome", report);
  }

  cancelTrial(reason) {
    return this.post("/api/trial/cancel", { reason: reason || "cancelled by the experimenter" });
  }

  // -- sets -----------------------------------------------------------------

  readSets() {
    return this.get("/api/sets");
  }

  putSet(name, set) {
    return this.put(`/api/sets/${encodeURIComponent(name)}`, set);
  }

  deleteSet(name) {
    return this.delete(`/api/sets/${encodeURIComponent(name)}`);
  }

  loadSet(name) {
    return this.post(`/api/sets/${encodeURIComponent(name)}/load`);
  }

  // -- config -----------------------------------------------------------------

  readConfig() {
    return this.get("/api/config");
  }

  patchConfig(patch) {
    return this.patch("/api/config", patch);
  }

  resetRounds() {
    return this.post("/api/config/reset-rounds");
  }

  resetCounters() {
    return this.post("/api/config/reset-counters");
  }

  // -- policy -----------------------------------------------------------------

  readPolicy(withSource) {
    const query = withSource ? "?source=true" : "";
    return this.get(`/api/policy${query}`);
  }

  checkPolicy(name, source) {
    return this.post("/api/policy/check", { name, source });
  }

  loadPolicy(name, source) {
    return this.put("/api/policy", { name, source });
  }

  clearPolicy() {
    return this.delete("/api/policy");
  }

  // -- events -----------------------------------------------------------------

  note(text) {
    return this.post("/api/events/note", { text });
  }

  // -- debug (the simulated subject) -------------------------------------

  readSim() {
    return this.get("/api/debug/sim");
  }

  setSim(settings) {
    return this.put("/api/debug/sim", settings);
  }

  step(trials) {
    return this.post("/api/debug/step", { trials: trials ?? 1 });
  }

  readFreeRun() {
    return this.get("/api/debug/free-run");
  }

  setFreeRun(running, intervalMs) {
    return this.put("/api/debug/free-run", { running, interval_ms: intervalMs ?? 250 });
  }
}
