from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from specgate.web_db import connect_db


HASH_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000
SESSION_TTL = timedelta(days=7)


def utc_now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str, *, salt: str | None = None) -> str:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    password_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        password_salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"{HASH_ALGORITHM}${password_salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt, expected_digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != HASH_ALGORITHM:
        return False
    try:
        candidate = hash_password(password, salt=salt).split("$", 2)[2]
    except ValueError:
        return False
    return hmac.compare_digest(candidate, expected_digest)


def create_user(db_path: Path, username: str, password: str) -> sqlite3.Row:
    normalized_username = username.strip()
    if not normalized_username:
        raise ValueError("username is required")

    conn = connect_db(db_path)
    try:
        password_hash = hash_password(password)
        try:
            cursor = conn.execute(
                "insert into users (username, password_hash, created_at, updated_at) values (?, ?, ?, ?)",
                (
                    normalized_username,
                    password_hash,
                    utc_now().isoformat(),
                    utc_now().isoformat(),
                ),
            )
            user_id = cursor.lastrowid
            conn.execute(
                "insert or ignore into user_settings (user_id) values (?)",
                (user_id,),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ValueError("username is unavailable") from exc
        return conn.execute(
            "select * from users where id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def authenticate_user(db_path: Path, username: str, password: str) -> sqlite3.Row:
    normalized_username = username.strip()
    conn = connect_db(db_path)
    try:
        user = conn.execute(
            "select * from users where username = ?",
            (normalized_username,),
        ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            raise ValueError("invalid username or password")
        conn.execute(
            "insert or ignore into user_settings (user_id) values (?)",
            (user["id"],),
        )
        conn.commit()
        return user
    finally:
        conn.close()


def create_session(db_path: Path, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    expires_at = now + SESSION_TTL
    conn = connect_db(db_path)
    try:
        conn.execute(
            "insert into sessions (token, user_id, created_at, expires_at) values (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires_at.isoformat()),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def get_user_by_session(db_path: Path, token: str | None) -> sqlite3.Row:
    if not token:
        raise ValueError("invalid session")

    conn = connect_db(db_path)
    try:
        row = conn.execute(
            """
            select users.*, sessions.expires_at
            from sessions
            join users on users.id = sessions.user_id
            where sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            raise ValueError("invalid session")
        expires_at = row["expires_at"]
        if expires_at is not None and datetime.fromisoformat(expires_at) <= utc_now():
            raise ValueError("invalid session")
        return row
    finally:
        conn.close()


def delete_session(db_path: Path, token: str) -> None:
    conn = connect_db(db_path)
    try:
        conn.execute("delete from sessions where token = ?", (token,))
        conn.commit()
    finally:
        conn.close()
