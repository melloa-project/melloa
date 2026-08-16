import {
  ApiError,
  MelloaApi,
  type AuthenticatedOwner,
  type ConversationMessage,
  type ConversationProcessingStatus,
  type ConversationThread,
  type ConversationTurn,
  type ConversationTurnInspection,
  type DeliveryWorkStatus,
  type ComponentHealth,
  type MemoryInspection,
  type MediaItemMetadata,
  type MediaSourceStatus,
  type ModelActivityEntry,
  type ModelActivityReport,
  type OwnerHealthReport,
  type OwnerMediaCatalog,
  type SystemStatus,
} from "./api.js";
import {
  areas,
  defaultActivityWindow,
  deliveryRecoverySummary,
  formatCount,
  formatGbp,
  formatInstant,
  formatJson,
  messageBody,
  mutationCapabilities,
  parseActivityWindow,
  parseJsonObject,
  shortId,
  writeText,
  type AreaId,
} from "./view.js";

type ConsoleState = {
  principal: AuthenticatedOwner | null;
  status: SystemStatus | null;
  threads: readonly ConversationThread[];
  selectedThreadId: string | null;
  messages: readonly ConversationMessage[];
  processing: readonly ConversationProcessingStatus[];
  deliveries: readonly DeliveryWorkStatus[];
  turns: readonly ConversationTurn[];
  selectedTurnId: string | null;
  turnInspection: ConversationTurnInspection | null;
  memory: MemoryInspection | null;
  modelActivity: ModelActivityReport | null;
  healthDetail: OwnerHealthReport | null;
  mediaCatalog: OwnerMediaCatalog | null;
};

const shell = `
  <header class="masthead">
    <div class="brand-block">
      <p class="eyebrow">Melloa · private owner surface</p>
      <h1>Owner Console</h1>
      <p class="lede">Canonical conversation and inspectable system records for one owner and one persistent intelligence.</p>
    </div>
    <div class="boundary-panel" aria-label="Security boundary status">
      <span class="boundary"><i></i>Private network only</span>
      <span class="boundary" id="guardian-boundary"><i></i><span id="guardian-boundary-text">Guardian status loading</span></span>
      <span class="boundary"><i></i>Guardian read-only contract</span>
      <span class="boundary warning" id="external-boundary"><i></i><span id="external-boundary-text">External actions unverified</span></span>
    </div>
  </header>

  <div class="notice" id="notice" role="status" aria-live="polite" hidden></div>

  <main>
    <section class="auth-card" aria-labelledby="auth-title">
      <div>
        <p class="eyebrow">Owner authentication</p>
        <h2 id="auth-title">Sign in to private records</h2>
        <p class="muted" id="auth-description">Credentials are sent only to the same-origin core and are never stored by this console.</p>
      </div>
      <form id="auth-form" class="auth-form">
        <label>
          Owner credential
          <input id="owner-credential" name="credential" type="password" minlength="32" maxlength="4096" autocomplete="current-password" required />
        </label>
        <button class="primary" id="auth-submit" type="submit">Sign in</button>
      </form>
      <div class="session-summary" id="session-summary" hidden>
        <dl class="compact-list">
          <div><dt>Owner</dt><dd id="session-owner"></dd></div>
          <div><dt>Session expires</dt><dd id="session-expires"></dd></div>
          <div><dt>Mutation proof</dt><dd id="session-proof"></dd></div>
        </dl>
        <button class="quiet" id="logout" type="button">Sign out</button>
      </div>
    </section>

    <section class="status-strip" aria-labelledby="status-title">
      <div>
        <p class="eyebrow">Authority state</p>
        <h2 id="status-title">Fail closed until Guardian status is verified</h2>
        <p class="muted" id="status-detail">Reading the signed status projection.</p>
      </div>
      <dl>
        <div><dt>Contract milestone</dt><dd id="status-milestone">—</dd></div>
        <div><dt>External actions</dt><dd id="status-actions">Unverified</dd></div>
        <div><dt>Guardian sequence</dt><dd id="status-sequence">—</dd></div>
      </dl>
    </section>

    <nav class="area-nav" id="area-nav" aria-label="Owner Console areas"></nav>

    <section class="area-panel" id="panel-conversation" data-area-panel="conversation" aria-labelledby="conversation-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Canonical first-party record</p>
          <h2 id="conversation-title">Conversation</h2>
        </div>
        <p>Messages, citations, turns, and structured decisions share one channel-neutral history.</p>
      </div>
      <div class="conversation-layout">
        <aside class="panel-card thread-rail" aria-label="Conversation threads">
          <div class="panel-heading">
            <h3>Threads</h3>
            <span class="count" id="thread-count">0</span>
          </div>
          <details class="create-thread">
            <summary>New private thread</summary>
            <form id="thread-form" class="stack-form">
              <label>Title<input id="thread-title" maxlength="256" required /></label>
              <label>
                Sensitivity
                <select id="thread-sensitivity">
                  <option value="public">Public</option>
                  <option value="internal">Internal</option>
                  <option value="personal" selected>Personal</option>
                  <option value="sensitive">Sensitive</option>
                  <option value="highly_sensitive">Highly sensitive</option>
                  <option value="device_only">Device only</option>
                </select>
              </label>
              <label>Retention policy<input id="thread-retention" value="retention.owner-conversation" maxlength="255" required /></label>
              <button class="primary" id="thread-submit" type="submit" data-mutation>Create thread</button>
            </form>
          </details>
          <div class="thread-list" id="thread-list"></div>
        </aside>

        <section class="panel-card message-panel" aria-label="Selected conversation">
          <div class="panel-heading selected-thread-heading">
            <div>
              <p class="eyebrow" id="selected-thread-sensitivity">No thread selected</p>
              <h3 id="selected-thread-title">Choose a thread</h3>
            </div>
            <span class="state-chip" id="selected-thread-state">Idle</span>
          </div>
          <div class="message-list" id="message-list" aria-live="polite"></div>
          <form id="message-form" class="message-form">
            <label for="message-text">Message</label>
            <textarea id="message-text" rows="3" maxlength="100000" placeholder="Write to Melloa…" required></textarea>
            <div class="form-footer">
              <span class="form-hint">Submission retries keep one key until durable acceptance; provider retries continue from the canonical record.</span>
              <button class="primary" id="message-submit" type="submit" data-mutation>Send</button>
            </div>
          </form>
        </section>

        <aside class="panel-card turn-rail" aria-label="Structured turn inspection">
          <div class="panel-heading">
            <h3>Turns & decisions</h3>
            <span class="count" id="turn-count">0</span>
          </div>
          <div class="turn-list" id="turn-list"></div>
          <div class="turn-inspection" id="turn-inspection"></div>
        </aside>
      </div>
      <section class="panel-card delivery-panel" aria-labelledby="delivery-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Exact policy-bound side effect</p>
            <h3 id="delivery-title">Outbound delivery</h3>
          </div>
          <span class="count" id="delivery-count">0</span>
        </div>
        <div class="delivery-layout">
          <form id="delivery-form" class="stack-form delivery-form">
            <label>
              Canonical message
              <select id="delivery-message" required></select>
            </label>
            <label>
              Client adapter
              <input id="delivery-adapter" maxlength="128" placeholder="client.fake" required />
            </label>
            <label>
              Destination reference
              <input id="delivery-destination" maxlength="512" placeholder="synthetic:owner" required />
            </label>
            <p class="form-hint">Submission requires recent authentication and authorizes only this exact message, adapter, and destination. The current acceptance route is synthetic and performs no channel network call.</p>
            <button class="primary" id="delivery-submit" type="submit" data-sensitive-mutation>Authorize delivery</button>
          </form>
          <div class="delivery-list" id="delivery-list" aria-live="polite"></div>
        </div>
      </section>
    </section>

    <section class="area-panel" id="panel-timeline" data-area-panel="timeline" aria-labelledby="timeline-title" hidden>
      <div class="section-heading">
        <div><p class="eyebrow">Append-only history</p><h2 id="timeline-title">Timeline</h2></div>
        <p>The aggregate timeline API is not yet exposed. Canonical turn history and memory state changes remain available in their source views.</p>
      </div>
      <div class="placeholder-card">
        <span class="placeholder-mark">T</span>
        <div><h3>Aggregate projection pending</h3><p>No synthetic timeline is presented as real data. M1 will expose observations, interpretations, corrections, actions, and outcomes through an authenticated projection.</p></div>
      </div>
    </section>

    <section class="area-panel" id="panel-memory" data-area-panel="memory" aria-labelledby="memory-title" hidden>
      <div class="section-heading">
        <div><p class="eyebrow">Provenance-preserving controls</p><h2 id="memory-title">Memory</h2></div>
        <p>Inspect an assertion by record ID. Corrections append a new assertion; dispute and retraction append immutable state transitions.</p>
      </div>
      <form id="memory-form" class="lookup-form">
        <label>Assertion ID<input id="memory-id" autocomplete="off" placeholder="assertion_…" required /></label>
        <button class="primary" id="memory-inspect" type="submit" data-auth-only>Inspect</button>
      </form>
      <div class="memory-layout">
        <section class="panel-card memory-record" id="memory-record">
          <div class="empty-state"><strong>No assertion loaded</strong><span>Enter an owner-visible assertion ID to inspect value, provenance, and state history.</span></div>
        </section>
        <aside class="panel-card memory-actions" id="memory-actions" hidden>
          <div class="panel-heading"><h3>Owner controls</h3><span class="state-chip" id="memory-version">—</span></div>
          <p class="muted">These controls require a fresh in-memory CSRF proof and recent owner authentication.</p>
          <label>Expected version<input id="memory-expected-version" type="number" min="1" step="1" /></label>
          <label>Corrected JSON object<textarea id="memory-correction" rows="9" spellcheck="false"></textarea></label>
          <button class="primary" id="memory-correct" type="button" data-sensitive-mutation>Append correction</button>
          <div class="split-actions">
            <button class="quiet warning-button" id="memory-dispute" type="button" data-sensitive-mutation>Dispute</button>
            <button class="quiet danger-button" id="memory-retract" type="button" data-sensitive-mutation>Retract</button>
          </div>
        </aside>
      </div>
    </section>

    <section class="area-panel" id="panel-runs" data-area-panel="runs" aria-labelledby="runs-title" hidden>
      <div class="section-heading">
        <div><p class="eyebrow">Bounded owner activity</p><h2 id="runs-title">Runs & Decisions</h2></div>
        <p>Redacted model route, token, cost, and external-disclosure records. Hidden chain-of-thought is never shown.</p>
      </div>
      <form id="activity-form" class="lookup-form date-window">
        <label>From (UTC)<input id="activity-from" type="date" required /></label>
        <label>To, exclusive (UTC)<input id="activity-to" type="date" required /></label>
        <button class="primary" id="activity-load" type="submit" data-auth-only>Load activity</button>
      </form>
      <dl class="metric-grid" id="activity-metrics">
        <div><dt>Total runs</dt><dd id="metric-runs">—</dd></div>
        <div><dt>External disclosures</dt><dd id="metric-disclosures">—</dd></div>
        <div><dt>Input tokens</dt><dd id="metric-input">—</dd></div>
        <div><dt>Output tokens</dt><dd id="metric-output">—</dd></div>
        <div><dt>Total cost</dt><dd id="metric-cost">—</dd></div>
        <div><dt>External cost</dt><dd id="metric-external-cost">—</dd></div>
      </dl>
      <div class="activity-list" id="activity-list"></div>
    </section>

    <section class="area-panel" id="panel-media" data-area-panel="media" aria-labelledby="media-title" hidden>
      <div class="section-heading">
        <div><p class="eyebrow">Retained evidence</p><h2 id="media-title">Media</h2></div>
        <p>Authenticated metadata only: source state, missing intervals, event boundaries, confidence, retention expiry, and disclosure IDs. This console exposes no blob URL.</p>
      </div>
      <dl class="metric-grid media-metrics">
        <div><dt>Capture</dt><dd id="media-capture">—</dd></div>
        <div><dt>Content access</dt><dd id="media-content">—</dd></div>
        <div><dt>Sources</dt><dd id="media-source-count">—</dd></div>
        <div><dt>Retained records</dt><dd id="media-item-count">—</dd></div>
      </dl>
      <div class="media-layout">
        <section class="panel-card">
          <div class="panel-heading"><h3>Source health</h3><span class="state-chip">Metadata</span></div>
          <div class="media-source-list" id="media-source-list"></div>
        </section>
        <section class="panel-card">
          <div class="panel-heading"><h3>Retention records</h3><span class="state-chip">No blob route</span></div>
          <div class="media-item-list" id="media-item-list"></div>
        </section>
      </div>
    </section>

    <section class="area-panel" id="panel-operations" data-area-panel="operations" aria-labelledby="operations-title" hidden>
      <div class="section-heading">
        <div><p class="eyebrow">Read-only service state</p><h2 id="operations-title">Operations</h2></div>
        <p>The ordinary console reads Guardian status but cannot mutate Guardian authority, policy, or recovery state.</p>
      </div>
      <div class="operations-grid">
        <section class="panel-card"><h3>Current system projection</h3><pre id="operations-status">Status unavailable.</pre></section>
        <section class="panel-card">
          <div class="panel-heading"><h3>Authenticated component health</h3><span class="state-chip" id="operations-health-state">—</span></div>
          <div class="health-list" id="operations-health"></div>
        </section>
        <section class="panel-card boundary-copy"><h3>Enforced boundaries</h3><ul><li>Private ingress only</li><li>Authenticated owner records</li><li>Guardian independence</li><li>Deterministic policy decisions</li><li>Synthetic adapters until explicitly configured</li></ul></section>
      </div>
    </section>
  </main>

  <footer>
    Structured records are shown instead of hidden chain-of-thought. Credentials and CSRF proofs remain memory-only, and the ordinary console cannot mutate Guardian state.
  </footer>
`;

const app = document.querySelector<HTMLDivElement>("#app");
if (app === null) {
  throw new Error("Owner Console mount point is missing");
}
app.innerHTML = shell;

function required<ElementType extends Element>(selector: string): ElementType {
  const element = document.querySelector<ElementType>(selector);
  if (element === null) {
    throw new Error(`Owner Console element is missing: ${selector}`);
  }
  return element;
}

function makeElement<TagName extends keyof HTMLElementTagNameMap>(
  tagName: TagName,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[TagName] {
  const element = document.createElement(tagName);
  if (className !== undefined) {
    element.className = className;
  }
  if (text !== undefined) {
    writeText(element, text);
  }
  return element;
}

const refs = {
  notice: required<HTMLDivElement>("#notice"),
  authForm: required<HTMLFormElement>("#auth-form"),
  authTitle: required<HTMLHeadingElement>("#auth-title"),
  authDescription: required<HTMLParagraphElement>("#auth-description"),
  credential: required<HTMLInputElement>("#owner-credential"),
  authSubmit: required<HTMLButtonElement>("#auth-submit"),
  sessionSummary: required<HTMLDivElement>("#session-summary"),
  sessionOwner: required<HTMLElement>("#session-owner"),
  sessionExpires: required<HTMLElement>("#session-expires"),
  sessionProof: required<HTMLElement>("#session-proof"),
  logout: required<HTMLButtonElement>("#logout"),
  guardianBoundary: required<HTMLElement>("#guardian-boundary"),
  guardianBoundaryText: required<HTMLElement>("#guardian-boundary-text"),
  externalBoundary: required<HTMLElement>("#external-boundary"),
  externalBoundaryText: required<HTMLElement>("#external-boundary-text"),
  statusTitle: required<HTMLHeadingElement>("#status-title"),
  statusDetail: required<HTMLParagraphElement>("#status-detail"),
  statusMilestone: required<HTMLElement>("#status-milestone"),
  statusActions: required<HTMLElement>("#status-actions"),
  statusSequence: required<HTMLElement>("#status-sequence"),
  areaNav: required<HTMLElement>("#area-nav"),
  threadForm: required<HTMLFormElement>("#thread-form"),
  threadTitle: required<HTMLInputElement>("#thread-title"),
  threadSensitivity: required<HTMLSelectElement>("#thread-sensitivity"),
  threadRetention: required<HTMLInputElement>("#thread-retention"),
  threadSubmit: required<HTMLButtonElement>("#thread-submit"),
  threadCount: required<HTMLElement>("#thread-count"),
  threadList: required<HTMLDivElement>("#thread-list"),
  selectedThreadTitle: required<HTMLElement>("#selected-thread-title"),
  selectedThreadSensitivity: required<HTMLElement>("#selected-thread-sensitivity"),
  selectedThreadState: required<HTMLElement>("#selected-thread-state"),
  messageList: required<HTMLDivElement>("#message-list"),
  messageForm: required<HTMLFormElement>("#message-form"),
  messageText: required<HTMLTextAreaElement>("#message-text"),
  messageSubmit: required<HTMLButtonElement>("#message-submit"),
  deliveryForm: required<HTMLFormElement>("#delivery-form"),
  deliveryMessage: required<HTMLSelectElement>("#delivery-message"),
  deliveryAdapter: required<HTMLInputElement>("#delivery-adapter"),
  deliveryDestination: required<HTMLInputElement>("#delivery-destination"),
  deliverySubmit: required<HTMLButtonElement>("#delivery-submit"),
  deliveryCount: required<HTMLElement>("#delivery-count"),
  deliveryList: required<HTMLDivElement>("#delivery-list"),
  turnCount: required<HTMLElement>("#turn-count"),
  turnList: required<HTMLDivElement>("#turn-list"),
  turnInspection: required<HTMLDivElement>("#turn-inspection"),
  memoryForm: required<HTMLFormElement>("#memory-form"),
  memoryId: required<HTMLInputElement>("#memory-id"),
  memoryInspect: required<HTMLButtonElement>("#memory-inspect"),
  memoryRecord: required<HTMLElement>("#memory-record"),
  memoryActions: required<HTMLElement>("#memory-actions"),
  memoryVersion: required<HTMLElement>("#memory-version"),
  memoryExpectedVersion: required<HTMLInputElement>("#memory-expected-version"),
  memoryCorrection: required<HTMLTextAreaElement>("#memory-correction"),
  memoryCorrect: required<HTMLButtonElement>("#memory-correct"),
  memoryDispute: required<HTMLButtonElement>("#memory-dispute"),
  memoryRetract: required<HTMLButtonElement>("#memory-retract"),
  activityForm: required<HTMLFormElement>("#activity-form"),
  activityFrom: required<HTMLInputElement>("#activity-from"),
  activityTo: required<HTMLInputElement>("#activity-to"),
  activityLoad: required<HTMLButtonElement>("#activity-load"),
  metricRuns: required<HTMLElement>("#metric-runs"),
  metricDisclosures: required<HTMLElement>("#metric-disclosures"),
  metricInput: required<HTMLElement>("#metric-input"),
  metricOutput: required<HTMLElement>("#metric-output"),
  metricCost: required<HTMLElement>("#metric-cost"),
  metricExternalCost: required<HTMLElement>("#metric-external-cost"),
  activityList: required<HTMLDivElement>("#activity-list"),
  mediaCapture: required<HTMLElement>("#media-capture"),
  mediaContent: required<HTMLElement>("#media-content"),
  mediaSourceCount: required<HTMLElement>("#media-source-count"),
  mediaItemCount: required<HTMLElement>("#media-item-count"),
  mediaSourceList: required<HTMLDivElement>("#media-source-list"),
  mediaItemList: required<HTMLDivElement>("#media-item-list"),
  operationsStatus: required<HTMLElement>("#operations-status"),
  operationsHealthState: required<HTMLElement>("#operations-health-state"),
  operationsHealth: required<HTMLDivElement>("#operations-health"),
};

const api = new MelloaApi();
const state: ConsoleState = {
  principal: null,
  status: null,
  threads: [],
  selectedThreadId: null,
  messages: [],
  processing: [],
  deliveries: [],
  turns: [],
  selectedTurnId: null,
  turnInspection: null,
  memory: null,
  modelActivity: null,
  healthDetail: null,
  mediaCatalog: null,
};
let activeArea: AreaId = "conversation";
let pendingMessage: { readonly threadId: string; readonly text: string; readonly key: string } | null = null;
let pendingDelivery: {
  readonly threadId: string;
  readonly messageId: string;
  readonly clientAdapter: string;
  readonly destinationRef: string;
  readonly key: string;
} | null = null;

const areaButtons = new Map<AreaId, HTMLButtonElement>();
for (const area of areas) {
  const button = makeElement("button", "area-tab", area.label);
  button.type = "button";
  button.setAttribute("role", "tab");
  button.setAttribute("aria-controls", `panel-${area.id}`);
  button.addEventListener("click", () => activateArea(area.id));
  refs.areaNav.append(button);
  areaButtons.set(area.id, button);
}

function activateArea(areaId: AreaId): void {
  activeArea = areaId;
  for (const area of areas) {
    const selected = area.id === activeArea;
    const button = areaButtons.get(area.id);
    const panel = required<HTMLElement>(`#panel-${area.id}`);
    if (button !== undefined) {
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    }
    panel.hidden = !selected;
  }
}

function showNotice(message: string, tone: "success" | "warning" | "danger" = "success"): void {
  writeText(refs.notice, message);
  refs.notice.className = `notice ${tone}`;
  refs.notice.hidden = false;
}

function clearNotice(): void {
  refs.notice.hidden = true;
  writeText(refs.notice, "");
}

function mutationReady(): boolean {
  return mutationCapabilities(state.principal, api.hasMutationProof).standard;
}

function sensitiveMutationReady(): boolean {
  return mutationCapabilities(state.principal, api.hasMutationProof).sensitive;
}

function requireAuthenticated(): AuthenticatedOwner {
  if (state.principal === null) {
    throw new ApiError(401, "owner_authentication_required", "Sign in to inspect private records.");
  }
  return state.principal;
}

function requireMutationProof(): void {
  requireAuthenticated();
  if (!mutationReady()) {
    throw new ApiError(
      403,
      "recent_authentication_required",
      "Reauthenticate before changing private state.",
    );
  }
}

function requireSensitiveMutationProof(): void {
  requireMutationProof();
  if (!sensitiveMutationReady()) {
    throw new ApiError(
      403,
      "recent_authentication_required",
      "Reauthenticate before this high-trust action.",
    );
  }
}

function renderAuth(): void {
  const authenticated = state.principal !== null;
  const canMutate = mutationReady();
  const canMutateSensitiveState = sensitiveMutationReady();
  refs.sessionSummary.hidden = !authenticated;
  refs.logout.disabled = !canMutate;
  writeText(refs.authTitle, authenticated ? "Reauthenticate owner" : "Sign in to private records");
  writeText(refs.authSubmit, authenticated ? "Reauthenticate" : "Sign in");
  writeText(
    refs.authDescription,
    authenticated
      ? "Reauthenticate to refresh the memory-only mutation proof. The session cookie remains HTTP-only."
      : "Credentials are sent only to the same-origin core and are never stored by this console.",
  );
  if (state.principal !== null) {
    writeText(refs.sessionOwner, shortId(state.principal.owner_id));
    writeText(refs.sessionExpires, formatInstant(state.principal.expires_at));
    writeText(
      refs.sessionProof,
      canMutateSensitiveState
        ? "Fresh · sensitive changes allowed"
        : canMutate
          ? "Available · reauthenticate for sensitive actions"
          : "Reauthentication required",
    );
  } else {
    writeText(refs.sessionOwner, "");
    writeText(refs.sessionExpires, "");
    writeText(refs.sessionProof, "");
  }
  document.querySelectorAll<HTMLButtonElement>("[data-auth-only]").forEach((element) => {
    element.disabled = !authenticated;
  });
  document.querySelectorAll<HTMLButtonElement>("[data-mutation]").forEach((element) => {
    element.disabled = !canMutate;
  });
  document.querySelectorAll<HTMLButtonElement>("[data-sensitive-mutation]").forEach((element) => {
    element.disabled = !canMutateSensitiveState;
  });
  renderConversationControls();
}

function renderStatus(): void {
  if (state.status === null) {
    writeText(refs.statusTitle, "Fail closed until Guardian status is verified");
    writeText(refs.statusDetail, "The core status projection is unavailable.");
    writeText(refs.statusMilestone, "—");
    writeText(refs.statusActions, "Disabled");
    writeText(refs.statusSequence, "—");
    writeText(refs.guardianBoundaryText, "Guardian status unavailable");
    writeText(refs.externalBoundaryText, "External actions disabled");
    refs.guardianBoundary.className = "boundary warning";
    refs.externalBoundary.className = "boundary warning";
    writeText(refs.operationsStatus, "Status unavailable. Normal operation remains fail closed.");
    return;
  }
  const normal = state.status.guardian.mode === "normal";
  writeText(refs.statusTitle, `Guardian ${state.status.guardian.mode}`);
  writeText(refs.statusDetail, `Signed projection changed ${formatInstant(state.status.guardian.changed_at)}.`);
  writeText(refs.statusMilestone, state.status.milestone);
  writeText(refs.statusActions, state.status.external_actions_enabled ? "Enabled by Guardian" : "Disabled");
  writeText(refs.statusSequence, state.status.guardian.sequence);
  writeText(
    refs.guardianBoundaryText,
    `Guardian ${state.status.guardian.mode} · sequence ${state.status.guardian.sequence}`,
  );
  writeText(
    refs.externalBoundaryText,
    state.status.external_actions_enabled ? "External actions Guardian-enabled" : "External actions disabled",
  );
  refs.guardianBoundary.className = normal ? "boundary" : "boundary warning";
  refs.externalBoundary.className = state.status.external_actions_enabled ? "boundary warning" : "boundary";
  writeText(refs.operationsStatus, formatJson(state.status));
}

function emptyState(title: string, detail: string): HTMLElement {
  const container = makeElement("div", "empty-state");
  container.append(makeElement("strong", undefined, title), makeElement("span", undefined, detail));
  return container;
}

function definitionGrid(entries: readonly (readonly [string, string])[]): HTMLDListElement {
  const list = makeElement("dl", "record-grid");
  for (const [label, value] of entries) {
    const item = makeElement("div");
    item.append(makeElement("dt", undefined, label), makeElement("dd", undefined, value));
    list.append(item);
  }
  return list;
}

function structuredBlock(title: string, value: unknown): HTMLElement {
  const details = makeElement("details", "structured-block");
  details.append(makeElement("summary", undefined, title));
  const output = makeElement("pre");
  writeText(output, formatJson(value));
  details.append(output);
  return details;
}

function selectedThread(): ConversationThread | null {
  return state.threads.find((thread) => thread.thread_id === state.selectedThreadId) ?? null;
}

function renderThreads(): void {
  writeText(refs.threadCount, state.threads.length);
  refs.threadList.replaceChildren();
  if (state.threads.length === 0) {
    refs.threadList.append(emptyState("No threads", "Create a private thread after authenticating."));
  }
  for (const thread of state.threads) {
    const button = makeElement("button", "thread-item");
    button.type = "button";
    button.setAttribute("aria-pressed", String(thread.thread_id === state.selectedThreadId));
    button.append(
      makeElement("strong", undefined, thread.title),
      makeElement("span", undefined, `${thread.sensitivity} · ${formatInstant(thread.updated_at)}`),
    );
    button.addEventListener("click", () => {
      void attempt("Load conversation", async () => selectThread(thread.thread_id));
    });
    refs.threadList.append(button);
  }
  const thread = selectedThread();
  const failedProcessing = state.processing.some((item) => item.state === "dead");
  const pendingProcessing = state.processing.some(
    (item) => item.state === "ready" || item.state === "running",
  );
  const failedDelivery = state.deliveries.some((item) => item.state === "dead");
  const pendingDeliveryState = state.deliveries.some(
    (item) => item.state === "ready" || item.state === "running",
  );
  writeText(refs.selectedThreadTitle, thread?.title ?? "Choose a thread");
  writeText(refs.selectedThreadSensitivity, thread?.sensitivity ?? "No thread selected");
  writeText(
    refs.selectedThreadState,
    failedProcessing
      ? "Reply failed"
      : failedDelivery
        ? "Delivery failed"
      : pendingProcessing
        ? "Reply pending"
        : pendingDeliveryState
          ? "Delivery pending"
        : thread?.status ?? "Idle",
  );
  renderConversationControls();
}

function renderConversationControls(): void {
  const canMutate = mutationReady();
  const hasThread = state.selectedThreadId !== null;
  const hasMessage = refs.deliveryMessage.value !== "";
  refs.threadSubmit.disabled = !canMutate;
  refs.messageSubmit.disabled = !canMutate || !hasThread;
  refs.messageText.disabled = state.principal === null || !hasThread;
  refs.deliveryMessage.disabled = state.principal === null || !hasThread;
  refs.deliveryAdapter.disabled = state.principal === null || !hasThread;
  refs.deliveryDestination.disabled = state.principal === null || !hasThread;
  refs.deliverySubmit.disabled = !sensitiveMutationReady() || !hasThread || !hasMessage;
}

function renderMessages(): void {
  refs.messageList.replaceChildren();
  if (state.selectedThreadId === null) {
    refs.messageList.append(emptyState("No thread selected", "Choose a thread to load canonical messages."));
    return;
  }
  if (state.messages.length === 0) {
    refs.messageList.append(emptyState("No messages yet", "Send the first owner message when mutation proof is fresh."));
    return;
  }
  for (const message of state.messages) {
    const ownerAuthored = message.author_principal_id === state.principal?.owner_id;
    const article = makeElement("article", ownerAuthored ? "message owner" : "message intelligence");
    const header = makeElement("header");
    header.append(
      makeElement("strong", undefined, ownerAuthored ? "Owner" : "Melloa"),
      makeElement("time", undefined, formatInstant(message.created_at)),
    );
    const body = makeElement("p", "message-body");
    writeText(body, messageBody(message));
    article.append(header, body);
    const processing = state.processing.find((item) => item.message_id === message.message_id);
    if (ownerAuthored && processing !== undefined && processing.state !== "completed") {
      const detail = makeElement("div", `processing-state ${processing.state}`);
      const retryDetail =
        processing.state === "ready"
          ? `Next eligible attempt: ${formatInstant(processing.available_at)}`
          : processing.state === "running"
            ? `Lease expires: ${formatInstant(processing.lease_expires_at ?? processing.available_at)}`
            : "Automatic attempts are exhausted.";
      detail.append(
        makeElement(
          "strong",
          undefined,
          `Reply ${processing.state} · attempt ${formatCount(processing.attempt_count)}/${formatCount(processing.max_attempts)}`,
        ),
        makeElement(
          "span",
          undefined,
          `${processing.last_error_code ?? "No provider error recorded"} · ${retryDetail}`,
        ),
      );
      if (processing.state === "dead") {
        const resume = makeElement("button", "quiet", "Resume reply");
        resume.type = "button";
        resume.dataset.mutation = "";
        resume.disabled = !mutationReady();
        resume.addEventListener("click", () => {
          void attempt("Resume accepted message", async () => {
            requireMutationProof();
            await api.resumeMessage(processing.thread_id, processing.message_id);
            await loadSelectedThread();
            showNotice("Accepted message requeued with a new bounded attempt budget.");
          }).finally(renderAuth);
        });
        detail.append(resume);
      }
      article.append(detail);
    }
    if (message.citation_ids.length > 0) {
      article.append(
        makeElement(
          "p",
          "citation-line",
          `Citations: ${message.citation_ids.map((citationId) => shortId(citationId)).join(", ")}`,
        ),
      );
    }
    article.append(
      makeElement(
        "span",
        "record-meta",
        `${shortId(message.message_id)} · ${message.delivery_state} · ${message.source_client}`,
      ),
    );
    refs.messageList.append(article);
  }
  refs.messageList.scrollTop = refs.messageList.scrollHeight;
}

function renderDeliveryMessageOptions(): void {
  const previous = refs.deliveryMessage.value;
  refs.deliveryMessage.replaceChildren();
  const placeholder = makeElement("option", undefined, "Choose a canonical message");
  placeholder.value = "";
  placeholder.disabled = true;
  refs.deliveryMessage.append(placeholder);
  for (const message of state.messages) {
    const ownerAuthored = message.author_principal_id === state.principal?.owner_id;
    const preview = messageBody(message).replace(/\s+/g, " ").trim();
    const label = `${ownerAuthored ? "Owner" : "Melloa"} · ${shortId(message.message_id)} · ${preview.slice(0, 72) || "No text body"}`;
    const option = makeElement("option", undefined, label);
    option.value = message.message_id;
    refs.deliveryMessage.append(option);
  }
  const selectedMessageId = state.messages.some((message) => message.message_id === previous)
    ? previous
    : (state.messages[state.messages.length - 1]?.message_id ?? "");
  refs.deliveryMessage.value = selectedMessageId;
  renderConversationControls();
}

function renderDeliveries(): void {
  writeText(refs.deliveryCount, state.deliveries.length);
  renderDeliveryMessageOptions();
  refs.deliveryList.replaceChildren();
  if (state.selectedThreadId === null) {
    refs.deliveryList.append(
      emptyState("No thread selected", "Choose a thread to inspect outbound delivery state."),
    );
    return;
  }
  if (state.deliveries.length === 0) {
    refs.deliveryList.append(
      emptyState(
        "No outbound deliveries",
        "Exact message-bound delivery attempts and recovery history appear here.",
      ),
    );
    return;
  }
  for (const delivery of state.deliveries) {
    const summary = deliveryRecoverySummary(delivery);
    const article = makeElement("article", `delivery-card ${summary.tone}`);
    const heading = makeElement("div", "activity-heading");
    const title = makeElement("div");
    title.append(
      makeElement("h4", undefined, `${delivery.client_adapter} → ${delivery.destination_ref}`),
      makeElement("p", "muted", `${shortId(delivery.work_id)} · ${shortId(delivery.message_id)}`),
    );
    heading.append(title, makeElement("span", "state-chip", summary.label));
    article.append(
      heading,
      makeElement("p", "delivery-summary", summary.detail),
      definitionGrid([
        ["State", delivery.state],
        ["Attempts", `${formatCount(delivery.attempt_count)} / ${formatCount(delivery.max_attempts)}`],
        ["Available", formatInstant(delivery.available_at)],
        ["Completed", formatInstant(delivery.completed_at)],
        ["Last error", delivery.last_error_code ?? "None recorded"],
        ["Policy decision", shortId(delivery.current_policy_decision_id)],
      ]),
    );
    if (summary.canResume) {
      const resume = makeElement("button", "quiet warning-button", "Resume with fresh policy");
      resume.type = "button";
      resume.dataset.sensitiveMutation = "";
      resume.disabled = !sensitiveMutationReady();
      resume.addEventListener("click", () => {
        void attempt("Resume outbound delivery", async () => {
          requireSensitiveMutationProof();
          if (
            !window.confirm(
              "Reauthorize this exact message, adapter, and destination under a fresh policy decision?",
            )
          ) {
            return;
          }
          resume.disabled = true;
          await api.resumeDelivery(delivery.thread_id, delivery.work_id);
          await loadSelectedThread();
          showNotice("Outbound delivery reauthorized with a fresh bounded attempt budget.");
        }).finally(renderAuth);
      });
      article.append(resume);
    }
    article.append(structuredBlock("Attempt history", delivery.attempts));
    if (delivery.resumptions.length > 0) {
      article.append(structuredBlock("Owner resumption history", delivery.resumptions));
    }
    refs.deliveryList.append(article);
  }
}

function renderTurns(): void {
  writeText(refs.turnCount, state.turns.length);
  refs.turnList.replaceChildren();
  if (state.selectedThreadId === null || state.turns.length === 0) {
    refs.turnList.append(emptyState("No turns", "Structured turn records appear after a completed exchange."));
  }
  for (const turn of state.turns) {
    const button = makeElement("button", "turn-item");
    button.type = "button";
    button.setAttribute("aria-pressed", String(turn.turn_id === state.selectedTurnId));
    button.append(
      makeElement("strong", undefined, shortId(turn.turn_id)),
      makeElement("span", undefined, formatInstant(turn.completed_at ?? turn.started_at)),
    );
    button.addEventListener("click", () => {
      void attempt("Inspect turn", async () => inspectTurn(turn.turn_id));
    });
    refs.turnList.append(button);
  }
  renderTurnInspection();
}

function renderTurnInspection(): void {
  refs.turnInspection.replaceChildren();
  if (state.turnInspection === null) {
    refs.turnInspection.append(
      emptyState("Select a turn", "Inspect retrieval, model result, output, and deterministic decision records."),
    );
    return;
  }
  const inspection = state.turnInspection;
  const heading = makeElement("div", "inspection-heading");
  heading.append(
    makeElement("p", "eyebrow", "Structured inspection"),
    makeElement("h4", undefined, shortId(inspection.turn.turn_id)),
  );
  const output = makeElement("section", "output-preview");
  output.append(
    makeElement("h5", undefined, "Output message"),
    makeElement("p", "message-body", messageBody(inspection.output_message)),
  );
  refs.turnInspection.append(
    heading,
    output,
    structuredBlock("Decision record", inspection.turn.decision_record),
    structuredBlock("Retrieval manifest", inspection.retrieval_manifest),
    structuredBlock("Model result", inspection.model_result),
  );
}

function renderMemory(): void {
  refs.memoryRecord.replaceChildren();
  if (state.memory === null) {
    refs.memoryActions.hidden = true;
    refs.memoryRecord.append(
      emptyState("No assertion loaded", "Enter an owner-visible assertion ID to inspect value, provenance, and state history."),
    );
    return;
  }
  const memory = state.memory;
  refs.memoryActions.hidden = false;
  writeText(refs.memoryVersion, `Version ${memory.current_state.version}`);
  refs.memoryExpectedVersion.value = String(memory.current_state.version);
  refs.memoryCorrection.value = formatJson(memory.assertion.value);
  refs.memoryRecord.append(
    makeElement("p", "eyebrow", "Assertion record"),
    makeElement("h3", undefined, shortId(memory.assertion.assertion_id)),
    definitionGrid([
      ["State", memory.current_state.current_status],
      ["Version", String(memory.current_state.version)],
      ["Provenance edges", String(memory.provenance_edges.length)],
      ["State changes", String(memory.state_changes.length)],
    ]),
    structuredBlock("Assertion value and metadata", memory.assertion),
    structuredBlock("Current projection", memory.current_state),
    structuredBlock("Provenance", memory.provenance_edges),
    structuredBlock("Append-only state history", memory.state_changes),
  );
}

function renderActivity(): void {
  const report = state.modelActivity;
  writeText(refs.metricRuns, report === null ? "—" : formatCount(report.total_runs));
  writeText(
    refs.metricDisclosures,
    report === null ? "—" : formatCount(report.external_disclosure_runs),
  );
  writeText(refs.metricInput, report === null ? "—" : formatCount(report.total_input_tokens));
  writeText(refs.metricOutput, report === null ? "—" : formatCount(report.total_output_tokens));
  writeText(refs.metricCost, report === null ? "—" : formatGbp(report.total_cost_gbp));
  writeText(
    refs.metricExternalCost,
    report === null ? "—" : formatGbp(report.external_cost_gbp),
  );
  refs.activityList.replaceChildren();
  if (report === null) {
    refs.activityList.append(emptyState("No report loaded", "Authenticate and choose a bounded UTC window."));
    return;
  }
  if (report.entries.length === 0) {
    refs.activityList.append(emptyState("No model runs", "No completed model activity falls inside this half-open window."));
    return;
  }
  for (const entry of report.entries) {
    refs.activityList.append(renderActivityEntry(entry));
  }
}

function renderActivityEntry(entry: ModelActivityEntry): HTMLElement {
  const article = makeElement("article", "activity-card");
  const heading = makeElement("div", "activity-heading");
  const title = makeElement("div");
  title.append(
    makeElement("p", "eyebrow", entry.external_disclosure ? "External disclosure" : "Local route"),
    makeElement("h3", undefined, `${entry.provider_id} · ${entry.model_id}`),
  );
  const inspect = makeElement("button", "quiet", "Open turn");
  inspect.type = "button";
  inspect.addEventListener("click", () => {
    void attempt("Open model turn", async () => openActivityTurn(entry));
  });
  heading.append(title, inspect);
  article.append(
    heading,
    definitionGrid([
      ["Route", entry.route_id],
      ["Input tokens", formatCount(entry.input_tokens)],
      ["Output tokens", formatCount(entry.output_tokens)],
      ["Cost", formatGbp(entry.cost_gbp)],
      ["Completed", formatInstant(entry.completed_at)],
      ["Result", shortId(entry.result_id)],
    ]),
  );
  if (entry.disclosure !== null && entry.disclosure !== undefined) {
    article.append(structuredBlock("External disclosure detail", entry.disclosure));
  }
  return article;
}

function renderHealth(): void {
  const report = state.healthDetail;
  writeText(refs.operationsHealthState, report?.overall_state ?? "—");
  refs.operationsHealth.replaceChildren();
  if (report === null) {
    refs.operationsHealth.append(
      emptyState("No health detail loaded", "Authenticate to inspect redacted component state."),
    );
    return;
  }
  for (const component of report.components) {
    refs.operationsHealth.append(renderHealthComponent(component));
  }
}

function renderHealthComponent(component: ComponentHealth): HTMLElement {
  const article = makeElement("article", "health-card");
  const heading = makeElement("div", "panel-heading");
  const title = makeElement("div");
  title.append(
    makeElement("p", "eyebrow", component.category),
    makeElement("h4", undefined, component.component_id),
  );
  heading.append(title, makeElement("span", "state-chip", component.state));
  article.append(
    heading,
    makeElement("p", "muted", component.summary),
    definitionGrid([
      ["Required", component.required ? "Yes" : "No"],
      ["Observed", formatInstant(component.observed_at)],
      ["Version", component.version ?? "—"],
    ]),
  );
  return article;
}

function renderMedia(): void {
  const catalog = state.mediaCatalog;
  writeText(
    refs.mediaCapture,
    catalog === null ? "—" : catalog.capture_enabled ? "Enabled" : "Disabled",
  );
  writeText(
    refs.mediaContent,
    catalog === null ? "—" : catalog.content_endpoint_available ? "Available" : "Metadata only",
  );
  writeText(refs.mediaSourceCount, catalog === null ? "—" : formatCount(catalog.sources.length));
  writeText(refs.mediaItemCount, catalog === null ? "—" : formatCount(catalog.items.length));
  refs.mediaSourceList.replaceChildren();
  refs.mediaItemList.replaceChildren();
  if (catalog === null) {
    refs.mediaSourceList.append(
      emptyState("No source status loaded", "Authenticate to inspect capture configuration."),
    );
    refs.mediaItemList.append(
      emptyState("No retention metadata loaded", "No content route is exposed by this view."),
    );
    return;
  }
  if (catalog.sources.length === 0) {
    refs.mediaSourceList.append(
      emptyState("No media sources", "No media capability is installed for this owner runtime."),
    );
  }
  for (const source of catalog.sources) {
    refs.mediaSourceList.append(renderMediaSource(source));
  }
  if (catalog.items.length === 0) {
    refs.mediaItemList.append(
      emptyState(
        "No retained media records",
        catalog.capture_enabled
          ? "Capture is configured, but no owner-visible metadata is retained."
          : "Capture is disabled. The console will not fabricate media records.",
      ),
    );
  }
  for (const item of catalog.items) {
    refs.mediaItemList.append(renderMediaItem(item));
  }
}

function renderMediaSource(source: MediaSourceStatus): HTMLElement {
  const article = makeElement("article", "health-card");
  const heading = makeElement("div", "panel-heading");
  heading.append(
    makeElement("h4", undefined, source.capability_id),
    makeElement("span", "state-chip", source.health_state),
  );
  article.append(
    heading,
    definitionGrid([
      ["Installed", source.installed ? "Yes" : "No"],
      ["Capture", source.capture_enabled ? "Enabled" : "Disabled"],
      ["Reason", source.status_reason],
      ["Observed", formatInstant(source.observed_at)],
      ["Last capture", formatInstant(source.last_capture_at)],
      ["Missing intervals", formatCount(source.missing_intervals.length)],
    ]),
  );
  if (source.missing_intervals.length > 0) {
    article.append(structuredBlock("Missing intervals", source.missing_intervals));
  }
  return article;
}

function renderMediaItem(item: MediaItemMetadata): HTMLElement {
  const article = makeElement("article", "activity-card");
  const heading = makeElement("div", "activity-heading");
  const title = makeElement("div");
  title.append(
    makeElement("p", "eyebrow", item.retention_state),
    makeElement("h3", undefined, shortId(item.media_id)),
  );
  heading.append(title, makeElement("span", "state-chip", item.sensitivity));
  article.append(
    heading,
    definitionGrid([
      ["Source", item.source_capability_id],
      ["Event", shortId(item.event_id)],
      ["Type", item.media_type],
      ["Captured from", formatInstant(item.captured_from)],
      ["Captured to", formatInstant(item.captured_to)],
      ["Confidence", item.interpretation_confidence?.toFixed(3) ?? "—"],
      ["Expires", formatInstant(item.expires_at)],
      ["Size bytes", formatCount(item.size_bytes)],
      ["Retention", item.retention_policy],
      ["Content hash", item.content_hash],
    ]),
  );
  if (item.disclosure_record_ids.length > 0) {
    article.append(structuredBlock("Disclosure record IDs", item.disclosure_record_ids));
  }
  return article;
}

function clearPrivateState(): void {
  state.threads = [];
  state.selectedThreadId = null;
  state.messages = [];
  state.processing = [];
  state.deliveries = [];
  state.turns = [];
  state.selectedTurnId = null;
  state.turnInspection = null;
  state.memory = null;
  state.modelActivity = null;
  state.healthDetail = null;
  state.mediaCatalog = null;
  pendingMessage = null;
  pendingDelivery = null;
  refs.messageText.value = "";
  refs.deliveryAdapter.value = "";
  refs.deliveryDestination.value = "";
  refs.memoryId.value = "";
  renderThreads();
  renderMessages();
  renderDeliveries();
  renderTurns();
  renderMemory();
  renderActivity();
  renderHealth();
  renderMedia();
}

function handleError(error: unknown, context: string): void {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      state.principal = null;
      clearPrivateState();
    }
    renderAuth();
    showNotice(`${context}: ${error.message}`, error.status >= 500 ? "danger" : "warning");
    return;
  }
  const message = error instanceof Error ? error.message : "Unexpected Owner Console failure.";
  showNotice(`${context}: ${message}`, "danger");
}

async function attempt(context: string, action: () => Promise<void>): Promise<void> {
  try {
    clearNotice();
    await action();
  } catch (error) {
    handleError(error, context);
  }
}

async function loadStatus(): Promise<void> {
  try {
    state.status = await api.systemStatus();
  } catch (error) {
    state.status = null;
    handleError(error, "Read system status");
  } finally {
    renderStatus();
  }
}

async function restoreSession(): Promise<void> {
  try {
    state.principal = await api.currentSession();
    renderAuth();
    showNotice("Session restored. Reauthenticate before changing private state.", "warning");
    await loadPrivateOverview();
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) {
      handleError(error, "Restore owner session");
    }
    state.principal = null;
    renderAuth();
  }
}

async function loadPrivateOverview(): Promise<void> {
  requireAuthenticated();
  await Promise.all([
    loadThreads().catch((error: unknown) => handleError(error, "Load conversations")),
    loadActivity().catch((error: unknown) => handleError(error, "Load model activity")),
    loadHealth().catch((error: unknown) => handleError(error, "Load component health")),
    loadMedia().catch((error: unknown) => handleError(error, "Load media metadata")),
  ]);
}

async function loadThreads(): Promise<void> {
  requireAuthenticated();
  const threads = await api.listThreads();
  state.threads = threads;
  if (
    state.selectedThreadId === null ||
    !threads.some((thread) => thread.thread_id === state.selectedThreadId)
  ) {
    state.selectedThreadId = threads[0]?.thread_id ?? null;
  }
  renderThreads();
  if (state.selectedThreadId === null) {
    state.messages = [];
    state.processing = [];
    state.deliveries = [];
    state.turns = [];
    state.turnInspection = null;
    renderMessages();
    renderDeliveries();
    renderTurns();
    return;
  }
  await loadSelectedThread();
}

async function selectThread(threadId: string): Promise<void> {
  requireAuthenticated();
  if (state.selectedThreadId === threadId) {
    return;
  }
  state.selectedThreadId = threadId;
  state.processing = [];
  state.deliveries = [];
  state.selectedTurnId = null;
  state.turnInspection = null;
  pendingMessage = null;
  pendingDelivery = null;
  renderThreads();
  await loadSelectedThread();
}

async function loadSelectedThread(): Promise<void> {
  const threadId = state.selectedThreadId;
  if (threadId === null) {
    return;
  }
  const [messages, turns, processing, deliveries] = await Promise.all([
    api.listMessages(threadId),
    api.listTurns(threadId),
    api.listProcessing(threadId),
    api.listDeliveries(threadId),
  ]);
  if (state.selectedThreadId !== threadId) {
    return;
  }
  state.messages = messages;
  state.turns = turns;
  state.processing = processing;
  state.deliveries = deliveries;
  if (!turns.some((turn) => turn.turn_id === state.selectedTurnId)) {
    state.selectedTurnId = null;
    state.turnInspection = null;
  }
  renderMessages();
  renderDeliveries();
  renderTurns();
}

async function inspectTurn(turnId: string): Promise<void> {
  const threadId = state.selectedThreadId;
  if (threadId === null) {
    throw new Error("Select a conversation thread first.");
  }
  const inspection = await api.inspectTurn(threadId, turnId);
  if (state.selectedThreadId !== threadId) {
    return;
  }
  state.selectedTurnId = turnId;
  state.turnInspection = inspection;
  renderTurns();
}

async function inspectMemory(assertionId: string): Promise<void> {
  requireAuthenticated();
  state.memory = await api.inspectMemory(assertionId);
  refs.memoryId.value = assertionId;
  renderMemory();
  renderAuth();
}

function expectedMemoryVersion(): number {
  const version = Number(refs.memoryExpectedVersion.value);
  if (!Number.isSafeInteger(version) || version <= 0) {
    throw new Error("Expected memory version must be a positive integer.");
  }
  return version;
}

async function loadActivity(): Promise<void> {
  requireAuthenticated();
  const window = parseActivityWindow(refs.activityFrom.value, refs.activityTo.value);
  state.modelActivity = await api.modelActivity(window.start, window.end);
  renderActivity();
}

async function loadHealth(): Promise<void> {
  requireAuthenticated();
  state.healthDetail = await api.healthDetail();
  renderHealth();
}

async function loadMedia(): Promise<void> {
  requireAuthenticated();
  state.mediaCatalog = await api.mediaCatalog();
  renderMedia();
}

async function openActivityTurn(entry: ModelActivityEntry): Promise<void> {
  activateArea("conversation");
  if (state.selectedThreadId !== entry.thread_id) {
    state.selectedThreadId = entry.thread_id;
    state.selectedTurnId = null;
    state.turnInspection = null;
    renderThreads();
    await loadSelectedThread();
  }
  await inspectTurn(entry.turn_id);
}

refs.authForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const credential = refs.credential.value;
  refs.credential.value = "";
  void attempt("Authenticate owner", async () => {
    refs.authSubmit.disabled = true;
    try {
      state.principal = await api.login(credential);
      renderAuth();
      showNotice("Owner authenticated. Mutation proof is held in memory only.");
      await loadPrivateOverview();
    } finally {
      renderAuth();
    }
  });
});

refs.logout.addEventListener("click", () => {
  void attempt("Sign out", async () => {
    requireMutationProof();
    refs.logout.disabled = true;
    await api.logout();
    state.principal = null;
    clearPrivateState();
    renderAuth();
    showNotice("Owner session revoked.");
  });
});

refs.threadForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void attempt("Create conversation", async () => {
    requireMutationProof();
    refs.threadSubmit.disabled = true;
    const created = await api.createThread({
      title: refs.threadTitle.value.trim(),
      sensitivity: refs.threadSensitivity.value,
      retention_policy: refs.threadRetention.value.trim(),
    });
    refs.threadTitle.value = "";
    await loadThreads();
    await selectThread(created.thread_id);
    showNotice("Private conversation thread created.");
  }).finally(renderAuth);
});

refs.messageForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void attempt("Send owner message", async () => {
    requireMutationProof();
    const threadId = state.selectedThreadId;
    if (threadId === null) {
      throw new Error("Select a conversation thread first.");
    }
    const text = refs.messageText.value.trim();
    if (text === "") {
      throw new Error("Message text cannot be empty.");
    }
    if (pendingMessage === null || pendingMessage.threadId !== threadId || pendingMessage.text !== text) {
      pendingMessage = {
        threadId,
        text,
        key: `owner-console:${crypto.randomUUID()}`,
      };
    }
    refs.messageSubmit.disabled = true;
    const reply = await api.postMessage(threadId, text, pendingMessage.key);
    pendingMessage = null;
    refs.messageText.value = "";
    await loadSelectedThread();
    showNotice(
      reply.processing.state === "completed"
        ? "Canonical owner message and reply recorded."
        : "Canonical owner message accepted; bounded reply processing continues.",
    );
  }).finally(renderAuth);
});

refs.deliveryMessage.addEventListener("change", renderConversationControls);

refs.deliveryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void attempt("Authorize outbound delivery", async () => {
    requireSensitiveMutationProof();
    const threadId = state.selectedThreadId;
    if (threadId === null) {
      throw new Error("Select a conversation thread first.");
    }
    const messageId = refs.deliveryMessage.value;
    const clientAdapter = refs.deliveryAdapter.value.trim();
    const destinationRef = refs.deliveryDestination.value.trim();
    if (!state.messages.some((message) => message.message_id === messageId)) {
      throw new Error("Choose a canonical message from the selected thread.");
    }
    if (clientAdapter === "" || destinationRef === "") {
      throw new Error("Client adapter and destination reference are required.");
    }
    if (
      !window.confirm(
        `Authorize ${shortId(messageId)} for ${clientAdapter} → ${destinationRef}?`,
      )
    ) {
      return;
    }
    if (
      pendingDelivery === null ||
      pendingDelivery.threadId !== threadId ||
      pendingDelivery.messageId !== messageId ||
      pendingDelivery.clientAdapter !== clientAdapter ||
      pendingDelivery.destinationRef !== destinationRef
    ) {
      pendingDelivery = {
        threadId,
        messageId,
        clientAdapter,
        destinationRef,
        key: `owner-console-delivery:${crypto.randomUUID()}`,
      };
    }
    refs.deliverySubmit.disabled = true;
    const submission = await api.enqueueDelivery(threadId, {
      message_id: messageId,
      client_adapter: clientAdapter,
      destination_ref: destinationRef,
      idempotency_key: pendingDelivery.key,
    });
    pendingDelivery = null;
    await loadSelectedThread();
    const accepted = submission.delivery.state !== "completed";
    showNotice(
      submission.created
        ? accepted
          ? "Outbound delivery accepted; bounded recovery state is visible below."
          : "Outbound delivery completed and receipts are available below."
        : "Existing idempotent delivery status loaded without another external send.",
      accepted ? "warning" : "success",
    );
  }).finally(renderAuth);
});

refs.memoryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void attempt("Inspect memory", async () => {
    refs.memoryInspect.disabled = true;
    await inspectMemory(refs.memoryId.value.trim());
  }).finally(renderAuth);
});

refs.memoryCorrect.addEventListener("click", () => {
  void attempt("Correct memory", async () => {
    requireSensitiveMutationProof();
    const memory = state.memory;
    if (memory === null) {
      throw new Error("Inspect an assertion before correcting it.");
    }
    const expectedVersion = expectedMemoryVersion();
    const value = parseJsonObject(refs.memoryCorrection.value);
    if (!window.confirm("Append an immutable correction and supersede this assertion?")) {
      return;
    }
    refs.memoryCorrect.disabled = true;
    await api.correctMemory(memory.assertion.assertion_id, value, expectedVersion);
    await inspectMemory(memory.assertion.assertion_id);
    showNotice("Correction appended with CORRECTS provenance.");
  }).finally(renderAuth);
});

refs.memoryDispute.addEventListener("click", () => {
  void attempt("Dispute memory", async () => {
    requireSensitiveMutationProof();
    const memory = state.memory;
    if (memory === null) {
      throw new Error("Inspect an assertion before disputing it.");
    }
    const expectedVersion = expectedMemoryVersion();
    if (!window.confirm("Append a disputed state transition to this assertion?")) {
      return;
    }
    refs.memoryDispute.disabled = true;
    await api.disputeMemory(memory.assertion.assertion_id, expectedVersion);
    await inspectMemory(memory.assertion.assertion_id);
    showNotice("Dispute state transition appended.");
  }).finally(renderAuth);
});

refs.memoryRetract.addEventListener("click", () => {
  void attempt("Retract memory", async () => {
    requireSensitiveMutationProof();
    const memory = state.memory;
    if (memory === null) {
      throw new Error("Inspect an assertion before retracting it.");
    }
    const expectedVersion = expectedMemoryVersion();
    if (!window.confirm("Append a retracted state transition to this assertion?")) {
      return;
    }
    refs.memoryRetract.disabled = true;
    await api.retractMemory(memory.assertion.assertion_id, expectedVersion);
    await inspectMemory(memory.assertion.assertion_id);
    showNotice("Retraction state transition appended.");
  }).finally(renderAuth);
});

refs.activityForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void attempt("Load model activity", async () => {
    refs.activityLoad.disabled = true;
    await loadActivity();
  }).finally(renderAuth);
});

const activityWindow = defaultActivityWindow();
refs.activityFrom.value = activityWindow.from;
refs.activityTo.value = activityWindow.to;
activateArea(activeArea);
renderAuth();
renderStatus();
renderThreads();
renderMessages();
renderDeliveries();
renderTurns();
renderMemory();
renderActivity();
renderHealth();
renderMedia();
window.setInterval(renderAuth, 15_000);
void Promise.all([loadStatus(), restoreSession()]);
