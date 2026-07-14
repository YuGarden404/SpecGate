# WebUI Codex Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SpecGate 登录后的 WebUI 重构为 Codex-like 两栏工作台，包含顶部菜单、项目侧栏、居中对话区、项目详情菜单、搜索弹窗、文件导入新项目和全局快捷键。

**Architecture:** 保持 FastAPI 后端、数据库、Runner、Mock LLM 和现有 API 不变，只重构 `web_static` 的 HTML/CSS/JS。前端新增轻量 Shell 状态：当前视图、前进后退栈、侧栏折叠状态、搜索弹窗状态，并复用现有运行详情渲染函数。

**Tech Stack:** 原生 HTML dialog、原生 CSS、原生 JavaScript、Python `unittest` 静态断言、现有 WebUI API。

---

## File Structure

- Modify: `tests/test_web_static.py`
  - 负责静态结构、脚本 hook、样式 hook 的断言。
  - 先写失败测试，再改前端实现。
- Modify: `src/specgate/web_static/index.html`
  - 负责登录页、顶部菜单、两栏 Shell、项目弹窗、搜索弹窗、关于弹窗的静态 DOM。
- Modify: `src/specgate/web_static/app.js`
  - 负责 Shell 状态、视图历史、菜单动作、快捷键、项目文件导入、搜索、详情视图挂载、登出清理。
- Modify: `src/specgate/web_static/styles.css`
  - 负责 Codex-like 顶栏、侧栏、居中对话、详情视图、弹窗、折叠和 hover 唤起样式。

---

### Task 1: Static Tests for Codex Shell Contract

**Files:**
- Modify: `tests/test_web_static.py`

- [ ] **Step 1: Replace old three-column static assertions with Shell assertions**

In `tests/test_web_static.py`, update `test_index_contains_required_regions` to assert the new persistent regions:

```python
def test_index_contains_required_regions(self) -> None:
    html = read_static("index.html")
    for element_id in (
        "auth-view",
        "workspace-view",
        "app-menu-bar",
        "sidebar-toggle-button",
        "back-button",
        "forward-button",
        "project-sidebar",
        "project-list",
        "workspace-main",
        "workspace-titlebar",
        "message-list",
        "run-form",
        "project-dialog",
        "project-form",
        "search-dialog",
        "about-dialog",
    ):
        with self.subTest(element_id=element_id):
            self.assertIn(f'id="{element_id}"', html)
```

- [ ] **Step 2: Add static tests for top menus and shortcuts**

Add this test:

```python
def test_index_contains_codex_like_menu_bar(self) -> None:
    html = read_static("index.html")
    for text in (
        "文件",
        "编辑",
        "帮助",
        "新窗口",
        "Ctrl+Shift+N",
        "新项目",
        "Ctrl+N",
        "关闭",
        "Ctrl+W",
        "设置",
        "Ctrl+,",
        "登出",
        "退出",
        "Ctrl+Q",
        "搜索",
        "Ctrl+G",
        "关于 SpecGate",
    ):
        with self.subTest(text=text):
            self.assertIn(text, html)
    self.assertNotIn(">视图<", html)
```

- [ ] **Step 3: Add static tests for file import project dialog**

Add this test:

```python
def test_project_dialog_uses_file_import_fields(self) -> None:
    html = read_static("index.html")
    for element_id in (
        "project-name",
        "project-spec-file",
        "project-checklist-file",
        "project-index-file",
    ):
        with self.subTest(element_id=element_id):
            self.assertIn(f'id="{element_id}"', html)
    self.assertIn('type="file"', html)
    self.assertIn("spec.md", html)
    self.assertIn("checklist.md", html)
    self.assertIn("index.html", html)
    self.assertNotIn('id="project-spec" name="spec_text"', html)
    self.assertNotIn('id="project-checklist" name="checklist_text"', html)
```

- [ ] **Step 4: Add static tests for JS Shell hooks**

Add this test:

```python
def test_app_contains_codex_shell_workflows(self) -> None:
    app_js = read_static("app.js")
    for snippet in (
        "viewBackStack",
        "viewForwardStack",
        "function pushView",
        "function goBack",
        "function goForward",
        "function closeCurrentProject",
        "function toggleSidebar",
        "function showSidebarPeek",
        "function hideSidebarPeek",
        "function openSearchDialog",
        "function renderSearchResults",
        "async function readProjectFile",
        "function openNewWindow",
        "function exitWindow",
        "function clearAuthForm",
        "function renderWorkspaceView",
        "function openProjectMenu",
    ):
        with self.subTest(snippet=snippet):
            self.assertIn(snippet, app_js)
```

- [ ] **Step 5: Add static tests for CSS Shell hooks**

Replace `test_styles_include_codex_like_layout_hooks` with:

```python
def test_styles_include_codex_like_layout_hooks(self) -> None:
    css = read_static("styles.css")
    for selector in (
        ".app-menu-bar",
        ".menu-group",
        ".menu-popover",
        ".workspace-view",
        ".app-shell",
        ".project-sidebar",
        ".sidebar-edge-hotzone",
        ".workspace-main",
        ".workspace-titlebar",
        ".messages-frame",
        ".composer-frame",
        ".search-results",
        "body.sidebar-collapsed",
        "body.sidebar-peeking",
    ):
        with self.subTest(selector=selector):
            self.assertIn(selector, css)
```

- [ ] **Step 6: Run the focused failing tests**

Run:

```powershell
python -m unittest tests.test_web_static -v
```

Expected: FAIL because the current HTML still uses the old three-column `detail-panel` structure and does not contain the new Shell IDs.

- [ ] **Step 7: Commit the tests**

Run:

```powershell
git add tests/test_web_static.py
git commit -m "test: specify WebUI Codex shell contract"
```

---

### Task 2: HTML Shell Restructure

**Files:**
- Modify: `src/specgate/web_static/index.html`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Replace workspace HTML with top menu plus two-column Shell**

In `src/specgate/web_static/index.html`, replace the current `workspace-view` contents with this structure:

```html
<main id="workspace-view" class="workspace-view" hidden>
  <header id="app-menu-bar" class="app-menu-bar" aria-label="Application menu">
    <div class="window-controls">
      <button id="sidebar-toggle-button" type="button" class="icon-button" title="切换边栏 Ctrl+B" aria-label="切换边栏">☰</button>
      <button id="back-button" type="button" class="icon-button" title="返回 Ctrl+[" aria-label="返回">←</button>
      <button id="forward-button" type="button" class="icon-button" title="前进 Ctrl+]" aria-label="前进">→</button>
    </div>
    <nav class="menu-group" aria-label="Top menus">
      <div class="menu-root">
        <button id="file-menu-button" type="button" class="menu-button" aria-haspopup="true" aria-expanded="false">文件</button>
        <div id="file-menu" class="menu-popover" role="menu" hidden>
          <button type="button" role="menuitem" data-command="new-window"><span>新窗口</span><kbd>Ctrl+Shift+N</kbd></button>
          <button type="button" role="menuitem" data-command="new-project"><span>新项目</span><kbd>Ctrl+N</kbd></button>
          <button type="button" role="menuitem" data-command="close-project"><span>关闭</span><kbd>Ctrl+W</kbd></button>
          <hr>
          <button type="button" role="menuitem" data-command="settings"><span>设置</span><kbd>Ctrl+,</kbd></button>
          <hr>
          <button type="button" role="menuitem" data-command="logout"><span>登出</span></button>
          <button type="button" role="menuitem" data-command="exit"><span>退出</span><kbd>Ctrl+Q</kbd></button>
        </div>
      </div>
      <div class="menu-root">
        <button id="edit-menu-button" type="button" class="menu-button" aria-haspopup="true" aria-expanded="false">编辑</button>
        <div id="edit-menu" class="menu-popover" role="menu" hidden>
          <button type="button" role="menuitem" data-command="search-projects"><span>搜索</span><kbd>Ctrl+G</kbd></button>
        </div>
      </div>
      <div class="menu-root">
        <button id="help-menu-button" type="button" class="menu-button" aria-haspopup="true" aria-expanded="false">帮助</button>
        <div id="help-menu" class="menu-popover" role="menu" hidden>
          <button type="button" role="menuitem" data-command="about"><span>关于 SpecGate</span></button>
        </div>
      </div>
    </nav>
  </header>

  <div class="app-shell">
    <div id="sidebar-edge-hotzone" class="sidebar-edge-hotzone" aria-hidden="true"></div>
    <aside id="project-sidebar" class="project-sidebar" aria-label="项目">
      <div class="sidebar-actions">
        <button id="new-project-button" type="button">新项目</button>
        <button id="search-project-button" type="button" class="secondary">搜索</button>
      </div>
      <nav id="project-list" class="project-list" aria-label="项目列表"></nav>
      <button id="sidebar-settings-button" type="button" class="sidebar-settings">设置</button>
    </aside>

    <section id="workspace-main" class="workspace-main" aria-label="工作区">
      <header id="workspace-titlebar" class="workspace-titlebar">
        <div class="project-heading">
          <h1 id="project-title">选择项目</h1>
          <button id="project-menu-button" type="button" class="icon-button" aria-haspopup="true" aria-expanded="false" title="项目详情">...</button>
          <div id="project-menu" class="menu-popover project-menu" role="menu" hidden>
            <button type="button" role="menuitem" data-detail-view="detail-status">状态</button>
            <button type="button" role="menuitem" data-detail-view="detail-preview">预览</button>
            <button type="button" role="menuitem" data-detail-view="detail-report">报告</button>
            <button type="button" role="menuitem" data-detail-view="detail-audit">审计</button>
            <button type="button" role="menuitem" data-detail-view="detail-approvals">审批</button>
          </div>
        </div>
      </header>

      <section id="workspace-content" class="workspace-content">
        <div class="messages-frame">
          <ol id="message-list" class="message-list" aria-live="polite"></ol>
        </div>
        <div id="detail-content" class="detail-content shell-detail" aria-live="polite" hidden></div>
      </section>

      <form id="run-form" class="composer">
        <div class="composer-frame">
          <label class="sr-only" for="run-prompt">运行指令</label>
          <textarea id="run-prompt" name="prompt" rows="3" placeholder="向 SpecGate 描述你要生成或修改的 HTML..." required></textarea>
          <button type="submit">发送</button>
        </div>
      </form>
      <p id="app-message" class="message-line" role="status"></p>
    </section>
  </div>
</main>
```

- [ ] **Step 2: Replace project dialog textareas with file inputs**

Replace the current project dialog body with:

```html
<dialog id="project-dialog">
  <form id="project-form" method="dialog" class="project-form">
    <header class="dialog-header">
      <h2>新项目</h2>
      <button id="close-project-dialog" type="button" class="icon-button" title="关闭">关闭</button>
    </header>
    <label>
      项目名称
      <input id="project-name" name="name" placeholder="例如：新闻展示" required>
    </label>
    <label>
      spec.md
      <input id="project-spec-file" name="spec_file" type="file" accept=".md,text/markdown,text/plain" required>
    </label>
    <label>
      checklist.md
      <input id="project-checklist-file" name="checklist_file" type="file" accept=".md,text/markdown,text/plain" required>
    </label>
    <label>
      index.html
      <input id="project-index-file" name="index_file" type="file" accept=".html,text/html">
    </label>
    <div class="button-row align-end">
      <button type="button" id="cancel-project-button" class="secondary">取消</button>
      <button type="submit">创建项目</button>
    </div>
  </form>
</dialog>
```

- [ ] **Step 3: Add search and about dialogs**

Append these dialogs after the project dialog:

```html
<dialog id="search-dialog" class="search-dialog">
  <form method="dialog" class="search-form">
    <label class="sr-only" for="project-search-input">搜索项目</label>
    <input id="project-search-input" type="search" placeholder="搜索项目" autocomplete="off">
    <div id="search-results" class="search-results" role="listbox" aria-label="搜索结果"></div>
  </form>
</dialog>

<dialog id="about-dialog" class="about-dialog">
  <form method="dialog" class="stack">
    <header class="dialog-header">
      <h2>关于 SpecGate</h2>
      <button id="close-about-dialog" type="button" class="icon-button" title="关闭">关闭</button>
    </header>
    <p>SpecGate 当前是 Mock-first Coding Agent Harness 工作台，重点展示规范、权限、审计、审批和产物约束流程。</p>
  </form>
</dialog>
```

- [ ] **Step 4: Bump static asset query strings**

Change both references:

```html
<link rel="stylesheet" href="/styles.css?v=20260712-7">
<script src="/app.js?v=20260712-7" defer></script>
```

- [ ] **Step 5: Run focused static tests**

Run:

```powershell
python -m unittest tests.test_web_static -v
```

Expected: Some tests still FAIL because `app.js` and `styles.css` hooks are not implemented yet, but HTML region tests should pass.

- [ ] **Step 6: Commit HTML structure**

Run:

```powershell
git add src/specgate/web_static/index.html
git commit -m "feat: restructure WebUI shell markup"
```

---

### Task 3: JavaScript Shell State and Menu Commands

**Files:**
- Modify: `src/specgate/web_static/app.js`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Extend the global state**

At the top of `app.js`, update `state`:

```javascript
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
  view: "conversation",
  viewBackStack: [],
  viewForwardStack: [],
  sidebarCollapsed: false,
  sidebarPeeking: false,
  pollTimer: null,
};
```

- [ ] **Step 2: Add view history helpers**

Add these functions after `showView`:

```javascript
function resetViewHistory(view = "conversation") {
  state.view = view;
  state.viewBackStack = [];
  state.viewForwardStack = [];
}

function pushView(nextView) {
  if (!nextView || nextView === state.view) {
    renderWorkspaceView();
    return;
  }
  state.viewBackStack.push(state.view);
  state.view = nextView;
  state.viewForwardStack = [];
  renderWorkspaceView();
}

function goBack() {
  if (!state.viewBackStack.length) {
    return;
  }
  state.viewForwardStack.push(state.view);
  state.view = state.viewBackStack.pop();
  renderWorkspaceView();
}

function goForward() {
  if (!state.viewForwardStack.length) {
    return;
  }
  state.viewBackStack.push(state.view);
  state.view = state.viewForwardStack.pop();
  renderWorkspaceView();
}
```

- [ ] **Step 3: Add menu and command helpers**

Add:

```javascript
function closeAllMenus() {
  document.querySelectorAll(".menu-popover").forEach((menu) => {
    menu.hidden = true;
  });
  document.querySelectorAll("[aria-haspopup='true']").forEach((button) => {
    button.setAttribute("aria-expanded", "false");
  });
}

function toggleMenu(buttonId, menuId) {
  const button = byId(buttonId);
  const menu = byId(menuId);
  const willOpen = menu.hidden;
  closeAllMenus();
  menu.hidden = !willOpen;
  button.setAttribute("aria-expanded", willOpen ? "true" : "false");
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
    pushView("settings");
  } else if (command === "logout") {
    logout();
  } else if (command === "exit") {
    exitWindow();
  } else if (command === "search-projects") {
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
```

- [ ] **Step 4: Add sidebar helpers**

Add:

```javascript
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
  if (!state.sidebarCollapsed) {
    return;
  }
  state.sidebarPeeking = true;
  applySidebarState();
}

function hideSidebarPeek() {
  if (!state.sidebarCollapsed) {
    return;
  }
  state.sidebarPeeking = false;
  applySidebarState();
}
```

- [ ] **Step 5: Add project close, about, and auth cleanup**

Add:

```javascript
function closeCurrentProject() {
  clearPolling();
  state.selectedProject = null;
  state.messages = [];
  state.currentRun = null;
  state.runDebug = null;
  resetViewHistory("conversation");
  setText("project-title", "选择项目");
  renderProjects();
  renderWorkspaceView();
  setMessage("");
}

function openAboutDialog() {
  const dialog = byId("about-dialog");
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeAboutDialog() {
  const dialog = byId("about-dialog");
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function clearAuthForm() {
  byId("auth-form").reset();
  setAuthMessage("");
}
```

- [ ] **Step 6: Update bindEvents**

Replace `bindEvents` with:

```javascript
function bindEvents() {
  byId("auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    login();
  });
  byId("register-button").addEventListener("click", register);
  byId("sidebar-toggle-button").addEventListener("click", toggleSidebar);
  byId("back-button").addEventListener("click", goBack);
  byId("forward-button").addEventListener("click", goForward);
  byId("file-menu-button").addEventListener("click", () => toggleMenu("file-menu-button", "file-menu"));
  byId("edit-menu-button").addEventListener("click", () => toggleMenu("edit-menu-button", "edit-menu"));
  byId("help-menu-button").addEventListener("click", () => toggleMenu("help-menu-button", "help-menu"));
  byId("new-project-button").addEventListener("click", openProjectDialog);
  byId("search-project-button").addEventListener("click", openSearchDialog);
  byId("sidebar-settings-button").addEventListener("click", () => pushView("settings"));
  byId("project-menu-button").addEventListener("click", openProjectMenu);
  byId("sidebar-edge-hotzone").addEventListener("mouseenter", showSidebarPeek);
  byId("project-sidebar").addEventListener("mouseleave", hideSidebarPeek);
  byId("close-project-dialog").addEventListener("click", closeProjectDialog);
  byId("cancel-project-button").addEventListener("click", closeProjectDialog);
  byId("project-form").addEventListener("submit", createManualProject);
  byId("run-form").addEventListener("submit", startRun);
  byId("project-search-input").addEventListener("input", renderSearchResults);
  byId("close-about-dialog").addEventListener("click", closeAboutDialog);
  document.addEventListener("keydown", handleGlobalShortcut);
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".menu-root") && !event.target.closest(".project-heading")) {
      closeAllMenus();
    }
  });
  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => runCommand(button.dataset.command));
  });
  document.querySelectorAll("[data-detail-view]").forEach((button) => {
    button.addEventListener("click", () => pushView(button.dataset.detailView));
  });
}
```

- [ ] **Step 7: Add shortcut handler**

Add:

```javascript
function handleGlobalShortcut(event) {
  if (!event.ctrlKey || event.altKey) {
    return;
  }
  const key = event.key.toLowerCase();
  if (event.shiftKey && key === "n") {
    event.preventDefault();
    openNewWindow();
  } else if (key === "n") {
    event.preventDefault();
    openProjectDialog();
  } else if (key === "g") {
    event.preventDefault();
    openSearchDialog();
  } else if (key === "q") {
    event.preventDefault();
    exitWindow();
  } else if (key === ",") {
    event.preventDefault();
    pushView("settings");
  } else if (key === "b") {
    event.preventDefault();
    toggleSidebar();
  } else if (key === "w") {
    event.preventDefault();
    closeCurrentProject();
  } else if (event.key === "[") {
    event.preventDefault();
    goBack();
  } else if (event.key === "]") {
    event.preventDefault();
    goForward();
  }
}
```

- [ ] **Step 8: Update logout cleanup**

Inside `logout`, before `showView(false)`, set:

```javascript
state.user = null;
state.projects = [];
state.selectedProject = null;
state.messages = [];
state.currentRun = null;
state.runDebug = null;
state.approvals = [];
state.settings = null;
resetViewHistory("conversation");
clearAuthForm();
showView(false);
```

- [ ] **Step 9: Run focused tests**

Run:

```powershell
python -m unittest tests.test_web_static -v
```

Expected: JS hook tests pass; CSS hook tests may still fail until Task 5.

- [ ] **Step 10: Commit Shell state and commands**

Run:

```powershell
git add src/specgate/web_static/app.js
git commit -m "feat: add WebUI shell navigation commands"
```

---

### Task 4: Project Search, File Import, and Workspace View Rendering

**Files:**
- Modify: `src/specgate/web_static/app.js`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Replace project creation with file reading**

Replace `createManualProject` with:

```javascript
async function readProjectFile(inputId, required = false) {
  const input = byId(inputId);
  const file = input.files && input.files[0];
  if (!file) {
    if (required) {
      throw new Error("请选择必需的项目文件。");
    }
    return null;
  }
  return file.text();
}

async function createManualProject(event) {
  event.preventDefault();
  try {
    const specText = await readProjectFile("project-spec-file", true);
    const checklistText = await readProjectFile("project-checklist-file", true);
    const indexValue = await readProjectFile("project-index-file", false);
    const payload = await apiJson("/api/projects", {
      method: "POST",
      body: {
        name: byId("project-name").value.trim() || "新项目",
        spec_text: specText,
        checklist_text: checklistText,
        index_html: indexValue && indexValue.trim() ? indexValue : null,
      },
    });
    closeProjectDialog();
    await loadProjects();
    await selectProject(payload.project.id);
    setMessage("项目已创建。");
  } catch (error) {
    setMessage(error.message, true);
  }
}
```

- [ ] **Step 2: Add search dialog functions**

Add:

```javascript
function openSearchDialog() {
  const dialog = byId("search-dialog");
  byId("project-search-input").value = "";
  renderSearchResults();
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
  byId("project-search-input").focus();
}

function closeSearchDialog() {
  const dialog = byId("search-dialog");
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function renderSearchResults() {
  const query = byId("project-search-input").value.trim().toLowerCase();
  const results = byId("search-results");
  results.replaceChildren();
  const matches = state.projects.filter((project) => {
    const haystack = `${project.name || ""} ${project.last_run_status || ""}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  if (!matches.length) {
    results.append(el("p", { className: "muted" }, ["没有匹配项目。"]));
    return;
  }
  for (const project of matches) {
    const button = el("button", { type: "button", className: "search-result" }, [
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
```

- [ ] **Step 3: Add project detail menu and workspace view rendering**

Add:

```javascript
function openProjectMenu() {
  toggleMenu("project-menu-button", "project-menu");
}

function detailNameFromView(view) {
  return view.replace("detail-", "");
}

function renderWorkspaceView() {
  const messages = byId("message-list");
  const detail = byId("detail-content");
  const composer = byId("run-form");
  const isDetail = state.view.startsWith("detail-") || state.view === "settings";
  messages.closest(".messages-frame").hidden = isDetail;
  detail.hidden = !isDetail;
  composer.hidden = isDetail;
  byId("back-button").disabled = !state.viewBackStack.length;
  byId("forward-button").disabled = !state.viewForwardStack.length;
  if (state.view === "conversation") {
    renderConversation();
  } else if (state.view === "settings") {
    detail.replaceChildren();
    renderSettingsPlaceholder(detail);
  } else if (state.view.startsWith("detail-")) {
    state.activeTab = detailNameFromView(state.view);
    renderDetail();
  }
}

function renderSettingsPlaceholder(content) {
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["设置"]));
  card.append(el("p", { className: "muted" }, ["设置页面将在后续阶段完善。当前运行仍使用后端已保存的策略配置。"]));
  content.append(card);
}
```

- [ ] **Step 4: Update project selection and run refresh to use workspace renderer**

In `selectProject`, after setting `state.runDebug = null`, call:

```javascript
resetViewHistory("conversation");
```

Replace `renderConversation(); renderDetail();` pairs in `selectProject`, `hydrateWorkspace`, `startRun`, and `refreshRun` with:

```javascript
renderWorkspaceView();
```

Keep calls to `renderProjects()` and `setText("project-title", project.name)` intact.

- [ ] **Step 5: Update approval navigation inside run workspace**

In `renderRunWorkspaceApprovals`, replace:

```javascript
state.activeTab = "approvals";
renderDetail();
```

with:

```javascript
pushView("detail-approvals");
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m unittest tests.test_web_static -v
```

Expected: Static tests pass except CSS hook tests that depend on Task 5.

- [ ] **Step 7: Commit project import and workspace rendering**

Run:

```powershell
git add src/specgate/web_static/app.js
git commit -m "feat: add project search and file import"
```

---

### Task 5: Codex-like Shell CSS

**Files:**
- Modify: `src/specgate/web_static/styles.css`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Replace old workspace grid with menu plus app shell layout**

In `styles.css`, replace the old `.workspace-view`, `.sidebar`, `.conversation`, and `.detail-panel` layout block with:

```css
.workspace-view {
  min-height: 100vh;
  display: grid;
  grid-template-rows: 34px minmax(0, 1fr);
  background: var(--panel);
}

.app-menu-bar {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  border-bottom: 1px solid var(--line);
  padding: 0 0.55rem;
  background: #f7f7f4;
  user-select: none;
}

.window-controls,
.menu-group {
  display: flex;
  align-items: center;
  gap: 0.2rem;
}

.menu-root,
.project-heading {
  position: relative;
}

.menu-button,
.icon-button {
  min-width: 30px;
  min-height: 28px;
  border-color: transparent;
  padding: 0.25rem 0.45rem;
  color: var(--ink);
  background: transparent;
}

.menu-button:hover,
.icon-button:hover {
  background: var(--panel-soft);
}

.menu-popover {
  position: absolute;
  z-index: 20;
  top: calc(100% + 4px);
  left: 0;
  min-width: 210px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.3rem;
  background: var(--panel);
  box-shadow: var(--shadow);
}

.menu-popover button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-color: transparent;
  padding: 0.45rem 0.55rem;
  color: var(--ink);
  background: transparent;
}

.menu-popover button:hover {
  background: var(--panel-soft);
}

.menu-popover hr {
  border: 0;
  border-top: 1px solid var(--line);
  margin: 0.25rem;
}

kbd {
  color: var(--muted);
  font-size: 0.75rem;
}

.app-shell {
  position: relative;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
}
```

- [ ] **Step 2: Add sidebar styles**

Add:

```css
.project-sidebar {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 0.75rem;
  border-right: 1px solid var(--line);
  padding: 0.75rem;
  background: #f2f3ef;
  transition: transform 140ms ease;
}

.sidebar-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.sidebar-settings {
  width: 100%;
  color: var(--ink);
  border-color: transparent;
  background: transparent;
  text-align: left;
}

.sidebar-settings:hover {
  background: var(--panel-soft);
}

.sidebar-edge-hotzone {
  position: fixed;
  z-index: 12;
  top: 34px;
  left: 0;
  width: 8px;
  height: calc(100vh - 34px);
}

body.sidebar-collapsed .app-shell {
  grid-template-columns: 0 minmax(0, 1fr);
}

body.sidebar-collapsed .project-sidebar {
  transform: translateX(-100%);
  pointer-events: none;
}

body.sidebar-collapsed.sidebar-peeking .project-sidebar {
  position: fixed;
  z-index: 15;
  top: 34px;
  left: 0;
  width: 260px;
  height: calc(100vh - 34px);
  transform: translateX(0);
  pointer-events: auto;
  box-shadow: var(--shadow);
}
```

- [ ] **Step 3: Add main workspace styles**

Add:

```css
.workspace-main {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  background: var(--panel);
}

.workspace-titlebar {
  min-height: 48px;
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding: 0 1.25rem;
}

.project-heading {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.project-heading h1 {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}

.project-menu {
  left: auto;
  right: 0;
}

.workspace-content {
  min-height: 0;
  overflow: auto;
}

.messages-frame,
.shell-detail {
  width: min(820px, calc(100% - 2rem));
  margin: 0 auto;
  padding: 1rem 0;
}

.composer {
  border-top: 1px solid var(--line);
  padding: 0.9rem 1rem;
  background: #fbfbf9;
}

.composer-frame {
  width: min(820px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.75rem;
}
```

- [ ] **Step 4: Add search and responsive styles**

Add:

```css
.search-dialog,
.about-dialog,
#project-dialog {
  width: min(620px, calc(100% - 2rem));
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0;
  background: var(--panel);
  box-shadow: var(--shadow);
}

dialog::backdrop {
  background: rgba(31, 37, 34, 0.22);
}

.search-form,
.project-form {
  display: grid;
  gap: 0.85rem;
  padding: 1rem;
}

.search-results {
  display: grid;
  gap: 0.35rem;
  max-height: 360px;
  overflow: auto;
}

.search-result {
  display: grid;
  gap: 0.2rem;
  justify-items: start;
  color: var(--ink);
  border-color: transparent;
  background: transparent;
  text-align: left;
}

.search-result:hover {
  background: var(--panel-soft);
}

@media (max-width: 760px) {
  .app-shell {
    grid-template-columns: 0 minmax(0, 1fr);
  }

  .project-sidebar {
    position: fixed;
    z-index: 15;
    top: 34px;
    left: 0;
    width: min(280px, 88vw);
    height: calc(100vh - 34px);
    transform: translateX(-100%);
    box-shadow: var(--shadow);
  }

  body.sidebar-peeking .project-sidebar,
  body:not(.sidebar-collapsed) .project-sidebar {
    transform: translateX(0);
    pointer-events: auto;
  }

  .composer-frame {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Remove obsolete right-panel assumptions**

Delete or stop using layout rules that require:

```css
.detail-panel
.detail-tabs
.tab-button
.conversation
.sidebar
```

Keep reusable detail content classes such as `.detail-card`, `.detail-grid`, `.audit-metrics`, `.run-workspace`, `.source-view`, `.approval-item`.

- [ ] **Step 6: Run focused static tests**

Run:

```powershell
python -m unittest tests.test_web_static -v
```

Expected: PASS.

- [ ] **Step 7: Commit CSS**

Run:

```powershell
git add src/specgate/web_static/styles.css
git commit -m "style: add Codex-like WebUI shell"
```

---

### Task 6: Full Regression and Browser Smoke

**Files:**
- Modify only if verification reveals a defect:
  - `src/specgate/web_static/index.html`
  - `src/specgate/web_static/app.js`
  - `src/specgate/web_static/styles.css`
  - `tests/test_web_static.py`

- [ ] **Step 1: Run the focused WebUI static tests**

Run:

```powershell
python -m unittest tests.test_web_static -v
```

Expected: PASS.

- [ ] **Step 2: Run the backend WebUI tests**

Run:

```powershell
python -m unittest tests.test_web_app tests.test_web_auth tests.test_web_projects tests.test_web_runs tests.test_web_approvals tests.test_web_settings tests.test_web_debug tests.test_web_db -v
```

Expected: PASS.

- [ ] **Step 3: Run the full suite**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 4: Start the local WebUI**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.web --host 127.0.0.1 --port 8000
```

Expected: server prints that Uvicorn is running at `http://127.0.0.1:8000`.

- [ ] **Step 5: Manual browser smoke**

Open `http://127.0.0.1:8000/?v=20260712-7` and verify:

- 登录页显示正常。
- 登录或注册后显示顶部 `文件 / 编辑 / 帮助`。
- `Ctrl+B` 折叠侧栏，鼠标移动到左边缘可临时唤起侧栏。
- `文件 -> 新项目` 打开文件导入弹窗。
- 导入 `spec.md`、`checklist.md` 后项目出现在侧栏。
- `Ctrl+G` 打开搜索弹窗，点击搜索结果能切换项目。
- 发送一次 Mock run 后，对话流出现消息，项目 `...` 菜单能打开状态、预览、报告、审计、审批视图。
- `Ctrl+[` 和 `Ctrl+]` 可以在对话和详情视图间切换。
- `文件 -> 登出` 返回登录界面，登录表单为空。

- [ ] **Step 6: Fix any smoke defects with focused edits**

If a defect appears, make the smallest matching edit and rerun:

```powershell
python -m unittest tests.test_web_static -v
```

Then repeat the affected browser smoke step.

- [ ] **Step 7: Commit verification fixes if any**

If Step 6 changed files, run:

```powershell
git add src/specgate/web_static/index.html src/specgate/web_static/app.js src/specgate/web_static/styles.css tests/test_web_static.py
git commit -m "fix: polish WebUI shell smoke issues"
```

If Step 6 made no changes, do not create an empty commit.

---

### Task 7: Final Review and Branch Completion

**Files:**
- No required source edits.

- [ ] **Step 1: Inspect final diff**

Run:

```powershell
git status --short
git log --oneline -5
git diff main...HEAD --stat
```

Expected:

- Working tree clean.
- Recent commits include the design, tests, HTML, JS, CSS, and optional smoke fix commits.
- Diff is limited to `docs/superpowers`, `web_static`, and `tests/test_web_static.py`.

- [ ] **Step 2: Request code review**

Use `superpowers:requesting-code-review` before claiming completion. Ask the reviewer to focus on:

- Shell state transitions.
- Shortcut behavior.
- File import error paths.
- Whether old right-panel assumptions remain.
- Static tests matching the user-facing requirements.

- [ ] **Step 3: Address review findings**

For each confirmed defect, make a focused edit, rerun:

```powershell
python -m unittest tests.test_web_static -v
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Commit confirmed fixes:

```powershell
git add src/specgate/web_static/index.html src/specgate/web_static/app.js src/specgate/web_static/styles.css tests/test_web_static.py
git commit -m "fix: address WebUI shell review"
```

- [ ] **Step 4: Prepare PR summary**

Write the PR summary in Chinese with:

```markdown
## 概述
- 将 WebUI 主界面重构为 Codex-like 顶部菜单 + 左侧项目栏 + 居中对话工作区
- 新增项目搜索、文件导入新项目、侧栏折叠/边缘唤起、视图前进后退和全局快捷键
- 将状态、预览、报告、审计、审批入口收进项目标题 `...` 菜单

## 测试
- python -m unittest tests.test_web_static -v
- python -m unittest tests.test_web_app tests.test_web_auth tests.test_web_projects tests.test_web_runs tests.test_web_approvals tests.test_web_settings tests.test_web_debug tests.test_web_db -v
- python -m unittest discover -s tests -v
```

---

## Self-Review

- Spec coverage: 顶部菜单、快捷键、两栏 Shell、侧栏折叠、边缘唤起、新项目文件导入、搜索弹窗、详情 `...` 菜单、设置占位、登出清理和测试策略都映射到 Task 1 到 Task 7。
- Placeholder scan: 本计划未发现占位词或未定义任务。
- Type consistency: 计划中新增状态字段、函数名、DOM id 与测试断言保持一致。
