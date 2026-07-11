import sqlite3
from pathlib import Path


SCHEMA = """
create table if not exists users (
    id integer primary key autoincrement,
    username text not null unique,
    password_hash text not null,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
);

create table if not exists sessions (
    token text primary key,
    user_id integer not null references users(id) on delete cascade,
    created_at text not null default current_timestamp,
    expires_at text
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
    create_mode text,
    root_path text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp,
    last_run_status text
);

create table if not exists messages (
    id integer primary key autoincrement,
    project_id integer not null references projects(id) on delete cascade,
    user_id integer not null references users(id) on delete cascade,
    role text not null,
    content text not null,
    created_at text not null default current_timestamp
);

create table if not exists runs (
    id integer primary key autoincrement,
    project_id integer not null references projects(id) on delete cascade,
    user_id integer not null references users(id) on delete cascade,
    status text not null default 'pending',
    prompt text not null,
    trust_level text,
    report_path text,
    index_artifact_path text,
    zip_artifact_path text,
    error_message text,
    created_at text not null default current_timestamp,
    started_at text,
    finished_at text
);

create table if not exists approvals (
    id integer primary key autoincrement,
    run_id integer not null references runs(id) on delete cascade,
    project_id integer not null references projects(id) on delete cascade,
    approval_id text not null,
    status text not null default 'pending',
    action_name text not null,
    target_path text,
    reason text,
    preview_json text not null default '{}',
    created_at text not null default current_timestamp,
    decided_at text
);

create table if not exists artifacts (
    id integer primary key autoincrement,
    run_id integer not null references runs(id) on delete cascade,
    kind text not null,
    path text not null,
    created_at text not null default current_timestamp
);

pragma user_version = 1;
"""


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_db(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
