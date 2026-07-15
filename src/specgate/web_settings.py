from __future__ import annotations

from pathlib import Path

from specgate.llm_transport import LLMEndpointPolicy, LLMTransportError
from specgate.runtime_config import RunRuntimeConfig
from specgate.web_credentials import WebCredentialService
from specgate.web_db import connect_db
from specgate.web_llm import (
    WebLLMError,
    describe_llm_settings,
    validate_llm_model,
)


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
    endpoint_policy: LLMEndpointPolicy | None = None,
) -> dict:
    runtime = get_runtime_settings(db_path, user_id)
    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.commit()
        llm = conn.execute(
            """
            select llm_base_url, llm_model
            from user_settings where user_id = ?
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if llm is None:
        raise ValueError("settings not found")
    status = credentials.status(user_id)
    snapshot = credentials.snapshot(user_id)
    policy = endpoint_policy or LLMEndpointPolicy.from_csv("")
    llm_state = describe_llm_settings(
        llm["llm_base_url"],
        llm["llm_model"],
        snapshot,
        policy,
    )
    return {
        **runtime,
        "api_key_configured": status.configured,
        "api_key_storage": status.storage,
        "api_key_requires_reentry": status.requires_reentry,
        "credential_store_available": status.store_available,
        "llm_base_url": llm["llm_base_url"],
        "llm_model": llm["llm_model"],
        **llm_state,
    }


def upsert_api_key(
    db_path: Path,
    user_id: int,
    api_key: str,
    credentials: WebCredentialService,
    endpoint_policy: LLMEndpointPolicy | None = None,
) -> dict:
    credentials.put(user_id, api_key)
    return get_settings(db_path, user_id, credentials, endpoint_policy)


def clear_api_key(
    db_path: Path,
    user_id: int,
    credentials: WebCredentialService,
    endpoint_policy: LLMEndpointPolicy | None = None,
) -> dict:
    credentials.clear(user_id)
    return get_settings(db_path, user_id, credentials, endpoint_policy)


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
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    endpoint_policy: LLMEndpointPolicy | None = None,
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
    policy = endpoint_policy or LLMEndpointPolicy.from_csv("")
    normalized_base_url = None
    if llm_base_url is not None and llm_base_url.strip():
        try:
            normalized_base_url = policy.normalize(llm_base_url.strip()).base_url
        except LLMTransportError as exc:
            raise ValueError(exc.code) from exc
    normalized_model = None
    if llm_model is not None and llm_model.strip():
        try:
            normalized_model = validate_llm_model(llm_model)
        except WebLLMError as exc:
            raise ValueError(exc.code) from exc
    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.execute(
            """
            update user_settings
            set governance_profile = ?, context_strategy = ?,
                max_steps = ?, context_budget_chars = ?, retrieval_top_k = ?,
                retrieval_budget_chars = ?, compression_max_tool_result_chars = ?,
                llm_base_url = ?, llm_model = ?
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
                normalized_base_url,
                normalized_model,
                user_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_settings(db_path, user_id, credentials, policy)
