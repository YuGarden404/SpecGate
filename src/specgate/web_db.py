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
    id text primary key,
    user_id integer not null references users(id) on delete cascade,
    created_at text not null default current_timestamp,
    last_seen_at text not null default current_timestamp,
    expires_at text
);

create table if not exists user_settings (
    user_id integer primary key references users(id) on delete cascade,
    settings_json text not null default '{}',
    updated_at text not null default current_timestamp
);

create table if not exists projects (
    id integer primary key autoincrement,
    user_id integer references users(id) on delete set null,
    name text not null,
    root_path text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
);

create table if not exists messages (
    id integer primary key autoincrement,
    project_id integer not null references projects(id) on delete cascade,
    user_id integer references users(id) on delete set null,
    role text not null,
    content text not null,
    created_at text not null default current_timestamp
);

create table if not exists runs (
    id integer primary key autoincrement,
    project_id integer not null references projects(id) on delete cascade,
    user_id integer references users(id) on delete set null,
    status text not null default 'pending',
    goal text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
);

create table if not exists approvals (
    id integer primary key autoincrement,
    run_id integer not null references runs(id) on delete cascade,
    status text not null default 'pending',
    action text not null,
    path text,
    reason text,
    created_at text not null default current_timestamp,
    decided_at text
);

create table if not exists artifacts (
    id integer primary key autoincrement,
    run_id integer not null references runs(id) on delete cascade,
    kind text not null,
    path text not null,
    metadata_json text not null default '{}',
    created_at text not null default current_timestamp
);
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
