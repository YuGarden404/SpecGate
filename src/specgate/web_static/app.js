const state = {
  user: null,
  projects: [],
  selectedProject: null,
  messages: [],
  currentRun: null,
  runDebug: null,
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
    state.runDebug = null;
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
  state.runDebug = null;
  clearPolling();
  renderProjects();
  setText("project-title", project.name);
  await loadMessages(project.id);
  await loadLatestProjectRun(project);
  renderConversation();
  renderDetail();
}

async function loadMessages(projectId) {
  const payload = await apiJson(`/api/projects/${projectId}/messages`);
  state.messages = payload.messages || [];
}

async function loadLatestProjectRun(project) {
  state.currentRun = null;
  if (!project || !project.latest_run_id) {
    return;
  }
  try {
    const payload = await apiJson(`/api/runs/${project.latest_run_id}`);
    state.currentRun = payload.run;
    state.runDebug = null;
  } catch (error) {
    setMessage(`Latest run could not be loaded: ${error.message}`, true);
  }
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
    state.runDebug = null;
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
    state.runDebug = null;
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
  } else if (state.activeTab === "audit") {
    renderAuditDetail(content);
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

async function loadRunDebug(runId) {
  const payload = await apiJson(`/api/runs/${runId}/debug`);
  state.runDebug = payload.debug;
  return state.runDebug;
}

function renderAuditDetail(content) {
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["审计 / 调试"]));
  const run = state.currentRun;
  if (!run) {
    card.append(el("p", { className: "muted" }, ["当前没有可检查的运行。"]));
    content.append(card);
    return;
  }

  const body = el("div", { className: "audit-summary" }, ["正在加载审计数据..."]);
  const pre = el("pre", { className: "source-view" }, [""]);
  card.append(body);
  content.append(card);

  const existing = state.runDebug && state.runDebug.run && state.runDebug.run.id === run.id;
  const loader = existing ? Promise.resolve(state.runDebug) : loadRunDebug(run.id);
  loader
    .then((debug) => {
      body.replaceChildren(
        renderAuditOverview(debug),
        renderAuditMetrics(debug),
        renderAuditTimeline(debug),
        renderAuditEvidence(debug),
        el("h3", {}, ["原始 JSON"]),
        pre,
      );
      pre.textContent = JSON.stringify(debug, null, 2);
    })
    .catch((error) => {
      body.textContent = `审计数据不可用：${error.message}`;
      pre.textContent = "";
    });
}

function renderAuditOverview(debug) {
  const wrapper = el("div", { className: "audit-summary" });
  const summary = debug.summary || {};
  const trace = debug.trace || {};
  const evidence = debug.evidence || {};
  const evidenceState = Object.entries(evidence)
    .map(([key, value]) => `${translateEvidenceKey(key)}：${value ? "已记录" : "本次未启用"}`)
    .join("，");
  const rows = [
    ["状态", translateRunStatus(summary.status)],
    ["信任等级", translateTrustLevel(summary.trust_level)],
    ["产物数量", String(summary.artifact_count ?? 0)],
    ["审批数量", String(summary.approval_count ?? 0)],
    ["Trace 事件", `${summary.trace_event_count ?? 0}${trace.truncated ? "（已截断）" : ""}`],
    ["Evidence", evidenceState || "无"],
  ];
  wrapper.append(el("h3", {}, ["运行概览"]));
  const dl = el("dl", { className: "detail-grid" });
  for (const [label, value] of rows) {
    dl.append(el("dt", {}, [label]), el("dd", {}, [value]));
  }
  wrapper.append(dl);

  const links = el("div", { className: "audit-links" });
  for (const artifact of debug.artifacts || []) {
    if (artifact.download_url && artifact.exists) {
      links.append(
        el(
          "a",
          {
            href: artifact.download_url,
            download: artifact.kind === "zip" ? "result.zip" : "index.html",
          },
          [`下载 ${artifact.kind}`],
        ),
      );
    }
  }
  if (links.childElementCount) {
    wrapper.append(links);
  }
  return wrapper;
}

function renderAuditMetrics(debug) {
  const wrapper = el("section", { className: "audit-section" });
  wrapper.append(el("h3", {}, ["关键指标"]));
  const summary = latestRunSummary(debug);
  const metrics = (summary && summary.metrics) || {};
  const items = [
    ["LLM 调用", metrics.llm_calls ?? 0],
    ["工具调用", metrics.tool_calls ?? 0],
    ["被阻止动作", metrics.blocked_actions ?? 0],
    ["Gate 次数", metrics.gate_runs ?? 0],
    ["Gate 失败", metrics.gate_failures ?? 0],
    ["审批请求", metrics.approval_requests ?? 0],
    ["RAG 查询", metrics.retrieval_queries ?? 0],
    ["压缩输入", metrics.compression_original_chars ?? 0],
    ["压缩输出", metrics.compression_compressed_chars ?? 0],
    ["角色运行", metrics.role_runs ?? 0],
  ];
  const grid = el("div", { className: "audit-metrics" });
  for (const [label, value] of items) {
    grid.append(el("div", { className: "audit-metric" }, [el("span", {}, [label]), el("strong", {}, [value])]));
  }
  wrapper.append(grid);
  return wrapper;
}

function renderAuditTimeline(debug) {
  const wrapper = el("section", { className: "audit-section" });
  wrapper.append(el("h3", {}, ["执行流程"]));
  const events = (debug.trace && debug.trace.events) || [];
  if (!events.length) {
    wrapper.append(el("p", { className: "muted" }, ["本次运行没有 Trace 事件。"]));
    return wrapper;
  }
  const list = el("ol", { className: "audit-timeline" });
  for (const event of events) {
    const payload = event.payload || {};
    const step = payload.step || payload.result?.step;
    const title = translateTraceEvent(event.event_type);
    const detail = describeTraceEvent(event);
    const meta = step ? `Step ${step}` : event.event_type || "event";
    list.append(
      el("li", { className: "audit-event" }, [
        el("strong", {}, [title]),
        el("small", {}, [meta]),
        el("p", {}, [detail]),
      ]),
    );
  }
  wrapper.append(list);
  return wrapper;
}

function renderAuditEvidence(debug) {
  const wrapper = el("section", { className: "audit-section" });
  wrapper.append(el("h3", {}, ["Evidence 状态"]));
  const evidence = debug.evidence || {};
  const rows = [
    ["RAG 检索证据", evidence.retrieval],
    ["上下文压缩证据", evidence.compression],
    ["多代理隔离证据", evidence.isolation],
    ["安全评估证据", evidence.security],
  ];
  const dl = el("dl", { className: "detail-grid" });
  for (const [label, value] of rows) {
    dl.append(el("dt", {}, [label]), el("dd", {}, [value ? "已记录" : "本次未启用"]));
  }
  wrapper.append(dl);
  return wrapper;
}

function latestRunSummary(debug) {
  const events = (debug.trace && debug.trace.events) || [];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index].event_type === "run_summary") {
      return events[index].payload || {};
    }
  }
  return {};
}

function translateRunStatus(status) {
  const values = {
    completed: "已完成",
    running: "运行中",
    queued: "排队中",
    failed: "失败",
    needs_approval: "等待审批",
  };
  return values[status] || status || "未知";
}

function translateTrustLevel(level) {
  const values = {
    trusted: "可信",
    warning: "警告",
    failed: "失败",
  };
  return values[level] || level || "未知";
}

function translateEvidenceKey(key) {
  const values = {
    retrieval: "RAG",
    compression: "压缩",
    isolation: "隔离",
    security: "安全",
  };
  return values[key] || key;
}

function translateTraceEvent(eventType) {
  const values = {
    context_built: "构建上下文",
    llm_response: "LLM 返回动作",
    permission_decision: "权限判定",
    tool_result: "工具执行",
    gate_result: "Gate 校验",
    run_summary: "运行总结",
  };
  return values[eventType] || "其他事件";
}

function describeTraceEvent(event) {
  const payload = event.payload || {};
  if (event.event_type === "context_built") {
    return `策略 ${payload.strategy || "unknown"}，上下文 ${payload.context_chars ?? 0} 字符。`;
  }
  if (event.event_type === "llm_response") {
    return "模型返回了下一步结构化动作。";
  }
  if (event.event_type === "permission_decision") {
    return `${payload.action || "action"} ${payload.allowed ? "允许" : "拒绝"}：${payload.reason || "无原因"}`;
  }
  if (event.event_type === "tool_result") {
    const result = payload.result || {};
    return `${result.action || "tool"} ${result.ok ? "执行成功" : "执行失败"}：${result.message || "无消息"}`;
  }
  if (event.event_type === "gate_result") {
    return `${payload.passed ? "通过" : "未通过"}：${payload.summary || "无摘要"}`;
  }
  if (event.event_type === "run_summary") {
    const trust = payload.trust || {};
    return `最终状态 ${translateTrustLevel(trust.status)}，原因：${(trust.reasons || []).join(", ") || "无"}`;
  }
  return event.event_type || "未分类事件";
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
  loadLatestProjectRun,
  loadSettings,
  loadRunDebug,
  approveApproval,
  denyApproval,
  resumeRun,
  escapeHtml,
};

document.addEventListener("DOMContentLoaded", init);
