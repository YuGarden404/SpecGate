const state = {
  user: null,
  projects: [],
  selectedProject: null,
  messages: [],
  currentRun: null,
  approvals: [],
  settings: null,
  activeTab: "status",
  pollTimer: null,
};

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function text(value) {
  return document.createTextNode(String(value ?? ""));
}

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) {
    node.className = options.className;
  }
  if (options.id) {
    node.id = options.id;
  }
  if (options.type) {
    node.type = options.type;
  }
  if (options.href) {
    node.href = options.href;
  }
  if (options.download) {
    node.download = options.download;
  }
  if (options.title) {
    node.title = options.title;
  }
  if (options.dataset) {
    for (const [key, value] of Object.entries(options.dataset)) {
      node.dataset[key] = value;
    }
  }
  for (const child of children) {
    node.append(child instanceof Node ? child : text(child));
  }
  return node;
}

function setText(id, value) {
  const node = byId(id);
  if (node) {
    node.textContent = String(value ?? "");
  }
}

function setMessage(value, isError = false) {
  const node = byId("app-message");
  node.textContent = value || "";
  node.classList.toggle("error", Boolean(isError));
}

function setAuthMessage(value, isError = false) {
  const node = byId("auth-message");
  node.textContent = value || "";
  node.classList.toggle("error", Boolean(isError));
}

async function apiJson(path, options = {}) {
  const init = {
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  };
  if (options.body && !(options.body instanceof FormData)) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, init);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" && payload ? payload.detail : payload;
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return payload;
}

async function apiText(path) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "text/plain, text/html;q=0.9, */*;q=0.5" },
  });
  const value = await response.text();
  if (!response.ok) {
    throw new Error(value || `Request failed with ${response.status}`);
  }
  return value;
}

function showView(isAuthed) {
  byId("auth-view").hidden = isAuthed;
  byId("workspace-view").hidden = !isAuthed;
}

async function init() {
  bindEvents();
  try {
    const payload = await apiJson("/api/me");
    state.user = payload.user;
    showView(true);
    await hydrateWorkspace();
  } catch (error) {
    state.user = null;
    showView(false);
  }
}

function bindEvents() {
  byId("auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    login();
  });
  byId("register-button").addEventListener("click", register);
  byId("logout-button").addEventListener("click", logout);
  byId("refresh-button").addEventListener("click", hydrateWorkspace);
  byId("new-project-button").addEventListener("click", openProjectDialog);
  byId("close-project-dialog").addEventListener("click", closeProjectDialog);
  byId("cancel-project-button").addEventListener("click", closeProjectDialog);
  byId("project-form").addEventListener("submit", createManualProject);
  byId("run-form").addEventListener("submit", startRun);
  byId("settings-form").addEventListener("submit", updateSettings);
  byId("api-key-form").addEventListener("submit", saveApiKey);
  byId("clear-api-key-button").addEventListener("click", clearApiKey);
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      renderDetail();
    });
  });
}

async function login() {
  await authenticate("/api/auth/login");
}

async function register() {
  await authenticate("/api/auth/register");
}

async function authenticate(path) {
  const username = byId("auth-username").value.trim();
  const password = byId("auth-password").value;
  try {
    const payload = await apiJson(path, {
      method: "POST",
      body: { username, password },
    });
    state.user = payload.user;
    setAuthMessage("");
    showView(true);
    await hydrateWorkspace();
  } catch (error) {
    setAuthMessage(error.message, true);
  }
}

async function logout() {
  try {
    await apiJson("/api/auth/logout", { method: "POST" });
  } finally {
    clearPolling();
    state.user = null;
    state.projects = [];
    state.selectedProject = null;
    state.currentRun = null;
    showView(false);
  }
}

async function hydrateWorkspace() {
  if (!state.user) {
    return;
  }
  setText("current-user", state.user.username);
  await Promise.all([loadProjects(), loadApprovals(), loadSettings()]);
  if (!state.selectedProject && state.projects.length) {
    await selectProject(state.projects[0].id);
  } else {
    renderProjects();
    renderConversation();
    renderDetail();
  }
}

async function loadProjects() {
  const payload = await apiJson("/api/projects");
  state.projects = payload.projects || [];
  if (
    state.selectedProject &&
    !state.projects.some((project) => project.id === state.selectedProject.id)
  ) {
    state.selectedProject = null;
  }
  renderProjects();
}

function renderProjects() {
  const list = byId("project-list");
  list.replaceChildren();
  if (!state.projects.length) {
    list.append(el("p", { className: "muted" }, ["No projects yet."]));
    return;
  }
  for (const project of state.projects) {
    const button = el(
      "button",
      {
        className:
          "project-item" +
          (state.selectedProject && state.selectedProject.id === project.id ? " active" : ""),
        type: "button",
      },
      [
        el("strong", {}, [project.name]),
        el("small", {}, [project.last_run_status || "no runs"]),
      ],
    );
    button.addEventListener("click", () => selectProject(project.id));
    list.append(button);
  }
}

async function selectProject(projectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) {
    return;
  }
  state.selectedProject = project;
  state.currentRun = null;
  clearPolling();
  renderProjects();
  setText("project-title", project.name);
  await loadMessages(project.id);
  renderConversation();
  renderDetail();
}

async function loadMessages(projectId) {
  const payload = await apiJson(`/api/projects/${projectId}/messages`);
  state.messages = payload.messages || [];
}

function renderConversation() {
  const list = byId("message-list");
  list.replaceChildren();
  if (!state.selectedProject) {
    list.append(el("li", { className: "message" }, ["Create or select a project to begin."]));
    setText("project-title", "Select a project");
    setRunPill("Idle");
    return;
  }
  if (!state.messages.length) {
    list.append(el("li", { className: "message" }, ["No messages yet. Start a run from the composer."]));
  }
  for (const message of state.messages) {
    list.append(el("li", { className: `message ${message.role || ""}` }, [message.content]));
  }
  const status = state.currentRun ? state.currentRun.status : state.selectedProject.last_run_status || "Idle";
  setRunPill(status);
}

function setRunPill(status) {
  const pill = byId("run-status-pill");
  pill.textContent = status || "Idle";
  pill.classList.toggle("warning", status === "needs_approval");
  pill.classList.toggle("danger", status === "failed");
}

function openProjectDialog() {
  const dialog = byId("project-dialog");
  byId("project-form").reset();
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeProjectDialog() {
  const dialog = byId("project-dialog");
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

async function createManualProject(event) {
  event.preventDefault();
  const indexValue = byId("project-index").value;
  try {
    const payload = await apiJson("/api/projects", {
      method: "POST",
      body: {
        name: byId("project-name").value,
        spec_text: byId("project-spec").value,
        checklist_text: byId("project-checklist").value,
        index_html: indexValue.trim() ? indexValue : null,
      },
    });
    closeProjectDialog();
    await loadProjects();
    await selectProject(payload.project.id);
    setMessage("Project created.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function startRun(event) {
  event.preventDefault();
  if (!state.selectedProject) {
    setMessage("Select a project before starting a run.", true);
    return;
  }
  const prompt = byId("run-prompt").value.trim();
  if (!prompt) {
    return;
  }
  const submitButton = byId("run-form").querySelector("button");
  submitButton.disabled = true;
  try {
    const payload = await apiJson(`/api/projects/${state.selectedProject.id}/runs`, {
      method: "POST",
      body: { prompt },
    });
    state.currentRun = payload.run;
    byId("run-prompt").value = "";
    await loadMessages(state.selectedProject.id);
    renderConversation();
    renderDetail();
    pollRun(state.currentRun.id);
    setMessage("Run started.");
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    submitButton.disabled = false;
  }
}

function pollRun(runId) {
  clearPolling();
  refreshRun(runId);
  state.pollTimer = window.setInterval(() => refreshRun(runId), 1500);
}

async function refreshRun(runId) {
  try {
    const payload = await apiJson(`/api/runs/${runId}`);
    state.currentRun = payload.run;
    setRunPill(state.currentRun.status);
    renderDetail();
    if (!["queued", "running"].includes(state.currentRun.status)) {
      clearPolling();
      await Promise.all([loadProjects(), loadApprovals()]);
      if (state.selectedProject) {
        await loadMessages(state.selectedProject.id);
      }
      renderConversation();
      renderDetail();
    }
  } catch (error) {
    clearPolling();
    setMessage(error.message, true);
  }
}

function clearPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function renderDetail() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });
  const content = byId("detail-content");
  content.replaceChildren();
  if (state.activeTab === "preview") {
    renderPreviewDetail(content);
  } else if (state.activeTab === "report") {
    renderReportDetail(content);
  } else if (state.activeTab === "approvals") {
    renderApprovalsDetail(content);
  } else if (state.activeTab === "settings") {
    renderSettingsDetail(content);
  } else {
    renderStatusDetail(content);
  }
}

function renderStatusDetail(content) {
  const card = el("section", { className: "detail-card" });
  card.append(el("h2", {}, ["Run status"]));
  const run = state.currentRun;
  const rows = [
    ["Project", state.selectedProject ? state.selectedProject.name : "None"],
    ["Run", run ? `#${run.id}` : "No active run"],
    ["Status", run ? run.status : state.selectedProject?.last_run_status || "Idle"],
    ["Trust", run ? run.trust_level || "pending" : "n/a"],
    ["Error", run ? run.error_message || "None" : "None"],
    ["Created", run ? run.created_at || "n/a" : "n/a"],
    ["Finished", run ? run.finished_at || "n/a" : "n/a"],
  ];
  const dl = el("dl", { className: "detail-grid" });
  for (const [label, value] of rows) {
    dl.append(el("dt", {}, [label]), el("dd", {}, [value]));
  }
  card.append(dl);
  content.append(card);
}

function renderReportDetail(content) {
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["Report summary"]));
  const run = state.currentRun;
  const rows = [
    ["Project", state.selectedProject ? state.selectedProject.name : "None"],
    ["Run", run ? `#${run.id}` : "No active run"],
    ["Status", run ? run.status : state.selectedProject?.last_run_status || "Idle"],
    ["Trust", run ? run.trust_level || "pending" : "n/a"],
    ["Error", run ? run.error_message || "None" : "None"],
    ["Created", run ? run.created_at || "n/a" : "n/a"],
    ["Started", run ? run.started_at || "n/a" : "n/a"],
    ["Finished", run ? run.finished_at || "n/a" : "n/a"],
  ];
  const dl = el("dl", { className: "detail-grid" });
  for (const [label, value] of rows) {
    dl.append(el("dt", {}, [label]), el("dd", {}, [value]));
  }
  card.append(dl);

  const links = el("div", { className: "stack" });
  if (run && run.index_artifact_url) {
    links.append(el("a", { href: run.index_artifact_url, download: "index.html" }, ["Download index.html"]));
  }
  if (run && run.zip_artifact_url) {
    links.append(el("a", { href: run.zip_artifact_url, download: "result.zip" }, ["Download result.zip"]));
  }
  if (!links.childElementCount) {
    links.append(el("p", { className: "muted" }, ["No artifacts are available for this run yet."]));
  }
  card.append(links);
  content.append(card);
}

function renderPreviewDetail(content) {
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["HTML source"]));
  const pre = el("pre", { className: "source-view" }, ["Loading source..."]);
  card.append(pre);

  const runUrl = state.currentRun && state.currentRun.index_artifact_url;
  if (runUrl) {
    card.append(el("a", { href: runUrl, download: "index.html" }, ["Download generated index.html"]));
    apiText(runUrl)
      .then((source) => {
        pre.textContent = source;
      })
      .catch((error) => {
        pre.textContent = `Generated source is not available: ${error.message}`;
      });
  } else if (state.selectedProject) {
    apiText(`/api/projects/${state.selectedProject.id}/preview`)
      .then((source) => {
        pre.textContent = source;
      })
      .catch(() => {
        pre.textContent = "No project preview source is available yet.";
      });
  } else {
    pre.textContent = "Select a project to inspect source.";
  }
  content.append(card);
}

function renderApprovalsDetail(content) {
  const wrapper = el("section", { className: "stack" });
  wrapper.append(el("h2", {}, ["Approvals"]));
  if (!state.approvals.length) {
    wrapper.append(el("p", { className: "muted" }, ["No approvals are waiting."]));
    content.append(wrapper);
    return;
  }
  for (const approval of state.approvals) {
    const item = el("article", { className: "approval-item" });
    item.append(el("strong", {}, [`${approval.action_name || "action"} on ${approval.target_path || "workspace"}`]));
    item.append(el("span", { className: "pill" }, [approval.status]));
    if (approval.reason) {
      item.append(el("p", {}, [approval.reason]));
    }
    if (approval.preview_json) {
      item.append(el("pre", { className: "source-view" }, [approval.preview_json]));
    }
    const actions = el("div", { className: "approval-actions" });
    const approve = el("button", { type: "button" }, ["Approve"]);
    approve.disabled = approval.status !== "pending";
    approve.addEventListener("click", () => approveApproval(approval.id));
    const deny = el("button", { type: "button", className: "secondary" }, ["Deny"]);
    deny.disabled = approval.status !== "pending";
    deny.addEventListener("click", () => denyApproval(approval.id));
    const resume = el("button", { type: "button", className: "secondary" }, ["Resume run"]);
    resume.addEventListener("click", () => resumeRun(approval.run_id));
    actions.append(approve, deny, resume);
    item.append(actions);
    wrapper.append(item);
  }
  content.append(wrapper);
}

function renderSettingsDetail(content) {
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["Settings"]));
  const settings = state.settings;
  if (!settings) {
    card.append(el("p", { className: "muted" }, ["Settings have not loaded yet."]));
  } else {
    const dl = el("dl", { className: "detail-grid" });
    for (const [label, value] of [
      ["Governance", settings.governance_profile],
      ["Context", settings.context_strategy],
      ["LLM mode", settings.llm_mode],
      ["API key", settings.api_key_configured ? "configured" : "not configured"],
      ["Storage", settings.api_key_storage],
    ]) {
      dl.append(el("dt", {}, [label]), el("dd", {}, [value]));
    }
    card.append(dl);
  }
  content.append(card);
}

async function loadApprovals() {
  const payload = await apiJson("/api/approvals");
  state.approvals = payload.approvals || [];
}

async function approveApproval(approvalId) {
  try {
    await apiJson(`/api/approvals/${approvalId}/approve`, { method: "POST" });
    await loadApprovals();
    renderDetail();
    setMessage("Approval accepted.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function denyApproval(approvalId) {
  const reason = window.prompt("Reason for denial");
  if (!reason || !reason.trim()) {
    return;
  }
  try {
    await apiJson(`/api/approvals/${approvalId}/deny`, {
      method: "POST",
      body: { reason },
    });
    await loadApprovals();
    renderDetail();
    setMessage("Approval denied.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function resumeRun(runId = null) {
  const id = runId || (state.currentRun && state.currentRun.id);
  if (!id) {
    setMessage("No run is available to resume.", true);
    return;
  }
  try {
    const payload = await apiJson(`/api/runs/${id}/resume`, { method: "POST" });
    state.currentRun = payload.run;
    pollRun(state.currentRun.id);
    setMessage("Run resumed.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function loadSettings() {
  const payload = await apiJson("/api/settings");
  state.settings = payload.settings;
  byId("governance-profile").value = state.settings.governance_profile;
  byId("context-strategy").value = state.settings.context_strategy;
  setText(
    "settings-api-state",
    state.settings.api_key_configured ? "API key: configured" : "API key: not configured",
  );
}

async function updateSettings(event) {
  event.preventDefault();
  try {
    const payload = await apiJson("/api/settings", {
      method: "PUT",
      body: {
        governance_profile: byId("governance-profile").value,
        context_strategy: byId("context-strategy").value,
      },
    });
    state.settings = payload.settings;
    await loadSettings();
    renderDetail();
    setMessage("Settings saved.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function saveApiKey(event) {
  event.preventDefault();
  const apiKey = byId("api-key-input").value;
  if (!apiKey.trim()) {
    setMessage("Enter an API key first.", true);
    return;
  }
  try {
    const payload = await apiJson("/api/settings/api-key", {
      method: "PUT",
      body: { api_key: apiKey },
    });
    state.settings = payload.settings;
    byId("api-key-input").value = "";
    await loadSettings();
    renderDetail();
    setMessage("API key stored.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function clearApiKey() {
  try {
    const payload = await apiJson("/api/settings/api-key", { method: "DELETE" });
    state.settings = payload.settings;
    await loadSettings();
    renderDetail();
    setMessage("API key cleared.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

window.SpecGateWeb = {
  startRun,
  loadSettings,
  approveApproval,
  denyApproval,
  resumeRun,
  escapeHtml,
};

document.addEventListener("DOMContentLoaded", init);
