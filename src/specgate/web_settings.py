from __future__ import annotations

from pathlib import Path

from specgate.runtime_config import RunRuntimeConfig
from specgate.web_credentials import WebCredentialService
from specgate.web_db import connect_db


def _ensure_settings(conn, user_id: int) -> None:
    conn.execute(
        "insert or ignore into user_settings (user_id) values (?)",
        (user_id,),
    )


def get_runtime_settings(db_path: Path, user_id: int) -> dict:
    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.commit()
        row = conn.execute(
            """
            select governance_profile, context_strategy, max_steps,
                   context_budget_chars, retrieval_top_k, retrieval_budget_chars,
                   compression_max_tool_result_chars
            from user_settings where user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("settings not found")
        return {
            "governance_profile": row["governance_profile"],
            "context_strategy": row["context_strategy"],
            "max_steps": row["max_steps"],
            "context_budget_chars": row["context_budget_chars"],
            "retrieval_top_k": row["retrieval_top_k"],
            "retrieval_budget_chars": row["retrieval_budget_chars"],
            "compression_max_tool_result_chars": row[
                "compression_max_tool_result_chars"
            ],
        }
    finally:
        conn.close()


def get_settings(
    db_path: Path,
    user_id: int,
    credentials: WebCredentialService,
) -> dict:
    runtime = get_runtime_settings(db_path, user_id)
    status = credentials.status(user_id)
    return {
        **runtime,
        "api_key_configured": status.configured,
        "api_key_storage": status.storage,
        "api_key_requires_reentry": status.requires_reentry,
        "credential_store_available": status.store_available,
        "llm_mode": "mock",
    }


def upsert_api_key(
    db_path: Path,
    user_id: int,
    api_key: str,
    credentials: WebCredentialService,
) -> dict:
    credentials.put(user_id, api_key)
    return get_settings(db_path, user_id, credentials)


def clear_api_key(
    db_path: Path,
    user_id: int,
    credentials: WebCredentialService,
) -> dict:
    credentials.clear(user_id)
    return get_settings(db_path, user_id, credentials)


def update_settings(
    db_path: Path,
    user_id: int,
    governance_profile: str,
    context_strategy: str,
    max_steps: int,
    context_budget_chars: int,
    retrieval_top_k: int,
    retrieval_budget_chars: int,
    compression_max_tool_result_chars: int,
    credentials: WebCredentialService,
) -> dict:
    config = RunRuntimeConfig.from_settings(
        {
            "governance_profile": governance_profile,
            "context_strategy": context_strategy,
            "max_steps": max_steps,
            "context_budget_chars": context_budget_chars,
            "retrieval_top_k": retrieval_top_k,
            "retrieval_budget_chars": retrieval_budget_chars,
            "compression_max_tool_result_chars": compression_max_tool_result_chars,
        }
    )
    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.execute(
            """
            update user_settings
            set governance_profile = ?, context_strategy = ?,
                max_steps = ?, context_budget_chars = ?, retrieval_top_k = ?,
                retrieval_budget_chars = ?, compression_max_tool_result_chars = ?
            where user_id = ?
            """,
            (
                config.governance_profile,
                config.context_strategy,
                config.max_steps,
                config.context_budget_chars,
                config.retrieval_top_k,
                config.retrieval_budget_chars,
                config.compression_max_tool_result_chars,
                user_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_settings(db_path, user_id, credentials)
