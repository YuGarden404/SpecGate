from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

from specgate.approvals import VALID_GOVERNANCE_PROFILES
from specgate.config import VALID_CONTEXT_STRATEGIES
from specgate.web_db import connect_db


def _ensure_settings(conn, user_id: int) -> None:
    conn.execute(
        "insert or ignore into user_settings (user_id) values (?)",
        (user_id,),
    )


def _settings_dict(row) -> dict:
    api_key_configured = bool(row["api_key_configured"])
    api_key_ciphertext = row["api_key_ciphertext"]
    return {
        "governance_profile": row["governance_profile"],
        "context_strategy": row["context_strategy"],
        "api_key_configured": api_key_configured,
        "api_key_storage": "protected" if api_key_ciphertext else "not_stored",
        "llm_mode": "openai" if api_key_configured else "mock",
    }


def _fetch_settings(conn, user_id: int) -> dict:
    row = conn.execute(
        "select * from user_settings where user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise ValueError("settings not found")
    return _settings_dict(row)


def get_settings(db_path: Path, user_id: int) -> dict:
    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.commit()
        return _fetch_settings(conn, user_id)
    finally:
        conn.close()


def update_settings(
    db_path: Path,
    user_id: int,
    governance_profile: str,
    context_strategy: str,
) -> dict:
    if governance_profile not in VALID_GOVERNANCE_PROFILES:
        raise ValueError("invalid governance profile")
    if context_strategy not in VALID_CONTEXT_STRATEGIES:
        raise ValueError("invalid context strategy")

    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.execute(
            """
            update user_settings
            set governance_profile = ?, context_strategy = ?
            where user_id = ?
            """,
            (governance_profile, context_strategy, user_id),
        )
        conn.commit()
        return _fetch_settings(conn, user_id)
    finally:
        conn.close()


def upsert_api_key(
    db_path: Path,
    user_id: int,
    api_key: str,
    encryption_secret: str | None,
) -> dict:
    normalized_key = api_key.strip()
    if not normalized_key:
        raise ValueError("api key is required")

    protected_value = None
    if encryption_secret:
        digest = hmac.new(
            encryption_secret.encode("utf-8"),
            normalized_key.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        protected_value = "hmac_sha256$" + base64.urlsafe_b64encode(digest).decode("ascii")

    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.execute(
            """
            update user_settings
            set api_key_configured = 1, api_key_ciphertext = ?
            where user_id = ?
            """,
            (protected_value, user_id),
        )
        conn.commit()
        return _fetch_settings(conn, user_id)
    finally:
        conn.close()


def clear_api_key(db_path: Path, user_id: int) -> dict:
    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.execute(
            """
            update user_settings
            set api_key_configured = 0, api_key_ciphertext = null
            where user_id = ?
            """,
            (user_id,),
        )
        conn.commit()
        return _fetch_settings(conn, user_id)
    finally:
        conn.close()
