# SpecGate WebUI Product Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Codex-like WebUI product shell for SpecGate with login, project import, mock-first agent runs, artifact preview/download, settings, and Web HITL approve/deny/resume.

**Architecture:** Implement a FastAPI single-process web application that serves static frontend assets and exposes JSON APIs backed by SQLite and filesystem project workspaces. The Web layer must stay thin: it owns users, sessions, projects, run records, and artifacts, while existing SpecGate runner, approval, gate, policy, snapshot, metrics, and report modules remain the execution source of truth.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, python-multipart, SQLite, stdlib `threading`, static HTML/CSS/JavaScript, `unittest`, FastAPI `TestClient`.

---

## File Structure

Create these focused files:

- `src/specgate/web_db.py`: SQLite schema initialization and small data-access helpers.
- `src/specgate/web_auth.py`: password hashing, session creation, session lookup, auth dependency helpers.
- `src/specgate/web_projects.py`: project directory layout, safe zip extraction, manual project creation, artifact packaging.
- `src/specgate/web_runs.py`: run creation, lightweight background execution, run polling, artifact publication.
- `src/specgate/web_approvals.py`: Web API helpers around existing approval queue operations and resume.
- `src/specgate/web_settings.py`: settings persistence and API key state handling.
- `src/specgate/web_app.py`: FastAPI app factory, routes, static file mounting.
- `src/specgate/web.py`: module entry point for `python -m specgate.web`.
- `src/specgate/web_static/index.html`: Codex-like shell UI.
- `src/specgate/web_static/styles.css`: WebUI layout and visual styling.
- `src/specgate/web_static/app.js`: frontend state, API calls, polling, panel rendering.

Modify these existing files:

- `pyproject.toml`: add Web dependencies and `specgate-web` script.
- `.gitignore`: ignore `var/specgate_web/`.
- `README.md`: document local WebUI startup and server deployment shape.

Create these tests:

- `tests/test_web_db.py`
- `tests/test_web_auth.py`
- `tests/test_web_projects.py`
- `tests/test_web_runs.py`
- `tests/test_web_approvals.py`
- `tests/test_web_app.py`
- `tests/test_web_static.py`

Implementation must keep all existing tests passing.

---

### Task 1: Web Dependencies and Runtime Layout

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `tests/test_web_db.py`
- Create: `src/specgate/web_db.py`

- [ ] **Step 1: Write the failing database initialization test**

Add `tests/test_web_db.py`:

```python
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from specgate.web_db import connect_db, init_db


class WebDbTests(unittest.TestCase):
    def test_init_db_creates_required_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "specgate_web.sqlite3"

            init_db(db_path)

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()
            table_names = {row[0] for row in rows}
            self.assertIn("users", table_names)
            self.assertIn("sessions", table_names)
            self.assertIn("projects", table_names)
            self.assertIn("runs", table_names)
            self.assertIn("approvals", table_names)

    def test_connect_db_returns_rows_as_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "specgate_web.sqlite3"
            init_db(db_path)

            with connect_db(db_path) as conn:
                conn.execute(
                    "insert into users (username, password_hash, created_at) values (?, ?, ?)",
                    ("alice", "hash", "2026-07-11T00:00:00Z"),
                )
                row = conn.execute("select username from users").fetchone()

            self.assertEqual(row["username"], "alice")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_db -v
```

Expected: import failure for `specgate.web_db`.

- [ ] **Step 3: Add Web dependencies and ignored runtime directory**

Modify `pyproject.toml`:

```toml
[project]
name = "specgate"
version = "0.1.0"
description = "A small coding agent harness for static HTML generation and gate feedback."
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115,<1",
    "httpx>=0.27,<1",
    "python-multipart>=0.0.9,<1",
    "uvicorn>=0.30,<1",
]

[project.scripts]
specgate = "specgate.cli:main"
specgate-web = "specgate.web:main"
```

Add to `.gitignore`:

```gitignore
var/specgate_web/
```

- [ ] **Step 4: Implement minimal SQLite initialization**

Create `src/specgate/web_db.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
create table if not exists users (
    id integer primary key autoincrement,
    username text not null unique,
    password_hash text not null,
    created_at text not null
);

create table if not exists sessions (
    token text primary key,
    user_id integer not null references users(id) on delete cascade,
    created_at text not null,
    expires_at text not null
);

create table if not exists user_settings (
    user_id integer primary key references users(id) on delete cascade,
    governance_profile text not null default 'review',
    context_strategy text not null default 'injection-safe',
    api_key_configured integer not null default 0,
    api_key_ciphertext text
);

create table if not exists projects (
    id integer primary key autoincrement,
    user_id integer not null references users(id) on delete cascade,
    name text not null,
    create_mode text not null,
    root_path text not null,
    created_at text not null,
    updated_at text not null,
    last_run_status text
);

create table if not exists messages (
    id integer primary key autoincrement,
    project_id integer not null references projects(id) on delete cascade,
    role text not null,
    content text not null,
    created_at text not null
);

create table if not exists runs (
    id integer primary key autoincrement,
    project_id integer not null references projects(id) on delete cascade,
    user_id integer not null references users(id) on delete cascade,
    status text not null,
    prompt text not null,
    trust_level text,
    report_path text,
    index_artifact_path text,
    zip_artifact_path text,
    error_message text,
    created_at text not null,
    started_at text,
    finished_at text
);

create table if not exists approvals (
    id integer primary key autoincrement,
    run_id integer not null references runs(id) on delete cascade,
    project_id integer not null references projects(id) on delete cascade,
    approval_id text not null,
    status text not null,
    action_name text not null,
    target_path text,
    reason text not null,
    preview_json text not null,
    created_at text not null,
    decided_at text
);

create table if not exists artifacts (
    id integer primary key autoincrement,
    run_id integer not null references runs(id) on delete cascade,
    kind text not null,
    path text not null,
    created_at text not null
);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_db(db_path) as conn:
        conn.executescript(SCHEMA)


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn
```

- [ ] **Step 5: Run the focused test and verify it passes**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_db -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml .gitignore src/specgate/web_db.py tests/test_web_db.py
git commit -m "feat: add web runtime database schema"
```

---

### Task 2: Authentication and Settings Core

**Files:**
- Create: `tests/test_web_auth.py`
- Create: `tests/test_web_settings.py`
- Create: `src/specgate/web_auth.py`
- Create: `src/specgate/web_settings.py`

- [ ] **Step 1: Write failing auth and settings tests**

Create `tests/test_web_auth.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from specgate.web_auth import (
    authenticate_user,
    create_session,
    create_user,
    get_user_by_session,
)
from specgate.web_db import init_db


class WebAuthTests(unittest.TestCase):
    def test_create_user_hashes_password_and_authenticates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)

            user = create_user(db_path, "alice", "correct horse battery staple")

            self.assertEqual(user["username"], "alice")
            self.assertNotIn("correct horse", user["password_hash"])
            authenticated = authenticate_user(db_path, "alice", "correct horse battery staple")
            self.assertEqual(authenticated["id"], user["id"])

    def test_session_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")

            token = create_session(db_path, user["id"])
            session_user = get_user_by_session(db_path, token)

            self.assertEqual(session_user["username"], "alice")


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_web_settings.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from specgate.web_auth import create_user
from specgate.web_db import init_db
from specgate.web_settings import clear_api_key, get_settings, update_settings, upsert_api_key


class WebSettingsTests(unittest.TestCase):
    def test_default_settings_are_mock_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")

            settings = get_settings(db_path, user["id"])

            self.assertEqual(settings["governance_profile"], "review")
            self.assertEqual(settings["context_strategy"], "injection-safe")
            self.assertFalse(settings["api_key_configured"])

    def test_api_key_state_can_be_saved_and_cleared_without_returning_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")

            saved = upsert_api_key(db_path, user["id"], "sk-test-secret", encryption_secret=None)
            cleared = clear_api_key(db_path, user["id"])

            self.assertTrue(saved["api_key_configured"])
            self.assertNotIn("sk-test-secret", str(saved))
            self.assertFalse(cleared["api_key_configured"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_auth tests.test_web_settings -v
```

Expected: import failures for `specgate.web_auth` and `specgate.web_settings`.

- [ ] **Step 3: Implement authentication helpers**

Create `src/specgate/web_auth.py`:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlite3 import IntegrityError, Row

from specgate.web_db import connect_db


SESSION_DAYS = 7


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, *, salt: str | None = None) -> str:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_value),
        120_000,
    )
    return f"pbkdf2_sha256${salt_value}${base64.b64encode(digest).decode('ascii')}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hash_password(password, salt=salt)
    return hmac.compare_digest(actual, password_hash)


def create_user(db_path: Path, username: str, password: str) -> Row:
    username = username.strip()
    if not username:
        raise ValueError("username is required")
    password_hash = hash_password(password)
    try:
        with connect_db(db_path) as conn:
            cur = conn.execute(
                "insert into users (username, password_hash, created_at) values (?, ?, ?)",
                (username, password_hash, utc_now()),
            )
            conn.execute(
                "insert into user_settings (user_id) values (?)",
                (cur.lastrowid,),
            )
            return conn.execute("select * from users where id = ?", (cur.lastrowid,)).fetchone()
    except IntegrityError as exc:
        raise ValueError("username already exists") from exc


def authenticate_user(db_path: Path, username: str, password: str) -> Row:
    with connect_db(db_path) as conn:
        user = conn.execute("select * from users where username = ?", (username.strip(),)).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        raise ValueError("invalid username or password")
    return user


def create_session(db_path: Path, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=SESSION_DAYS)
    with connect_db(db_path) as conn:
        conn.execute(
            "insert into sessions (token, user_id, created_at, expires_at) values (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires_at.isoformat()),
        )
    return token


def get_user_by_session(db_path: Path, token: str | None) -> Row:
    if not token:
        raise ValueError("missing session")
    with connect_db(db_path) as conn:
        row = conn.execute(
            """
            select users.*
            from sessions
            join users on users.id = sessions.user_id
            where sessions.token = ? and sessions.expires_at > ?
            """,
            (token, utc_now()),
        ).fetchone()
    if row is None:
        raise ValueError("invalid session")
    return row


def delete_session(db_path: Path, token: str) -> None:
    with connect_db(db_path) as conn:
        conn.execute("delete from sessions where token = ?", (token,))
```

- [ ] **Step 4: Implement settings helpers**

Create `src/specgate/web_settings.py`:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path
from sqlite3 import Row

from specgate.context import VALID_CONTEXT_STRATEGIES
from specgate.web_db import connect_db


GOVERNANCE_PROFILES = {"strict", "review", "demo"}


def get_settings(db_path: Path, user_id: int) -> dict[str, object]:
    with connect_db(db_path) as conn:
        row = conn.execute("select * from user_settings where user_id = ?", (user_id,)).fetchone()
        if row is None:
            conn.execute("insert into user_settings (user_id) values (?)", (user_id,))
            row = conn.execute("select * from user_settings where user_id = ?", (user_id,)).fetchone()
    return _settings_dict(row)


def update_settings(
    db_path: Path,
    user_id: int,
    *,
    governance_profile: str,
    context_strategy: str,
) -> dict[str, object]:
    if governance_profile not in GOVERNANCE_PROFILES:
        raise ValueError("invalid governance profile")
    if context_strategy not in VALID_CONTEXT_STRATEGIES:
        raise ValueError("invalid context strategy")
    with connect_db(db_path) as conn:
        conn.execute(
            """
            update user_settings
            set governance_profile = ?, context_strategy = ?
            where user_id = ?
            """,
            (governance_profile, context_strategy, user_id),
        )
    return get_settings(db_path, user_id)


def upsert_api_key(
    db_path: Path,
    user_id: int,
    api_key: str,
    *,
    encryption_secret: str | None,
) -> dict[str, object]:
    if not api_key.strip():
        raise ValueError("api key is required")
    ciphertext = _protect_api_key(api_key, encryption_secret)
    with connect_db(db_path) as conn:
        conn.execute(
            """
            update user_settings
            set api_key_configured = 1, api_key_ciphertext = ?
            where user_id = ?
            """,
            (ciphertext, user_id),
        )
    return get_settings(db_path, user_id)


def clear_api_key(db_path: Path, user_id: int) -> dict[str, object]:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            update user_settings
            set api_key_configured = 0, api_key_ciphertext = null
            where user_id = ?
            """,
            (user_id,),
        )
    return get_settings(db_path, user_id)


def _settings_dict(row: Row) -> dict[str, object]:
    return {
        "governance_profile": row["governance_profile"],
        "context_strategy": row["context_strategy"],
        "api_key_configured": bool(row["api_key_configured"]),
        "api_key_storage": "encrypted" if row["api_key_ciphertext"] else "not_stored",
        "llm_mode": "mock",
    }


def _protect_api_key(api_key: str, encryption_secret: str | None) -> str | None:
    if encryption_secret is None:
        return None
    digest = hmac.new(
        encryption_secret.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")
```

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_auth tests.test_web_settings -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/specgate/web_auth.py src/specgate/web_settings.py tests/test_web_auth.py tests/test_web_settings.py
git commit -m "feat: add web auth and settings core"
```

---

### Task 3: Project Import, Manual Creation, and Artifact Packaging

**Files:**
- Create: `tests/test_web_projects.py`
- Create: `src/specgate/web_projects.py`

- [ ] **Step 1: Write failing project tests**

Create `tests/test_web_projects.py`:

```python
from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from specgate.web_auth import create_user
from specgate.web_db import init_db
from specgate.web_projects import (
    create_manual_project,
    create_project_from_zip,
    package_result_zip,
    project_paths,
)


class WebProjectTests(unittest.TestCase):
    def test_manual_project_creates_original_workspace_and_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "web.sqlite3"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")

            project = create_manual_project(
                db_path,
                base / "data",
                user["id"],
                name="Demo",
                spec_text="Build a page",
                checklist_text="- title",
                index_html="<h1>Old</h1>",
            )

            paths = project_paths(base / "data", user["id"], project["id"])
            self.assertEqual((paths.original / "SPEC.md").read_text(encoding="utf-8"), "Build a page")
            self.assertEqual((paths.workspace / "CHECKLIST.md").read_text(encoding="utf-8"), "- title")
            self.assertEqual((paths.workspace / "index.html").read_text(encoding="utf-8"), "<h1>Old</h1>")

    def test_zip_project_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "web.sqlite3"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")
            zip_bytes = io.BytesIO()
            with zipfile.ZipFile(zip_bytes, "w") as zf:
                zf.writestr("../evil.txt", "bad")

            with self.assertRaises(ValueError):
                create_project_from_zip(db_path, base / "data", user["id"], "Unsafe", zip_bytes.getvalue())

    def test_zip_project_requires_spec_and_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "web.sqlite3"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")
            zip_bytes = io.BytesIO()
            with zipfile.ZipFile(zip_bytes, "w") as zf:
                zf.writestr("SPEC.md", "Build")

            with self.assertRaises(ValueError):
                create_project_from_zip(db_path, base / "data", user["id"], "Missing", zip_bytes.getvalue())

    def test_package_result_zip_contains_latest_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            artifact_dir = base / "artifacts"
            artifact_dir.mkdir()
            index_path = artifact_dir / "latest-index.html"
            index_path.write_text("<h1>Result</h1>", encoding="utf-8")

            result_zip = package_result_zip(artifact_dir)

            with zipfile.ZipFile(result_zip) as zf:
                self.assertEqual(zf.read("index.html").decode("utf-8"), "<h1>Result</h1>")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_projects -v
```

Expected: import failure for `specgate.web_projects`.

- [ ] **Step 3: Implement project helpers**

Create `src/specgate/web_projects.py`:

```python
from __future__ import annotations

import io
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from sqlite3 import Row

from specgate.web_auth import utc_now
from specgate.web_db import connect_db


SPEC_NAMES = {"SPEC", "SPEC.md", "TASK_SPEC.md", "TASK_SPEC"}
CHECKLIST_NAMES = {"CHECKLIST", "CHECKLIST.md"}


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    original: Path
    workspace: Path
    artifacts: Path
    runs: Path


def project_paths(data_root: Path, user_id: int, project_id: int) -> ProjectPaths:
    root = data_root / "users" / str(user_id) / "projects" / str(project_id)
    return ProjectPaths(
        root=root,
        original=root / "original",
        workspace=root / "workspace",
        artifacts=root / "artifacts",
        runs=root / "runs",
    )


def create_manual_project(
    db_path: Path,
    data_root: Path,
    user_id: int,
    *,
    name: str,
    spec_text: str,
    checklist_text: str,
    index_html: str | None,
) -> Row:
    if not spec_text.strip():
        raise ValueError("SPEC is required")
    if not checklist_text.strip():
        raise ValueError("CHECKLIST is required")
    project = _insert_project(db_path, user_id, name, "manual")
    paths = project_paths(data_root, user_id, project["id"])
    _create_project_dirs(paths)
    _write_both(paths, "SPEC.md", spec_text)
    _write_both(paths, "CHECKLIST.md", checklist_text)
    if index_html is not None:
        _write_both(paths, "index.html", index_html)
    return _set_project_root(db_path, project["id"], paths.root)


def create_project_from_zip(
    db_path: Path,
    data_root: Path,
    user_id: int,
    name: str,
    zip_content: bytes,
) -> Row:
    project = _insert_project(db_path, user_id, name, "zip")
    paths = project_paths(data_root, user_id, project["id"])
    _create_project_dirs(paths)
    with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            relative = _safe_zip_member(member.filename)
            destination = paths.original / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(zf.read(member))
    _require_spec_and_checklist(paths.original)
    shutil.copytree(paths.original, paths.workspace, dirs_exist_ok=True)
    return _set_project_root(db_path, project["id"], paths.root)


def package_result_zip(artifact_dir: Path) -> Path:
    index_path = artifact_dir / "latest-index.html"
    if not index_path.exists():
        raise ValueError("latest index artifact is missing")
    result_zip = artifact_dir / "result.zip"
    with zipfile.ZipFile(result_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(index_path, "index.html")
    return result_zip


def _insert_project(db_path: Path, user_id: int, name: str, create_mode: str) -> Row:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("project name is required")
    now = utc_now()
    with connect_db(db_path) as conn:
        cur = conn.execute(
            """
            insert into projects (user_id, name, create_mode, root_path, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (user_id, clean_name, create_mode, "", now, now),
        )
        return conn.execute("select * from projects where id = ?", (cur.lastrowid,)).fetchone()


def _set_project_root(db_path: Path, project_id: int, root: Path) -> Row:
    with connect_db(db_path) as conn:
        conn.execute("update projects set root_path = ? where id = ?", (str(root), project_id))
        return conn.execute("select * from projects where id = ?", (project_id,)).fetchone()


def _create_project_dirs(paths: ProjectPaths) -> None:
    paths.original.mkdir(parents=True, exist_ok=True)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.artifacts.mkdir(parents=True, exist_ok=True)
    paths.runs.mkdir(parents=True, exist_ok=True)


def _write_both(paths: ProjectPaths, relative: str, content: str) -> None:
    for base in (paths.original, paths.workspace):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _safe_zip_member(filename: str) -> Path:
    posix = PurePosixPath(filename.replace("\\", "/"))
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("zip contains unsafe path")
    return Path(*posix.parts)


def _require_spec_and_checklist(root: Path) -> None:
    names = {path.name for path in root.rglob("*") if path.is_file()}
    if not names.intersection(SPEC_NAMES):
        raise ValueError("zip must contain SPEC or TASK_SPEC")
    if not names.intersection(CHECKLIST_NAMES):
        raise ValueError("zip must contain CHECKLIST")
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_projects -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/specgate/web_projects.py tests/test_web_projects.py
git commit -m "feat: add web project import helpers"
```

---

### Task 4: Run Records, Mock Execution, and Artifact Publication

**Files:**
- Create: `tests/test_web_runs.py`
- Create: `src/specgate/web_runs.py`

- [ ] **Step 1: Write failing run tests**

Create `tests/test_web_runs.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from specgate.web_auth import create_user
from specgate.web_db import init_db
from specgate.web_projects import create_manual_project, project_paths
from specgate.web_runs import create_run, execute_run_once, get_run


class WebRunTests(unittest.TestCase):
    def test_create_run_records_queued_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "web.sqlite3"
            data_root = base / "data"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")
            project = create_manual_project(
                db_path,
                data_root,
                user["id"],
                name="Demo",
                spec_text="Create a page",
                checklist_text="- Result",
                index_html=None,
            )

            run = create_run(db_path, project["id"], user["id"], "Generate HTML")

            self.assertEqual(run["status"], "queued")
            self.assertEqual(run["prompt"], "Generate HTML")

    def test_execute_run_publishes_latest_index_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "web.sqlite3"
            data_root = base / "data"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")
            project = create_manual_project(
                db_path,
                data_root,
                user["id"],
                name="Demo",
                spec_text="Create a page with Result title",
                checklist_text="- Result",
                index_html=None,
            )
            run = create_run(db_path, project["id"], user["id"], "Generate HTML")

            execute_run_once(db_path, data_root, run["id"])
            completed = get_run(db_path, user["id"], run["id"])
            paths = project_paths(data_root, user["id"], project["id"])

            self.assertIn(completed["status"], {"completed", "needs_approval", "failed"})
            self.assertTrue((paths.artifacts / "latest-index.html").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs -v
```

Expected: import failure for `specgate.web_runs`.

- [ ] **Step 3: Implement run helpers**

Create `src/specgate/web_runs.py`:

```python
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from sqlite3 import Row

from specgate.approvals import ApprovalQueue, GovernanceConfig, approval_queue_path
from specgate.config import WorkspaceConfig
from specgate.llm import MockLLM
from specgate.runner import AgentRunner
from specgate.web_auth import utc_now
from specgate.web_db import connect_db
from specgate.web_projects import package_result_zip, project_paths


def create_run(db_path: Path, project_id: int, user_id: int, prompt: str) -> Row:
    if not prompt.strip():
        raise ValueError("prompt is required")
    now = utc_now()
    with connect_db(db_path) as conn:
        cur = conn.execute(
            """
            insert into runs (project_id, user_id, status, prompt, created_at)
            values (?, ?, 'queued', ?, ?)
            """,
            (project_id, user_id, prompt.strip(), now),
        )
        conn.execute(
            "insert into messages (project_id, role, content, created_at) values (?, 'user', ?, ?)",
            (project_id, prompt.strip(), now),
        )
        return conn.execute("select * from runs where id = ?", (cur.lastrowid,)).fetchone()


def get_run(db_path: Path, user_id: int, run_id: int) -> Row:
    with connect_db(db_path) as conn:
        row = conn.execute(
            "select * from runs where id = ? and user_id = ?",
            (run_id, user_id),
        ).fetchone()
    if row is None:
        raise ValueError("run not found")
    return row


def start_run_background(db_path: Path, data_root: Path, run_id: int) -> None:
    thread = threading.Thread(
        target=execute_run_once,
        args=(db_path, data_root, run_id),
        daemon=True,
    )
    thread.start()


def execute_run_once(db_path: Path, data_root: Path, run_id: int) -> None:
    run = _load_run(db_path, run_id)
    project = _load_project(db_path, run["project_id"], run["user_id"])
    paths = project_paths(data_root, run["user_id"], project["id"])
    _mark_running(db_path, run_id)
    responses = _mock_responses_for_prompt(run["prompt"])
    try:
        runner = AgentRunner(
            paths.workspace,
            MockLLM(responses),
            max_steps=5,
            governance=GovernanceConfig(profile="review"),
            context_strategy="injection-safe",
            workspace_config=WorkspaceConfig(),
        )
        result = runner.run()
        _publish_artifacts(db_path, run_id, paths)
        queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
        if queue.next_resume_candidate() is not None:
            _mark_needs_approval(db_path, run_id, result)
            _sync_approvals(db_path, run_id, project["id"], queue)
        elif result.gate.passed:
            _mark_completed(db_path, run_id, result)
        else:
            _mark_failed(db_path, run_id, "Gate did not pass")
    except Exception as exc:
        _mark_failed(db_path, run_id, str(exc))


def _mock_responses_for_prompt(prompt: str) -> list[dict]:
    html = (
        "<!doctype html><html><head><title>SpecGate Result</title></head>"
        "<body><main><h1>SpecGate Result</h1><p>Generated from WebUI task.</p></main></body></html>"
    )
    return [
        {
            "schema_version": "1",
            "action": "write_file",
            "args": {"path": "index.html", "content": html},
        },
        {
            "schema_version": "1",
            "action": "finish",
            "args": {"summary": f"Completed WebUI task: {prompt}"},
        },
    ]


def _publish_artifacts(db_path: Path, run_id: int, paths) -> None:
    index_source = paths.workspace / "index.html"
    if index_source.exists():
        paths.artifacts.mkdir(parents=True, exist_ok=True)
        index_artifact = paths.artifacts / "latest-index.html"
        shutil.copyfile(index_source, index_artifact)
        zip_artifact = package_result_zip(paths.artifacts)
        with connect_db(db_path) as conn:
            conn.execute(
                """
                update runs
                set index_artifact_path = ?, zip_artifact_path = ?
                where id = ?
                """,
                (str(index_artifact), str(zip_artifact), run_id),
            )


def _sync_approvals(db_path: Path, run_id: int, project_id: int, queue: ApprovalQueue) -> None:
    now = utc_now()
    with connect_db(db_path) as conn:
        conn.execute("delete from approvals where run_id = ?", (run_id,))
        for approval in queue.approvals:
            conn.execute(
                """
                insert into approvals
                    (run_id, project_id, approval_id, status, action_name, target_path, reason, preview_json, created_at, decided_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    approval.id,
                    approval.status,
                    approval.action_name,
                    approval.target_path,
                    approval.reason,
                    json.dumps(approval.preview_args, ensure_ascii=False),
                    now,
                    approval.decided_at,
                ),
            )


def _load_run(db_path: Path, run_id: int) -> Row:
    with connect_db(db_path) as conn:
        row = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("run not found")
    return row


def _load_project(db_path: Path, project_id: int, user_id: int) -> Row:
    with connect_db(db_path) as conn:
        row = conn.execute(
            "select * from projects where id = ? and user_id = ?",
            (project_id, user_id),
        ).fetchone()
    if row is None:
        raise ValueError("project not found")
    return row


def _mark_running(db_path: Path, run_id: int) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            "update runs set status = 'running', started_at = ? where id = ?",
            (utc_now(), run_id),
        )


def _mark_completed(db_path: Path, run_id: int, result) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            update runs
            set status = 'completed', trust_level = ?, finished_at = ?
            where id = ?
            """,
            (result.trust_summary.level if result.trust_summary else "trusted", utc_now(), run_id),
        )


def _mark_needs_approval(db_path: Path, run_id: int, result) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            update runs
            set status = 'needs_approval', trust_level = ?, finished_at = ?
            where id = ?
            """,
            (result.trust_summary.level if result.trust_summary else "warning", utc_now(), run_id),
        )


def _mark_failed(db_path: Path, run_id: int, message: str) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            update runs
            set status = 'failed', error_message = ?, finished_at = ?
            where id = ?
            """,
            (message, utc_now(), run_id),
        )
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/specgate/web_runs.py tests/test_web_runs.py
git commit -m "feat: add web run execution pipeline"
```

---

### Task 5: Web Approval and Resume Helpers

**Files:**
- Create: `tests/test_web_approvals.py`
- Create: `src/specgate/web_approvals.py`
- Modify: `src/specgate/web_runs.py`

- [ ] **Step 1: Write failing approval tests**

Create `tests/test_web_approvals.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from specgate.approvals import ApprovalQueue, PendingApproval, approval_queue_path
from specgate.web_approvals import approve_web_approval, deny_web_approval, list_web_approvals
from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_projects import create_manual_project, project_paths
from specgate.web_runs import create_run


class WebApprovalTests(unittest.TestCase):
    def test_list_approve_and_deny_respect_user_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "web.sqlite3"
            data_root = base / "data"
            init_db(db_path)
            user = create_user(db_path, "alice", "secret-password")
            project = create_manual_project(
                db_path,
                data_root,
                user["id"],
                name="Demo",
                spec_text="Create",
                checklist_text="- safe",
                index_html="<h1>Old</h1>",
            )
            run = create_run(db_path, project["id"], user["id"], "Modify")
            paths = project_paths(data_root, user["id"], project["id"])
            queue = ApprovalQueue([
                PendingApproval(
                    id="approval-1",
                    action_name="write_file",
                    target_path="index.html",
                    reason="review path",
                    preview_args={"path": "index.html"},
                    status="pending",
                    created_at="2026-07-11T00:00:00Z",
                )
            ])
            queue.write(approval_queue_path(paths.workspace))
            with connect_db(db_path) as conn:
                conn.execute(
                    """
                    insert into approvals
                        (run_id, project_id, approval_id, status, action_name, target_path, reason, preview_json, created_at)
                    values (?, ?, 'approval-1', 'pending', 'write_file', 'index.html', 'review path', '{}', '2026-07-11T00:00:00Z')
                    """,
                    (run["id"], project["id"]),
                )

            listed = list_web_approvals(db_path, user["id"])
            approved = approve_web_approval(db_path, data_root, user["id"], listed[0]["id"])

            self.assertEqual(len(listed), 1)
            self.assertEqual(approved["status"], "approved")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run focused test and verify it fails**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_approvals -v
```

Expected: import failure for `specgate.web_approvals`.

- [ ] **Step 3: Implement approval helpers**

Create `src/specgate/web_approvals.py`:

```python
from __future__ import annotations

from pathlib import Path
from sqlite3 import Row

from specgate.approvals import ApprovalQueue, approval_queue_path
from specgate.web_auth import utc_now
from specgate.web_db import connect_db
from specgate.web_projects import project_paths


def list_web_approvals(db_path: Path, user_id: int) -> list[Row]:
    with connect_db(db_path) as conn:
        return conn.execute(
            """
            select approvals.*
            from approvals
            join runs on runs.id = approvals.run_id
            where runs.user_id = ?
            order by approvals.id desc
            """,
            (user_id,),
        ).fetchall()


def approve_web_approval(db_path: Path, data_root: Path, user_id: int, web_approval_id: int) -> Row:
    row = _load_web_approval(db_path, user_id, web_approval_id)
    paths = project_paths(data_root, user_id, row["project_id"])
    queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
    decided_at = utc_now()
    queue.approve(row["approval_id"], decided_at).write(approval_queue_path(paths.workspace))
    return _update_web_approval_status(db_path, web_approval_id, "approved", decided_at)


def deny_web_approval(
    db_path: Path,
    data_root: Path,
    user_id: int,
    web_approval_id: int,
    reason: str,
) -> Row:
    row = _load_web_approval(db_path, user_id, web_approval_id)
    paths = project_paths(data_root, user_id, row["project_id"])
    queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
    decided_at = utc_now()
    queue.deny(row["approval_id"], reason or "Denied in WebUI", decided_at).write(
        approval_queue_path(paths.workspace)
    )
    return _update_web_approval_status(db_path, web_approval_id, "denied", decided_at)


def _load_web_approval(db_path: Path, user_id: int, web_approval_id: int) -> Row:
    with connect_db(db_path) as conn:
        row = conn.execute(
            """
            select approvals.*
            from approvals
            join runs on runs.id = approvals.run_id
            where approvals.id = ? and runs.user_id = ?
            """,
            (web_approval_id, user_id),
        ).fetchone()
    if row is None:
        raise ValueError("approval not found")
    return row


def _update_web_approval_status(db_path: Path, web_approval_id: int, status: str, decided_at: str) -> Row:
    with connect_db(db_path) as conn:
        conn.execute(
            "update approvals set status = ?, decided_at = ? where id = ?",
            (status, decided_at, web_approval_id),
        )
        return conn.execute("select * from approvals where id = ?", (web_approval_id,)).fetchone()
```

- [ ] **Step 4: Add resume helper to `web_runs.py`**

Append to `src/specgate/web_runs.py`:

```python
def resume_run_once(db_path: Path, data_root: Path, user_id: int, run_id: int) -> None:
    run = get_run(db_path, user_id, run_id)
    project = _load_project(db_path, run["project_id"], user_id)
    paths = project_paths(data_root, user_id, project["id"])
    _mark_running(db_path, run_id)
    try:
        runner = AgentRunner(
            paths.workspace,
            MockLLM([
                {
                    "schema_version": "1",
                    "action": "finish",
                    "args": {"summary": "Resumed after Web approval"},
                }
            ]),
            max_steps=5,
            governance=GovernanceConfig(profile="review"),
            context_strategy="injection-safe",
            workspace_config=WorkspaceConfig(),
        )
        result = runner.resume_from_approval()
        _publish_artifacts(db_path, run_id, paths)
        if result.gate.passed:
            _mark_completed(db_path, run_id, result)
        else:
            _mark_failed(db_path, run_id, "Gate did not pass after resume")
    except Exception as exc:
        _mark_failed(db_path, run_id, str(exc))
```

- [ ] **Step 5: Run focused test and verify it passes**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_approvals -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/specgate/web_approvals.py src/specgate/web_runs.py tests/test_web_approvals.py
git commit -m "feat: add web approval controls"
```

---

### Task 6: FastAPI App and JSON Routes

**Files:**
- Create: `tests/test_web_app.py`
- Create: `src/specgate/web_app.py`
- Create: `src/specgate/web.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_web_app.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from specgate.web_app import create_app


class WebAppTests(unittest.TestCase):
    def test_register_login_create_project_and_start_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(data_root=Path(tmp) / "data", db_path=Path(tmp) / "web.sqlite3")
            client = TestClient(app)

            register = client.post(
                "/api/auth/register",
                json={"username": "alice", "password": "secret-password"},
            )
            login = client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "secret-password"},
            )
            project = client.post(
                "/api/projects",
                json={
                    "name": "Demo",
                    "spec": "Create a page",
                    "checklist": "- SpecGate Result",
                    "index_html": "",
                },
            )
            run = client.post(
                f"/api/projects/{project.json()['id']}/runs",
                json={"prompt": "Generate HTML"},
            )

            self.assertEqual(register.status_code, 200)
            self.assertEqual(login.status_code, 200)
            self.assertEqual(project.status_code, 200)
            self.assertEqual(run.status_code, 200)
            self.assertEqual(run.json()["status"], "queued")

    def test_api_requires_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(data_root=Path(tmp) / "data", db_path=Path(tmp) / "web.sqlite3")
            client = TestClient(app)

            response = client.get("/api/projects")

            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run focused API tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_app -v
```

Expected: import failure for `specgate.web_app`.

- [ ] **Step 3: Implement FastAPI app factory and routes**

Create `src/specgate/web_app.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from specgate.web_approvals import approve_web_approval, deny_web_approval, list_web_approvals
from specgate.web_auth import authenticate_user, create_session, create_user, delete_session, get_user_by_session
from specgate.web_db import connect_db, init_db
from specgate.web_projects import create_manual_project, create_project_from_zip
from specgate.web_runs import create_run, get_run, resume_run_once, start_run_background
from specgate.web_settings import clear_api_key, get_settings, update_settings, upsert_api_key


SESSION_COOKIE = "specgate_session"


class Credentials(BaseModel):
    username: str
    password: str


class ManualProjectRequest(BaseModel):
    name: str
    spec: str
    checklist: str
    index_html: str | None = None


class RunRequest(BaseModel):
    prompt: str


class SettingsRequest(BaseModel):
    governance_profile: str
    context_strategy: str


class ApiKeyRequest(BaseModel):
    api_key: str


def create_app(
    *,
    data_root: Path | None = None,
    db_path: Path | None = None,
) -> FastAPI:
    resolved_data_root = data_root or Path(os.environ.get("SPECGATE_WEB_DATA", "var/specgate_web"))
    resolved_db_path = db_path or resolved_data_root / "specgate_web.sqlite3"
    init_db(resolved_db_path)
    app = FastAPI(title="SpecGate WebUI")
    app.state.data_root = resolved_data_root
    app.state.db_path = resolved_db_path

    def current_user(token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None):
        try:
            return get_user_by_session(resolved_db_path, token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="authentication required") from exc

    @app.post("/api/auth/register")
    def register(credentials: Credentials, response: Response):
        try:
            user = create_user(resolved_db_path, credentials.username, credentials.password)
            token = create_session(resolved_db_path, user["id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return {"id": user["id"], "username": user["username"]}

    @app.post("/api/auth/login")
    def login(credentials: Credentials, response: Response):
        try:
            user = authenticate_user(resolved_db_path, credentials.username, credentials.password)
            token = create_session(resolved_db_path, user["id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return {"id": user["id"], "username": user["username"]}

    @app.post("/api/auth/logout")
    def logout(response: Response, token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None):
        if token:
            delete_session(resolved_db_path, token)
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user=Depends(current_user)):
        return {"id": user["id"], "username": user["username"]}

    @app.get("/api/projects")
    def projects(user=Depends(current_user)):
        with connect_db(resolved_db_path) as conn:
            rows = conn.execute(
                "select * from projects where user_id = ? order by updated_at desc",
                (user["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/projects")
    def create_project(request: ManualProjectRequest, user=Depends(current_user)):
        try:
            row = create_manual_project(
                resolved_db_path,
                resolved_data_root,
                user["id"],
                name=request.name,
                spec_text=request.spec,
                checklist_text=request.checklist,
                index_html=request.index_html or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return dict(row)

    @app.post("/api/projects/upload")
    async def upload_project(name: str, file: UploadFile, user=Depends(current_user)):
        content = await file.read()
        try:
            row = create_project_from_zip(resolved_db_path, resolved_data_root, user["id"], name, content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return dict(row)

    @app.post("/api/projects/{project_id}/runs")
    def start_run(project_id: int, request: RunRequest, user=Depends(current_user)):
        _assert_project_owner(resolved_db_path, project_id, user["id"])
        row = create_run(resolved_db_path, project_id, user["id"], request.prompt)
        start_run_background(resolved_db_path, resolved_data_root, row["id"])
        return dict(row)

    @app.get("/api/runs/{run_id}")
    def read_run(run_id: int, user=Depends(current_user)):
        return dict(get_run(resolved_db_path, user["id"], run_id))

    @app.get("/api/runs/{run_id}/artifact/index.html")
    def read_index_artifact(run_id: int, user=Depends(current_user)):
        run = get_run(resolved_db_path, user["id"], run_id)
        if not run["index_artifact_path"]:
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(run["index_artifact_path"], media_type="text/html")

    @app.get("/api/runs/{run_id}/artifact/result.zip")
    def read_zip_artifact(run_id: int, user=Depends(current_user)):
        run = get_run(resolved_db_path, user["id"], run_id)
        if not run["zip_artifact_path"]:
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(run["zip_artifact_path"], media_type="application/zip", filename="result.zip")

    @app.get("/api/approvals")
    def approvals(user=Depends(current_user)):
        return [dict(row) for row in list_web_approvals(resolved_db_path, user["id"])]

    @app.post("/api/approvals/{approval_id}/approve")
    def approve(approval_id: int, user=Depends(current_user)):
        return dict(approve_web_approval(resolved_db_path, resolved_data_root, user["id"], approval_id))

    @app.post("/api/approvals/{approval_id}/deny")
    def deny(approval_id: int, user=Depends(current_user)):
        return dict(deny_web_approval(resolved_db_path, resolved_data_root, user["id"], approval_id, "Denied in WebUI"))

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: int, user=Depends(current_user)):
        resume_run_once(resolved_db_path, resolved_data_root, user["id"], run_id)
        return dict(get_run(resolved_db_path, user["id"], run_id))

    @app.get("/api/settings")
    def read_settings(user=Depends(current_user)):
        return get_settings(resolved_db_path, user["id"])

    @app.put("/api/settings")
    def save_settings(request: SettingsRequest, user=Depends(current_user)):
        return update_settings(
            resolved_db_path,
            user["id"],
            governance_profile=request.governance_profile,
            context_strategy=request.context_strategy,
        )

    @app.put("/api/settings/api-key")
    def save_api_key(request: ApiKeyRequest, user=Depends(current_user)):
        return upsert_api_key(
            resolved_db_path,
            user["id"],
            request.api_key,
            encryption_secret=os.environ.get("SPECGATE_WEB_SECRET"),
        )

    @app.delete("/api/settings/api-key")
    def delete_api_key(user=Depends(current_user)):
        return clear_api_key(resolved_db_path, user["id"])

    static_dir = Path(__file__).with_name("web_static")
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


def _assert_project_owner(db_path: Path, project_id: int, user_id: int) -> None:
    with connect_db(db_path) as conn:
        row = conn.execute(
            "select id from projects where id = ? and user_id = ?",
            (project_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
```

- [ ] **Step 4: Add module entry point**

Create `src/specgate/web.py`:

```python
from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SpecGate WebUI server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("specgate.web_app:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run focused API tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_app -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/specgate/web_app.py src/specgate/web.py tests/test_web_app.py pyproject.toml
git commit -m "feat: add FastAPI web routes"
```

---

### Task 7: Codex-like Static Frontend

**Files:**
- Create: `tests/test_web_static.py`
- Create: `src/specgate/web_static/index.html`
- Create: `src/specgate/web_static/styles.css`
- Create: `src/specgate/web_static/app.js`

- [ ] **Step 1: Write static asset tests**

Create `tests/test_web_static.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path


STATIC_DIR = Path("src/specgate/web_static")


class WebStaticTests(unittest.TestCase):
    def test_static_assets_contain_required_ui_regions(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="project-list"', index)
        self.assertIn('id="message-list"', index)
        self.assertIn('id="detail-panel"', index)
        self.assertIn("startRun", app_js)
        self.assertIn("loadSettings", app_js)
        self.assertIn("approveApproval", app_js)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run static test and verify it fails**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: file not found for `src/specgate/web_static/index.html`.

- [ ] **Step 3: Create HTML shell**

Create `src/specgate/web_static/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SpecGate</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <main id="app-shell">
    <section id="auth-view" class="auth-view">
      <div class="auth-card">
        <h1>SpecGate</h1>
        <form id="auth-form">
          <input id="auth-username" autocomplete="username" placeholder="用户名">
          <input id="auth-password" autocomplete="current-password" type="password" placeholder="密码">
          <button id="auth-submit" type="submit">登录</button>
          <button id="auth-toggle" type="button">注册新账户</button>
          <p id="auth-error" class="error-text"></p>
        </form>
      </div>
    </section>

    <section id="workspace-view" class="workspace hidden">
      <aside class="sidebar">
        <div class="sidebar-header">
          <strong>SpecGate</strong>
          <button id="new-project-button">新项目</button>
        </div>
        <div id="project-list" class="project-list"></div>
        <button id="settings-button" class="sidebar-link">设置</button>
      </aside>

      <section class="conversation">
        <header id="conversation-title" class="conversation-title">选择一个项目</header>
        <div id="message-list" class="message-list"></div>
        <form id="run-form" class="composer">
          <textarea id="run-prompt" placeholder="要求后续变更"></textarea>
          <button type="submit">发送</button>
        </form>
      </section>

      <aside id="detail-panel" class="detail-panel">
        <nav class="tabs">
          <button data-tab="preview" class="active">预览</button>
          <button data-tab="report">报告</button>
          <button data-tab="approvals">审批</button>
          <button data-tab="settings">设置</button>
        </nav>
        <div id="detail-content" class="detail-content"></div>
      </aside>
    </section>

    <dialog id="project-dialog">
      <form id="project-form">
        <h2>创建项目</h2>
        <input id="project-name" placeholder="项目名">
        <textarea id="project-spec" placeholder="SPEC"></textarea>
        <textarea id="project-checklist" placeholder="CHECKLIST"></textarea>
        <textarea id="project-index" placeholder="可选 index.html"></textarea>
        <div class="dialog-actions">
          <button type="button" id="project-cancel">取消</button>
          <button type="submit">创建</button>
        </div>
      </form>
    </dialog>
  </main>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create CSS styling**

Create `src/specgate/web_static/styles.css`:

```css
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  color: #202124;
  background: #f7f7f8;
}
button, input, textarea { font: inherit; }
button {
  border: 1px solid #d8d8dc;
  background: #fff;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
}
.hidden { display: none !important; }
.auth-view {
  min-height: 100vh;
  display: grid;
  place-items: center;
}
.auth-card {
  width: min(420px, calc(100vw - 32px));
  background: #fff;
  border: 1px solid #e5e5e8;
  border-radius: 12px;
  padding: 32px;
}
.auth-card form { display: grid; gap: 12px; }
input, textarea {
  width: 100%;
  border: 1px solid #d8d8dc;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
}
textarea { resize: vertical; min-height: 92px; }
.workspace {
  display: grid;
  grid-template-columns: 280px minmax(420px, 1fr) 420px;
  height: 100vh;
}
.sidebar {
  border-right: 1px solid #e5e5e8;
  background: #f1f1f3;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.project-list { display: grid; gap: 6px; }
.project-item {
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
}
.project-item.active { background: #e2e2e6; }
.conversation {
  display: grid;
  grid-template-rows: auto 1fr auto;
  background: #fff;
}
.conversation-title {
  padding: 18px 24px;
  border-bottom: 1px solid #ededf0;
  font-weight: 600;
}
.message-list {
  padding: 24px;
  overflow: auto;
}
.message {
  max-width: 780px;
  margin: 0 auto 18px;
  line-height: 1.6;
}
.message.user {
  background: #f0f0f2;
  border-radius: 14px;
  padding: 12px 14px;
}
.composer {
  width: min(760px, calc(100% - 48px));
  margin: 0 auto 18px;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
}
.composer textarea {
  min-height: 56px;
  max-height: 160px;
}
.detail-panel {
  border-left: 1px solid #e5e5e8;
  background: #fbfbfc;
  display: grid;
  grid-template-rows: auto 1fr;
}
.tabs {
  display: flex;
  gap: 6px;
  padding: 12px;
  border-bottom: 1px solid #e5e5e8;
}
.tabs button.active { background: #202124; color: #fff; }
.detail-content {
  padding: 16px;
  overflow: auto;
}
.preview-frame {
  width: 100%;
  height: 70vh;
  border: 1px solid #d8d8dc;
  border-radius: 8px;
  background: #fff;
}
.error-text { color: #b42318; min-height: 20px; }
dialog {
  border: 1px solid #d8d8dc;
  border-radius: 12px;
  width: min(680px, calc(100vw - 32px));
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
@media (max-width: 1000px) {
  .workspace { grid-template-columns: 220px 1fr; }
  .detail-panel { display: none; }
}
```

- [ ] **Step 5: Create frontend JavaScript**

Create `src/specgate/web_static/app.js`:

```javascript
const state = {
  mode: "login",
  user: null,
  projects: [],
  activeProject: null,
  activeRun: null,
  activeTab: "preview"
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

async function boot() {
  bindEvents();
  try {
    state.user = await api("/api/me");
    showWorkspace();
    await loadProjects();
    await loadSettings();
  } catch {
    showAuth();
  }
}

function bindEvents() {
  $("auth-form").addEventListener("submit", submitAuth);
  $("auth-toggle").addEventListener("click", () => {
    state.mode = state.mode === "login" ? "register" : "login";
    $("auth-submit").textContent = state.mode === "login" ? "登录" : "注册";
    $("auth-toggle").textContent = state.mode === "login" ? "注册新账户" : "返回登录";
  });
  $("new-project-button").addEventListener("click", () => $("project-dialog").showModal());
  $("project-cancel").addEventListener("click", () => $("project-dialog").close());
  $("project-form").addEventListener("submit", createProject);
  $("run-form").addEventListener("submit", startRun);
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderDetail();
    });
  });
}

async function submitAuth(event) {
  event.preventDefault();
  $("auth-error").textContent = "";
  try {
    state.user = await api(state.mode === "login" ? "/api/auth/login" : "/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username: $("auth-username").value,
        password: $("auth-password").value
      })
    });
    showWorkspace();
    await loadProjects();
    await loadSettings();
  } catch (error) {
    $("auth-error").textContent = error.message;
  }
}

function showAuth() {
  $("auth-view").classList.remove("hidden");
  $("workspace-view").classList.add("hidden");
}

function showWorkspace() {
  $("auth-view").classList.add("hidden");
  $("workspace-view").classList.remove("hidden");
}

async function loadProjects() {
  state.projects = await api("/api/projects");
  renderProjects();
}

function renderProjects() {
  $("project-list").innerHTML = state.projects.map((project) => `
    <div class="project-item ${state.activeProject?.id === project.id ? "active" : ""}" data-project-id="${project.id}">
      <strong>${escapeHtml(project.name)}</strong><br>
      <small>${escapeHtml(project.last_run_status || "未运行")}</small>
    </div>
  `).join("");
  document.querySelectorAll(".project-item").forEach((item) => {
    item.addEventListener("click", () => {
      state.activeProject = state.projects.find((project) => String(project.id) === item.dataset.projectId);
      $("conversation-title").textContent = state.activeProject.name;
      renderProjects();
      renderMessages([]);
      renderDetail();
    });
  });
}

async function createProject(event) {
  event.preventDefault();
  const project = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      name: $("project-name").value,
      spec: $("project-spec").value,
      checklist: $("project-checklist").value,
      index_html: $("project-index").value
    })
  });
  $("project-dialog").close();
  await loadProjects();
  state.activeProject = project;
  $("conversation-title").textContent = project.name;
  renderDetail();
}

async function startRun(event) {
  event.preventDefault();
  if (!state.activeProject) return;
  const prompt = $("run-prompt").value.trim();
  if (!prompt) return;
  $("run-prompt").value = "";
  renderMessages([{ role: "user", content: prompt }, { role: "assistant", content: "运行中..." }]);
  state.activeRun = await api(`/api/projects/${state.activeProject.id}/runs`, {
    method: "POST",
    body: JSON.stringify({ prompt })
  });
  pollRun(state.activeRun.id);
}

async function pollRun(runId) {
  const run = await api(`/api/runs/${runId}`);
  state.activeRun = run;
  renderDetail();
  if (["queued", "running"].includes(run.status)) {
    setTimeout(() => pollRun(runId), 1000);
  } else {
    renderMessages([{ role: "assistant", content: `运行状态：${run.status}` }]);
    await loadProjects();
  }
}

function renderMessages(messages) {
  $("message-list").innerHTML = messages.map((message) => `
    <div class="message ${message.role}">${escapeHtml(message.content)}</div>
  `).join("");
}

async function loadSettings() {
  const settings = await api("/api/settings");
  return settings;
}

async function approveApproval(id) {
  await api(`/api/approvals/${id}/approve`, { method: "POST", body: "{}" });
  renderDetail();
}

async function denyApproval(id) {
  await api(`/api/approvals/${id}/deny`, { method: "POST", body: "{}" });
  renderDetail();
}

function renderDetail() {
  if (state.activeTab === "preview") {
    if (state.activeRun?.index_artifact_path) {
      $("detail-content").innerHTML = `<iframe class="preview-frame" src="/api/runs/${state.activeRun.id}/artifact/index.html"></iframe>`;
    } else {
      $("detail-content").innerHTML = "<p>运行完成后这里会显示 HTML 预览。</p>";
    }
    return;
  }
  if (state.activeTab === "report") {
    $("detail-content").innerHTML = state.activeRun
      ? `<p>状态：${escapeHtml(state.activeRun.status)}</p><p>信任等级：${escapeHtml(state.activeRun.trust_level || "未生成")}</p>`
      : "<p>暂无运行报告。</p>";
    return;
  }
  if (state.activeTab === "approvals") {
    renderApprovals();
    return;
  }
  $("detail-content").innerHTML = "<p>MockLLM 默认启用。真实 LLM API Key 仅作为预留设置。</p>";
}

async function renderApprovals() {
  const approvals = await api("/api/approvals");
  $("detail-content").innerHTML = approvals.map((approval) => `
    <section class="approval">
      <strong>${escapeHtml(approval.action_name)}</strong>
      <p>${escapeHtml(approval.reason)}</p>
      <p>${escapeHtml(approval.target_path || "")}</p>
      <button onclick="approveApproval(${approval.id})">批准</button>
      <button onclick="denyApproval(${approval.id})">拒绝</button>
    </section>
  `).join("") || "<p>暂无待审批项。</p>";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

boot();
```

- [ ] **Step 6: Run static test and verify it passes**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/specgate/web_static/index.html src/specgate/web_static/styles.css src/specgate/web_static/app.js tests/test_web_static.py
git commit -m "feat: add Codex-like web shell"
```

---

### Task 8: README, Full Regression, and Manual Smoke Run

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README WebUI usage section**

Add this section to `README.md`:

```markdown
## WebUI

SpecGate includes a mock-first WebUI product shell for local demos and future server deployment.

Start locally:

```powershell
$env:PYTHONPATH="src"
python -m specgate.web --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

The WebUI supports:

- account registration and login
- manual project creation with SPEC, CHECKLIST, and optional index.html
- zip project upload through the API
- task-style chat runs powered by MockLLM
- HTML preview and result artifact download
- governance settings
- HITL approval display and approve/deny/resume APIs

Runtime data is stored under `var/specgate_web/` by default. Set `SPECGATE_WEB_DATA` to move it. Set `SPECGATE_WEB_SECRET` before storing API key state on a deployed server. The default WebUI mode remains MockLLM and does not call real LLM providers.
```

- [ ] **Step 2: Run all Web tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_db tests.test_web_auth tests.test_web_settings tests.test_web_projects tests.test_web_runs tests.test_web_approvals tests.test_web_app tests.test_web_static -v
```

Expected: all Web tests pass.

- [ ] **Step 3: Run the full test suite**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 4: Manual smoke run**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.web --host 127.0.0.1 --port 8000
```

Manual checks:

- Open `http://127.0.0.1:8000`.
- Register a user.
- Create a manual project with SPEC and CHECKLIST.
- Send a run prompt.
- Confirm the right panel shows a status and then a preview when the run completes.
- Stop the server with `Ctrl+C`.

- [ ] **Step 5: Commit**

```powershell
git add README.md
git commit -m "docs: document WebUI usage"
```

---

## Self-Review

Spec coverage:

- Login/register: Task 2 and Task 6.
- SQLite persistence: Task 1.
- API Key settings and mock-first mode: Task 2 and Task 6.
- Zip/manual project input: Task 3 and Task 6.
- Isolated original/workspace/artifacts directories: Task 3.
- Chat/task run model: Task 4, Task 6, Task 7.
- Lightweight background task and polling: Task 4, Task 6, Task 7.
- HTML preview and artifact download: Task 3, Task 4, Task 6, Task 7.
- HITL approve/deny/resume: Task 5 and Task 6.
- Codex-like UI and settings page foundation: Task 7.
- Server deployment entry: Task 6 and Task 8.
- Regression and smoke verification: Task 8.

Placeholder scan:

- The plan contains concrete file paths, test names, commands, and implementation snippets.
- No open-ended implementation markers are intentionally left.

Type consistency:

- `db_path` and `data_root` are `Path`.
- `user_id`, `project_id`, `run_id`, and Web approval IDs are integers.
- Run statuses are `queued`, `running`, `completed`, `needs_approval`, and `failed`.
- API route names match frontend calls in `app.js`.
