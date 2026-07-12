const state = {
  user: null,
  projects: [],
  selectedProject: null,
  messages: [],
  currentRun: null,
  runDebug: null,
  approvals: [],
  settings: null,
  view: "conversation",
  viewBackStack: [],
  viewForwardStack: [],
  sidebarCollapsed: false,
  sidebarPeeking: false,
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
  if (node) {
    node.textContent = value || "";
    node.classList.toggle("error", Boolean(isError));
  }
}

function setAuthMessage(value, isError = false) {
  const node = byId("auth-message");
  if (node) {
    node.textContent = value || "";
    node.classList.toggle("error", Boolean(isError));
  }
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
  const authView = byId("auth-view");
  const workspaceView = byId("workspace-view");
  if (authView) {
    authView.hidden = isAuthed;
  }
  if (workspaceView) {
    workspaceView.hidden = !isAuthed;
  }
}

function on(id, eventName, handler) {
  const node = byId(id);
  if (node) {
    node.addEventListener(eventName, handler);
  }
}

function resetViewHistory(view = "conversation") {
  state.view = view;
  state.viewBackStack = [];
  state.viewForwardStack = [];
}

function pushView(view) {
  if (!view || view === state.view) {
    return;
  }
  state.viewBackStack.push(state.view);
  state.view = view;
  state.viewForwardStack = [];
  renderWorkspaceView();
}

function goBack() {
  const previous = state.viewBackStack.pop();
  if (!previous) {
    return;
  }
  state.viewForwardStack.push(state.view);
  state.view = previous;
  renderWorkspaceView();
}

function goForward() {
  const next = state.viewForwardStack.pop();
  if (!next) {
    return;
  }
  state.viewBackStack.push(state.view);
  state.view = next;
  renderWorkspaceView();
}

function renderWorkspaceView() {
  if (state.view.startsWith("detail-")) {
    state.activeTab = state.view.replace("detail-", "") || "status";
  }
  const messages = byId("message-list");
  const detail = byId("detail-content");
  const runForm = byId("run-form");
  const showingDetail = state.view !== "conversation";
  if (messages) {
    messages.hidden = showingDetail;
  }
  if (detail) {
    detail.hidden = !showingDetail;
  }
  if (runForm) {
    runForm.hidden = showingDetail;
  }
  if (showingDetail) {
    renderDetail();
  } else {
    renderConversation();
  }
}

function closeAllMenus() {
  document.querySelectorAll(".menu-popover").forEach((menu) => {
    menu.hidden = true;
    const button = menu.id ? document.querySelector(`[aria-controls="${menu.id}"]`) : null;
    if (button) {
      button.setAttribute("aria-expanded", "false");
    }
  });
}

function toggleMenu(buttonId, menuId) {
  const button = byId(buttonId);
  const menu = byId(menuId);
  if (!button || !menu) {
    return;
  }
  const willOpen = menu.hidden;
  closeAllMenus();
  menu.hidden = !willOpen;
  button.setAttribute("aria-expanded", String(willOpen));
}

function openProjectMenu() {
  toggleMenu("project-menu-button", "project-menu");
}

function runCommand(command) {
  closeAllMenus();
  if (command === "new-window") {
    openNewWindow();
  } else if (command === "new-project") {
    openProjectDialog();
  } else if (command === "close-project") {
    closeCurrentProject();
  } else if (command === "settings") {
    pushView("detail-settings");
  } else if (command === "logout") {
    logout();
  } else if (command === "exit") {
    exitWindow();
  } else if (command === "search" || command === "search-projects") {
    openSearchDialog();
  } else if (command === "about") {
    openAboutDialog();
  }
}

function openNewWindow() {
  window.open(window.location.href, "_blank", "noopener");
}

function exitWindow() {
  window.close();
  setMessage("如果浏览器阻止关闭，请直接关闭当前页签。");
}

function applySidebarState() {
  document.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  document.body.classList.toggle("sidebar-peeking", state.sidebarPeeking);
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  state.sidebarPeeking = false;
  applySidebarState();
}

function showSidebarPeek() {
  if (state.sidebarCollapsed) {
    state.sidebarPeeking = true;
    applySidebarState();
  }
}

function hideSidebarPeek() {
  if (state.sidebarPeeking) {
    state.sidebarPeeking = false;
    applySidebarState();
  }
}

function closeCurrentProject() {
  state.selectedProject = null;
  state.messages = [];
  state.currentRun = null;
  state.runDebug = null;
  clearPolling();
  resetViewHistory("conversation");
  renderProjects();
  renderWorkspaceView();
  setMessage("Project closed.");
}

function openAboutDialog() {
  const dialog = byId("about-dialog");
  if (!dialog) {
    return;
  }
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeAboutDialog() {
  const dialog = byId("about-dialog");
  if (!dialog) {
    return;
  }
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function clearAuthForm() {
  const form = byId("auth-form");
  if (form) {
    form.reset();
  }
  setAuthMessage("");
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
  on("auth-form", "submit", (event) => {
    event.preventDefault();
    login();
  });
  on("register-button", "click", register);
  on("sidebar-toggle-button", "click", toggleSidebar);
  on("back-button", "click", goBack);
  on("forward-button", "click", goForward);
  on("file-menu-button", "click", (event) => {
    event.stopPropagation();
    toggleMenu("file-menu-button", "file-menu");
  });
  on("edit-menu-button", "click", (event) => {
    event.stopPropagation();
    toggleMenu("edit-menu-button", "edit-menu");
  });
  on("help-menu-button", "click", (event) => {
    event.stopPropagation();
    toggleMenu("help-menu-button", "help-menu");
  });
  on("project-menu-button", "click", (event) => {
    event.stopPropagation();
    openProjectMenu();
  });
  on("new-project-button", "click", () => runCommand("new-project"));
  on("search-project-button", "click", () => runCommand("search"));
  on("sidebar-settings-button", "click", () => pushView("detail-settings"));
  on("sidebar-edge-hotzone", "mouseenter", showSidebarPeek);
  on("project-sidebar", "mouseleave", hideSidebarPeek);
  on("close-project-dialog", "click", closeProjectDialog);
  on("cancel-project-button", "click", closeProjectDialog);
  on("project-form", "submit", createManualProject);
  on("run-form", "submit", startRun);
  on("project-search-input", "input", renderSearchResults);
  on("close-search-dialog", "click", closeSearchDialog);
  on("close-about-dialog", "click", closeAboutDialog);
  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      runCommand(button.dataset.command);
    });
  });
  document.querySelectorAll("[data-detail-view]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      pushView(button.dataset.detailView);
      closeAllMenus();
    });
  });
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      pushView(`detail-${state.activeTab}`);
    });
  });
  document.addEventListener("keydown", handleGlobalShortcut);
  document.addEventListener("click", (event) => {
    if (
      event.target instanceof Element &&
      !event.target.closest(".menu-group") &&
      !event.target.closest("#project-menu")
    ) {
      closeAllMenus();
    }
  });
  applySidebarState();
}

function handleGlobalShortcut(event) {
  if (!event.ctrlKey || event.altKey || event.metaKey) {
    return;
  }
  const key = event.key.toLowerCase();
  const target = event.target;
  const isEditable =
    target instanceof Element &&
    (target.matches("input, textarea, select") || target.isContentEditable);
  let command = null;
  if (event.shiftKey && key === "n") {
    command = "new-window";
  } else if (!event.shiftKey && key === "n") {
    command = "new-project";
  } else if (!event.shiftKey && key === "g") {
    command = "search";
  } else if (!event.shiftKey && key === "q") {
    command = "exit";
  } else if (!event.shiftKey && key === ",") {
    command = "settings";
  } else if (!event.shiftKey && key === "w") {
    command = "close-project";
  } else if (!event.shiftKey && key === "b") {
    event.preventDefault();
    toggleSidebar();
    return;
  } else if (!event.shiftKey && key === "[") {
    event.preventDefault();
    goBack();
    return;
  } else if (!event.shiftKey && key === "]") {
    event.preventDefault();
    goForward();
    return;
  } else if (isEditable) {
    return;
  }
  if (command) {
    event.preventDefault();
    runCommand(command);
  }
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
    state.messages = [];
    state.currentRun = null;
    state.runDebug = null;
    state.approvals = [];
    state.settings = null;
    resetViewHistory("conversation");
    closeAllMenus();
    closeProjectDialog();
    closeSearchDialog();
    closeAboutDialog();
    state.sidebarPeeking = false;
    applySidebarState();
    clearAuthForm();
    renderProjects();
    renderWorkspaceView();
    setText("project-title", "Select a project");
    setRunPill("Idle");
    setMessage("");
    showView(false);
  }
}

async function hydrateWorkspace() {
  if (!state.user) {
    return;
  }
  setText("current-user", state.user.username);
  resetViewHistory("conversation");
  await Promise.all([loadProjects(), loadApprovals(), loadSettings()]);
  if (!state.selectedProject && state.projects.length) {
    await selectProject(state.projects[0].id);
  } else {
    renderProjects();
    renderWorkspaceView();
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
  if (!list) {
    return;
  }
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
  renderWorkspaceView();
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
  if (!list) {
    return;
  }
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
  if (pill) {
    pill.textContent = status || "Idle";
    pill.classList.toggle("warning", status === "needs_approval");
    pill.classList.toggle("danger", status === "failed");
  }
}

function openProjectDialog() {
  const dialog = byId("project-dialog");
  const form = byId("project-form");
  if (!dialog) {
    return;
  }
  if (form) {
    form.reset();
  }
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeProjectDialog() {
  const dialog = byId("project-dialog");
  if (!dialog) {
    return;
  }
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function openSearchDialog() {
  const dialog = byId("search-dialog");
  const input = byId("project-search-input");
  if (!dialog) {
    return;
  }
  if (input) {
    input.value = "";
  }
  renderSearchResults();
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
  if (input) {
    input.focus();
  }
}

function closeSearchDialog() {
  const dialog = byId("search-dialog");
  if (!dialog) {
    return;
  }
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function renderSearchResults() {
  const results = byId("search-results");
  const input = byId("project-search-input");
  if (!results) {
    return;
  }
  const query = input ? input.value.trim().toLowerCase() : "";
  const matches = state.projects.filter((project) => project.name.toLowerCase().includes(query));
  results.replaceChildren();
  if (!matches.length) {
    results.append(el("p", { className: "muted" }, ["No projects found."]));
    return;
  }
  for (const project of matches) {
    const button = el("button", { type: "button", className: "project-item" }, [
      el("strong", {}, [project.name]),
      el("small", {}, [project.last_run_status || "no runs"]),
    ]);
    button.addEventListener("click", async () => {
      closeSearchDialog();
      await selectProject(project.id);
    });
    results.append(button);
  }
}

async function readProjectFile(inputId) {
  const input = byId(inputId);
  const file = input && input.files ? input.files[0] : null;
  if (!file) {
    return "";
  }
  return file.text();
}

async function createManualProject(event) {
  event.preventDefault();
  const nameInput = byId("project-name");
  try {
    const specText = await readProjectFile("project-spec-file");
    const checklistText = await readProjectFile("project-checklist-file");
    const indexValue = await readProjectFile("project-index-file");
    const payload = await apiJson("/api/projects", {
      method: "POST",
      body: {
        name: nameInput ? nameInput.value : "",
        spec_text: specText,
        checklist_text: checklistText,
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
  const promptInput = byId("run-prompt");
  const prompt = promptInput ? promptInput.value.trim() : "";
  if (!prompt) {
    return;
  }
  const form = byId("run-form");
  const submitButton = form ? form.querySelector("button") : null;
  if (submitButton) {
    submitButton.disabled = true;
  }
  try {
    const payload = await apiJson(`/api/projects/${state.selectedProject.id}/runs`, {
      method: "POST",
      body: { prompt },
    });
    state.currentRun = payload.run;
    state.runDebug = null;
    const promptInput = byId("run-prompt");
    if (promptInput) {
      promptInput.value = "";
    }
    await loadMessages(state.selectedProject.id);
    renderWorkspaceView();
    pollRun(state.currentRun.id);
    setMessage("Run started.");
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
    }
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
      renderWorkspaceView();
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
  if (state.view.startsWith("detail-")) {
    state.activeTab = state.view.replace("detail-", "") || "status";
  }
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });
  document.querySelectorAll("[data-detail-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.detailView === `detail-${state.activeTab}`);
  });
  const content = byId("detail-content");
  if (!content) {
    return;
  }
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
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["运行工作台"]));
  const run = state.currentRun;
  if (!state.selectedProject) {
    card.append(el("p", { className: "muted" }, ["请先创建或选择项目。"]));
    content.append(card);
    return;
  }
  if (!run) {
    card.append(el("p", { className: "muted" }, ["当前项目还没有运行。"]));
    card.append(renderBasicRunRows(null));
    content.append(card);
    return;
  }

  const body = el("div", { className: "run-workspace" }, ["正在加载运行证据..."]);
  card.append(body);
  content.append(card);

  const existing = state.runDebug && state.runDebug.run && state.runDebug.run.id === run.id;
  const loader = existing ? Promise.resolve(state.runDebug) : loadRunDebug(run.id);
  loader
    .then((debug) => {
      body.replaceChildren(renderRunWorkspace(debug));
    })
    .catch((error) => {
      body.replaceChildren(
        renderBasicRunRows(run),
        el("p", { className: "message-line error" }, [`运行证据暂不可用：${error.message}`]),
      );
    });
}

function renderBasicRunRows(run) {
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
  return dl;
}

function renderRunWorkspace(debug) {
  const wrapper = el("div", { className: "run-workspace stack" });
  wrapper.append(renderBasicRunRows(debug.run || state.currentRun));
  wrapper.append(renderRunWorkspaceMetrics(debug));
  wrapper.append(renderRunWorkspaceFlow(debug));
  wrapper.append(renderRunWorkspaceArtifacts(debug));
  wrapper.append(renderRunWorkspaceApprovals(debug));
  return wrapper;
}

function renderRunWorkspaceMetrics(debug) {
  const strategy = auditRunStrategy(debug);
  const summary = latestRunSummary(debug);
  const metrics = summary.metrics || {};
  const items = [
    ["治理策略", strategy.governanceProfile],
    ["上下文策略", strategy.contextStrategy],
    ["运行模式", strategy.llmMode],
    ["LLM 调用", metrics.llm_calls ?? 0],
    ["工具调用", metrics.tool_calls ?? 0],
    ["Gate 次数", metrics.gate_runs ?? 0],
    ["阻止动作", metrics.blocked_actions ?? 0],
    ["审批请求", metrics.approval_requests ?? 0],
    ["RAG 查询", metrics.retrieval_queries ?? 0],
    ["最大上下文", metrics.context_chars_max ?? 0],
  ];
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["策略与指标"]));
  const grid = el("div", { className: "run-workspace-grid" });
  for (const [label, value] of items) {
    grid.append(el("div", { className: "audit-metric" }, [el("span", {}, [label]), el("strong", {}, [value])]));
  }
  section.append(grid);
  return section;
}

function renderRunWorkspaceFlow(debug) {
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["执行流程"]));
  const events = ((debug.trace && debug.trace.events) || []).slice(0, 6);
  if (!events.length) {
    section.append(el("p", { className: "muted" }, ["本次运行还没有流程事件。"]));
    return section;
  }
  const list = el("ol", { className: "run-flow" });
  for (const event of events) {
    const payload = event.payload || {};
    const step = payload.step ? `Step ${payload.step}` : event.event_type || "event";
    list.append(
      el("li", { className: "run-flow-item" }, [
        el("strong", {}, [translateTraceEvent(event.event_type)]),
        el("small", {}, [step]),
        el("p", {}, [describeTraceEvent(event)]),
      ]),
    );
  }
  section.append(list);
  const trace = debug.trace || {};
  if (trace.truncated || (trace.total_events || 0) > events.length) {
    section.append(el("p", { className: "muted" }, ["更多流程细节请查看 Audit。"]));
  }
  return section;
}

function renderRunWorkspaceArtifacts(debug) {
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["产物"]));
  const artifacts = debug.artifacts || [];
  if (!artifacts.length) {
    section.append(el("p", { className: "muted" }, ["暂无产物。"]));
    return section;
  }
  const list = el("div", { className: "artifact-list" });
  for (const artifact of artifacts) {
    const item = el("div", { className: "artifact-item" });
    item.append(el("strong", {}, [artifact.kind || "artifact"]));
    item.append(el("span", { className: artifact.exists ? "pill" : "pill danger" }, [artifact.exists ? "已生成" : "缺失"]));
    item.append(el("small", {}, [formatBytes(artifact.size_bytes || 0)]));
    if (artifact.exists && artifact.download_url) {
      item.append(
        el(
          "a",
          { href: artifact.download_url, download: artifact.kind === "zip" ? "result.zip" : "index.html" },
          ["下载"],
        ),
      );
    }
    list.append(item);
  }
  section.append(list);
  return section;
}

function renderRunWorkspaceApprovals(debug) {
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["审批"]));
  const approvals = debug.approvals || [];
  const run = debug.run || state.currentRun || {};
  if (!approvals.length && run.status !== "needs_approval") {
    section.append(el("p", { className: "muted" }, ["无待处理审批。"]));
    return section;
  }
  section.append(el("p", {}, [`审批数量：${approvals.length}`]));
  const button = el("button", { type: "button", className: "secondary" }, ["前往审批"]);
  button.addEventListener("click", () => {
    pushView("detail-approvals");
  });
  section.append(button);
  return section;
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (size >= 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${size} B`;
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
  const runStrategy = auditRunStrategy(debug);
  const evidenceState = Object.entries(evidence)
    .map(([key, value]) => `${translateEvidenceKey(key)}：${value ? "已记录" : "本次未启用"}`)
    .join("，");
  const rows = [
    ["治理策略", runStrategy.governanceProfile],
    ["上下文策略", runStrategy.contextStrategy],
    ["运行模式", runStrategy.llmMode],
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

function auditRunStrategy(debug) {
  const events = (debug.trace && debug.trace.events) || [];
  let contextStrategy = "未知";
  let governanceProfile = "未知";
  for (const event of events) {
    if (event.event_type === "context_built" && event.payload && event.payload.strategy) {
      contextStrategy = event.payload.strategy;
    }
    if (event.event_type === "run_summary" && event.payload && event.payload.profile) {
      governanceProfile = event.payload.profile;
    }
  }
  return { governanceProfile, contextStrategy, llmMode: "MockLLM" };
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
  const governanceProfile = byId("governance-profile");
  const contextStrategy = byId("context-strategy");
  if (governanceProfile) {
    governanceProfile.value = state.settings.governance_profile;
  }
  if (contextStrategy) {
    contextStrategy.value = state.settings.context_strategy;
  }
  setText(
    "settings-api-state",
    state.settings.api_key_configured ? "API key: configured" : "API key: not configured",
  );
}

async function updateSettings(event) {
  event.preventDefault();
  const governanceProfile = byId("governance-profile");
  const contextStrategy = byId("context-strategy");
  if (!governanceProfile || !contextStrategy) {
    return;
  }
  try {
    const payload = await apiJson("/api/settings", {
      method: "PUT",
      body: {
        governance_profile: governanceProfile.value,
        context_strategy: contextStrategy.value,
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
  const apiKeyInput = byId("api-key-input");
  const apiKey = apiKeyInput ? apiKeyInput.value : "";
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
    if (apiKeyInput) {
      apiKeyInput.value = "";
    }
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
  pushView,
  goBack,
  goForward,
  closeCurrentProject,
  toggleSidebar,
  showSidebarPeek,
  hideSidebarPeek,
  openSearchDialog,
  renderSearchResults,
  openNewWindow,
  exitWindow,
  clearAuthForm,
  renderWorkspaceView,
  openProjectMenu,
  readProjectFile,
  escapeHtml,
};

document.addEventListener("DOMContentLoaded", init);
