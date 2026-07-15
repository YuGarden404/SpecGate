import sqlite3
from pathlib import Path

from specgate.llm_config import LLMRunConfig
from specgate.runtime_config import RunRuntimeConfig


LATEST_SCHEMA_VERSION = 5

USER_CREDENTIALS_SCHEMA = """
create table if not exists user_credentials (
    user_id integer not null references users(id) on delete cascade,
    provider text not null,
    status text not null
        check (status in ('configured', 'requires_reentry')),
    ciphertext blob,
    nonce blob,
    key_version integer,
    key_id text,
    updated_at text not null default current_timestamp,
    primary key (user_id, provider)
);
"""


SCHEMA = f"""
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
    max_steps integer not null default 5,
    context_budget_chars integer not null default 12000,
    retrieval_top_k integer not null default 6,
    retrieval_budget_chars integer not null default 9000,
    compression_max_tool_result_chars integer not null default 1200,
    llm_base_url text,
    llm_model text,
    api_key_configured integer not null default 0,
    api_key_ciphertext text
);

{USER_CREDENTIALS_SCHEMA}

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
    finished_at text,
    cancel_requested_at text,
    deadline_at text,
    runtime_config_json text,
    llm_config_json text
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
    preview_json text not null default '{{}}',
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

pragma user_version = 5;
"""


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma synchronous = normal")
    conn.execute("pragma busy_timeout = 5000")
    return conn


def _database_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("pragma user_version").fetchone()[0])


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    conn.execute("begin immediate")
    try:
        conn.execute(USER_CREDENTIALS_SCHEMA)
        conn.execute(
            """
            insert or ignore into user_credentials (
                user_id,
                provider,
                status
            )
            select
                user_id,
                'openai-compatible',
                'requires_reentry'
            from user_settings
            where api_key_configured = 1
               or api_key_ciphertext is not null
            """
        )
        conn.execute(
            """
            update user_settings
            set api_key_configured = 0,
                api_key_ciphertext = null
            where api_key_configured != 0
               or api_key_ciphertext is not null
            """
        )
        conn.execute("pragma user_version = 2")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    conn.execute("begin immediate")
    try:
        conn.execute("alter table runs add column cancel_requested_at text")
        conn.execute("alter table runs add column deadline_at text")
        conn.execute("pragma user_version = 3")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    conn.execute("begin immediate")
    try:
        conn.execute(
            "alter table user_settings add column max_steps integer not null default 5"
        )
        conn.execute(
            "alter table user_settings add column context_budget_chars integer not null default 12000"
        )
        conn.execute(
            "alter table user_settings add column retrieval_top_k integer not null default 6"
        )
        conn.execute(
            "alter table user_settings add column retrieval_budget_chars integer not null default 9000"
        )
        conn.execute(
            """
            alter table user_settings
            add column compression_max_tool_result_chars integer not null default 1200
            """
        )
        conn.execute("alter table runs add column runtime_config_json text")
        rows = conn.execute(
            """
            select runs.id,
                   coalesce(user_settings.governance_profile, 'review')
                       as governance_profile,
                   coalesce(user_settings.context_strategy, 'injection-safe')
                       as context_strategy,
                   coalesce(user_settings.max_steps, 5) as max_steps,
                   coalesce(user_settings.context_budget_chars, 12000)
                       as context_budget_chars,
                   coalesce(user_settings.retrieval_top_k, 6) as retrieval_top_k,
                   coalesce(user_settings.retrieval_budget_chars, 9000)
                       as retrieval_budget_chars,
                   coalesce(user_settings.compression_max_tool_result_chars, 1200)
                       as compression_max_tool_result_chars
            from runs
            left join user_settings on user_settings.user_id = runs.user_id
            order by runs.id
            """
        ).fetchall()
        for row in rows:
            config = RunRuntimeConfig.for_migration(dict(row))
            conn.execute(
                "update runs set runtime_config_json = ? where id = ?",
                (config.to_json(), row["id"]),
            )
        missing = conn.execute(
            "select count(*) from runs where runtime_config_json is null"
        ).fetchone()[0]
        if missing:
            raise RuntimeError("runtime config migration left empty snapshots")
        conn.execute("pragma user_version = 4")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    conn.execute("begin immediate")
    try:
        conn.execute("alter table user_settings add column llm_base_url text")
        conn.execute("alter table user_settings add column llm_model text")
        conn.execute("alter table runs add column llm_config_json text")
        migrated = LLMRunConfig.mock(source="migration-v5").to_json()
        conn.execute(
            "update runs set llm_config_json = ? where llm_config_json is null",
            (migrated,),
        )
        missing = conn.execute(
            "select count(*) from runs where llm_config_json is null"
        ).fetchone()[0]
        if missing:
            raise RuntimeError("LLM config migration left empty snapshots")
        conn.execute("pragma user_version = 5")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_db(db_path)
    try:
        version = _database_version(conn)
        if version == 0:
            conn.executescript(SCHEMA)
            return
        if version == 1:
            _migrate_v1_to_v2(conn)
            version = 2
        if version == 2:
            _migrate_v2_to_v3(conn)
            version = 3
        if version == 3:
            _migrate_v3_to_v4(conn)
            version = 4
        if version == 4:
            _migrate_v4_to_v5(conn)
            version = 5
        if version == LATEST_SCHEMA_VERSION:
            conn.execute(USER_CREDENTIALS_SCHEMA)
            conn.commit()
            return
        if version > LATEST_SCHEMA_VERSION:
            raise RuntimeError("database uses a newer schema version")
        raise RuntimeError("unsupported database schema version")
    finally:
        conn.close()
