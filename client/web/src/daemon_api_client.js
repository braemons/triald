// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The one place in this UI that knows a network exists.
//
// It speaks **gRPC-Web, binary** to the eight services in `proto/triald/v1/`,
// over the same port the panels themselves are served from —
// `daemon/src/triald/api/web_edge.py` answers it in the daemon, so there is no
// proxy to deploy and nothing to configure.
//
// The same transport statemachined's and mousewheeld's panels use, where
// `tonic-web` answers it in process; this daemon is Python and the edge is
// written against the protocol specification instead. It used to be Connect,
// whose transport sends JSON unless told otherwise — and did. gRPC-Web has no
// JSON codec, so what crosses is protobuf, as it is on every other wire in the
// family (`contracts/DAEMON_LAYOUT.md`), refusals included.
//
// Every element takes a `base` attribute rather than assuming same-origin,
// because the point of the `/elements/` contract is that a console served from
// somewhere else drops `<triald-session>` into its own page. An element that
// called the daemon at its own origin would work perfectly on the rig's own
// page and silently talk to the console's host everywhere else.
//
// **A panel never sees a protobuf message.** This is the browser's half of the
// convert seam, and it is the same rule the daemon keeps in `api/convert/`:
// the generated types stop here. What a panel hands over and gets back is
// protobuf's JSON mapping — `fromJson` on the way out, `toJson` on the way
// back — a plain object with the field names the proto spells, which refuses
// an unknown field in a request by name, in the browser, before anything is
// encoded. The JSON never leaves this file: the wire carries the binary.
//
// Those names are the proto's own: every field in `proto/triald/v1/` pins
// `json_name` to its snake_case spelling, so `trial_number` is `trial_number`
// in the proto, on the wire, in the record on disk and here. That is the
// family's rule about a name travelling unchanged, applied to JSON.
//
// Methods are named after what they ask for rather than after their rpcs, so a
// panel reads as what it wants.

import { createClient, ConnectError, Code } from "@connectrpc/connect";
import { createGrpcWebTransport } from "@connectrpc/connect-web";
import { fromBinary, fromJson, toJson } from "@bufbuild/protobuf";

import {
  State as StateService,
  Session as SessionService,
  Trial as TrialService,
  SetStore as SetStoreService,
  Config as ConfigService,
  Policy as PolicyService,
  Events as EventsService,
  Debug as DebugService,
} from "../gen/triald/v1/service_pb.js";
import { ErrorSchema } from "../gen/triald/v1/common_pb.js";

export { TrialCountCriterionSchema, OrderingSchema } from "../gen/triald/v1/common_pb.js";
export { PolicyOriginSchema } from "../gen/triald/v1/policy_pb.js";

/// One enum value, as a word a person reads.
///
/// `TRIAL_COUNT_CRITERION_HITS` is the right name on the wire and the wrong
/// thing to show an experimenter, and the two were the same string for as long
/// as a panel printed what it received. protobuf's style prefixes every value
/// with its enum's name so that two enums can both have a `HITS`; the
/// descriptor knows that prefix, so stripping it is a fact about the schema
/// rather than a string trim somebody has to keep matching.
///
/// Unknown values come back as themselves. A daemon newer than the page it is
/// serving is a real situation, and showing the raw name says more than
/// "unknown" does.
export function wordFor(enumSchema, value) {
  const found = enumSchema.values.find((each) => each.name === value || each.localName === value);
  if (found === undefined) return value ?? "";
  return found.localName.toLowerCase().replace(/_/g, " ");
}

/// A refusal from the daemon: the status, the machine-readable code, the
/// sentence, and the context that names what to change.
///
/// `context` is why this is a class rather than a thrown string. An outcome
/// reported for the wrong trial names the trial it expected; a UI that shows
/// only `failed_precondition` throws exactly that away.
///
/// The three fields come from `triald.v1.Error` in the error's details, not
/// from parsing the message: a client that reads a sentence to find out which
/// refusal it was is a client that breaks when the sentence is reworded.
export class DaemonRefusedTheRequest extends Error {
  constructor(status, body) {
    super(body.detail || status);
    this.name = "DaemonRefusedTheRequest";
    this.status = status;
    this.code = body.error || "rpc_failed";
    this.detail = body.detail || status;
    this.context = body.context || "";
  }

  /// Whatever the transport threw, as a refusal.
  ///
  /// A daemon that is not running, a CORS rejection and a cancelled stream all
  /// arrive here too. They have no `triald.v1.Error` — nothing refused
  /// anything, the call never landed — so the code is the gRPC one and the
  /// detail is what the browser said.
  static from(thrown) {
    if (thrown instanceof DaemonRefusedTheRequest) return thrown;
    const failure = ConnectError.from(thrown);
    // gRPC logs spell codes `not_found`; the generated enum spells them
    // `NotFound`. Show the one the daemon's own logs and the network tab show.
    const status = (Code[failure.code] ?? "Unknown").replace(/(?<=[a-z])(?=[A-Z])/g, "_").toLowerCase();
    return new DaemonRefusedTheRequest(status, refusalIn(failure) ?? { detail: failure.rawMessage });
  }
}

/// The trailer `triald.v1.Error` rides in: the key the gRPC port uses, so a
/// browser and a Python client read the same bytes from the same place.
const REFUSAL_METADATA_KEY = "triald-error-bin";

/// `triald.v1.Error` out of the trailing metadata, or `null`.
///
/// gRPC-Web carries a `-bin` metadata value base64-encoded, and without
/// padding, which `atob` will not take. The same shape statemachined's and
/// mousewheeld's clients read, because it is the same wire. An error with no
/// refusal is still an error; it just has no machine-readable code, which is
/// the case for everything that failed before reaching a servicer.
function refusalIn(failure) {
  const encoded = failure.metadata?.get(REFUSAL_METADATA_KEY);
  if (!encoded) return null;
  try {
    const padded = encoded + "=".repeat((4 - (encoded.length % 4)) % 4);
    const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    return toJson(ErrorSchema, fromBinary(ErrorSchema, bytes), { alwaysEmitImplicit: true });
  } catch {
    return null; // a refusal we cannot read is still a refusal; keep the sentence
  }
}

export class DaemonApiClient {
  constructor(baseUrl) {
    this.baseUrl = (baseUrl || "").replace(/\/+$/, "");
    const transport = createGrpcWebTransport({ baseUrl: this.baseUrl || "/" });
    this.state = createClient(StateService, transport);
    this.session = createClient(SessionService, transport);
    this.trial = createClient(TrialService, transport);
    this.sets = createClient(SetStoreService, transport);
    this.config = createClient(ConfigService, transport);
    this.policy = createClient(PolicyService, transport);
    this.events = createClient(EventsService, transport);
    this.debug = createClient(DebugService, transport);
  }

  /// One unary call: JSON in, JSON out, refusals as `DaemonRefusedTheRequest`.
  ///
  /// The descriptors come off the service rather than being named again here,
  /// so a request or response type that changes in the proto changes here by
  /// itself and cannot be half-updated.
  async call(client, method, request = {}) {
    try {
      const answer = await client[method.localName](fromJson(method.input, request));
      return toJson(method.output, answer, { alwaysEmitImplicit: true });
    } catch (failure) {
      throw DaemonRefusedTheRequest.from(failure);
    }
  }

  /// One server-streaming call, as an async iterable of JSON frames.
  ///
  /// `signal` is how a panel stops it — a stream with no way to end it is a
  /// stream that outlives the panel that opened it. `onHeader` is the moment
  /// the daemon accepted the call, which is what a "streaming" pill means: a
  /// quiet wire yields no frames for a while and is perfectly healthy.
  async *follow(client, method, request, { signal, onHeader } = {}) {
    try {
      const frames = client[method.localName](fromJson(method.input, request), { signal, onHeader });
      for await (const frame of frames) {
        yield toJson(method.output, frame, { alwaysEmitImplicit: true });
      }
    } catch (failure) {
      if (signal?.aborted) return; // our own close, not a failure
      throw DaemonRefusedTheRequest.from(failure);
    }
  }

  // ------------------------------------------------------ state & stream ---

  readState() {
    return this.call(this.state, StateService.method.readState);
  }

  /// The state stream. Frames are whole states and are coalesced under load,
  /// so a panel that missed three has missed nothing it could have used.
  followState(options) {
    return this.follow(this.state, StateService.method.watchState, {}, options);
  }

  // -------------------------------------------------- session lifecycle ---

  arm() {
    return this.call(this.session, SessionService.method.arm);
  }

  stop(reason) {
    return this.call(this.session, SessionService.method.stop, { reason: reason || "" });
  }

  startRecording() {
    return this.call(this.session, SessionService.method.startRecording);
  }

  pauseRecording() {
    return this.call(this.session, SessionService.method.pauseRecording);
  }

  resumeRecording() {
    return this.call(this.session, SessionService.method.resumeRecording);
  }

  stopRecording() {
    return this.call(this.session, SessionService.method.stopRecording);
  }

  // ------------------------------------------------------- the trial loop ---

  nextTrial() {
    return this.call(this.trial, TrialService.method.next);
  }

  reportOutcome(report) {
    return this.call(this.trial, TrialService.method.reportOutcome, report);
  }

  cancelTrial(reason) {
    return this.call(this.trial, TrialService.method.cancel, {
      reason: reason || "cancelled by the experimenter",
    });
  }

  // ------------------------------------------------------------------ sets ---

  readSets() {
    return this.call(this.sets, SetStoreService.method.readSets);
  }

  writeSet(name, set) {
    return this.call(this.sets, SetStoreService.method.writeSet, { name, set });
  }

  deleteSet(name) {
    return this.call(this.sets, SetStoreService.method.deleteSet, { name });
  }

  loadSet(name) {
    return this.call(this.sets, SetStoreService.method.loadSet, { name });
  }

  // ---------------------------------------------------------------- config ---

  readConfig() {
    return this.call(this.config, ConfigService.method.readConfig);
  }

  patchConfig(patch) {
    return this.call(this.config, ConfigService.method.patchConfig, patch);
  }

  resetRounds() {
    return this.call(this.config, ConfigService.method.resetRounds);
  }

  resetCounters() {
    return this.call(this.config, ConfigService.method.resetCounters);
  }

  // ---------------------------------------------------------------- policy ---

  readPolicy(withSource) {
    return this.call(this.policy, PolicyService.method.readPolicy, {
      source: withSource === true,
    });
  }

  checkPolicy(name, source) {
    return this.call(this.policy, PolicyService.method.checkPolicy, { name, source });
  }

  loadPolicy(name, source) {
    return this.call(this.policy, PolicyService.method.loadPolicy, { name, source });
  }

  clearPolicy() {
    return this.call(this.policy, PolicyService.method.clearPolicy);
  }

  // ---------------------------------------------------------------- events ---

  note(text) {
    return this.call(this.events, EventsService.method.note, { text });
  }

  // ------------------------------------------- debug (the simulated subject) ---

  readSim() {
    return this.call(this.debug, DebugService.method.readSim);
  }

  setSim(settings) {
    return this.call(this.debug, DebugService.method.writeSim, settings);
  }

  step(trials) {
    return this.call(this.debug, DebugService.method.step, { trials: trials ?? 1 });
  }

  readFreeRun() {
    return this.call(this.debug, DebugService.method.readFreeRun);
  }

  setFreeRun(running, intervalMs) {
    return this.call(this.debug, DebugService.method.writeFreeRun, {
      running,
      interval_ms: intervalMs ?? 250,
    });
  }
}
