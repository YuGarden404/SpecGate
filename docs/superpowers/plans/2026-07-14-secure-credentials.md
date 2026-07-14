# 安全凭据存储实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用操作系统 keyring 替换 CLI 明文 `.env` 持久化，并用 AES-256-GCM 与独立主密钥实现 Web 多用户可逆加密存储，同时保持 MockLLM 为唯一运行模式。

**Architecture:** 新增通用 `CredentialStore` 协议和 keyring 后端，`credentials.py` 作为“环境变量优先、keyring 次之”的 CLI facade。Web 使用独立 `WebCredentialCipher` 和 `WebCredentialService`，把带用户/provider AAD 的 AES-GCM 密文保存到 schema version 2 的 `user_credentials` 表；旧 HMAC 状态迁移为 `requires_reentry`。

**Tech Stack:** Python 3.11、`keyring`、`cryptography.hazmat.primitives.ciphers.aead.AESGCM`、SQLite、FastAPI、原有 unittest 测试体系。

**Git 约束:** Agent 不执行 `git add`、`git commit`、`git push` 或 PR 操作；每个任务完成后由用户自行提交。提交信息和文档尽量使用中文。

---

## 文件职责

- 新建 `src/specgate/credential_store.py`：存储协议、稳定异常和操作系统 keyring adapter。
- 修改 `src/specgate/credentials.py`：provider 校验、凭据输入校验、环境变量/keyring 解析和安全状态。
- 新建 `src/specgate/web_credentials.py`：Web 主密钥、AES-GCM、AAD、SQLite repository 和安全状态。
- 修改 `src/specgate/web_db.py`：schema version 2 与 version 1 到 version 2 的确定性迁移。
- 修改 `src/specgate/web_settings.py`：治理/上下文设置与凭据状态组合，不再实现 HMAC。
- 修改 `src/specgate/web_app.py`：初始化 Web credential service，映射安全错误码。
- 修改 `src/specgate/web_runs.py`：只读取运行设置，不加载或接触 Web 凭据。
- 修改 `src/specgate/cli.py`：移除 `--env-file`，让 run/eval/credentials 使用统一 resolver。
- 修改 `src/specgate/web_static/app.js`：展示 encrypted/requires_reentry/unavailable 状态。
- 修改 `pyproject.toml`：增加受约束的 `keyring` 和 `cryptography` 依赖。
- 新建 `tests/test_credential_store.py`、`tests/test_web_credentials.py`，并扩展 CLI、数据库、Settings、API 和静态前端测试。

---

### Task 1: 引入依赖并实现可注入的 keyring 存储边界

**Files:**
- Modify: `pyproject.toml`
- Create: `src/specgate/credential_store.py`
- Create: `tests/test_credential_store.py`

- [ ] **Step 1: 写 keyring adapter RED 测试**

创建 `tests/test_credential_store.py`：

```python
import unittest

from keyring.errors import KeyringError, PasswordDeleteError

from specgate.credential_store import (
    CredentialStoreUnavailable,
    KeyringCredentialStore,
)


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        key = (service, username)
        if key not in self.values:
            raise PasswordDeleteError("missing")
        del self.values[key]


class BrokenKeyring:
    def get_password(self, service, username):
        raise KeyringError("backend unavailable")

    def set_password(self, service, username, password):
        raise KeyringError("backend unavailable")

    def delete_password(self, service, username):
        raise KeyringError("backend unavailable")


class CredentialStoreTests(unittest.TestCase):
    def test_keyring_round_trip_and_idempotent_clear(self):
        backend = MemoryKeyring()
        store = KeyringCredentialStore(backend=backend)

        self.assertIsNone(store.get("openai-compatible"))
        store.set("openai-compatible", "secret-value")
        self.assertEqual(store.get("openai-compatible"), "secret-value")
        store.clear("openai-compatible")
        store.clear("openai-compatible")
        self.assertIsNone(store.get("openai-compatible"))

    def test_keyring_errors_are_wrapped_without_secret(self):
        store = KeyringCredentialStore(backend=BrokenKeyring())
        sentinel = "SECRET_SENTINEL_credential_store"

        with self.assertRaises(CredentialStoreUnavailable) as raised:
            store.set("openai-compatible", sentinel)

        self.assertEqual(raised.exception.code, "credential_store_unavailable")
        self.assertNotIn(sentinel, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
python -m pip install -e .
$env:PYTHONPATH="src"
python -m unittest tests.test_credential_store -v
```

Expected: FAIL，原因是 `specgate.credential_store` 尚不存在，且 `pyproject.toml` 尚未声明依赖。

- [ ] **Step 3: 增加依赖**

在 `pyproject.toml` 的 `dependencies` 中增加：

```toml
    "keyring>=25,<26",
    "cryptography>=44,<47",
```

- [ ] **Step 4: 实现 keyring adapter**

创建 `src/specgate/credential_store.py`：

```python
from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError


KEYRING_SERVICE = "specgate"


class CredentialStoreError(ValueError):
    code = "credential_store_error"


class CredentialStoreUnavailable(CredentialStoreError):
    code = "credential_store_unavailable"


class CredentialStore(Protocol):
    def get(self, provider: str) -> str | None: ...
    def set(self, provider: str, secret: str) -> None: ...
    def clear(self, provider: str) -> None: ...


class KeyringCredentialStore:
    def __init__(self, backend=None):
        self.backend = backend or keyring

    def get(self, provider: str) -> str | None:
        try:
            return self.backend.get_password(KEYRING_SERVICE, provider)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "credential store is unavailable"
            ) from exc

    def set(self, provider: str, secret: str) -> None:
        try:
            self.backend.set_password(KEYRING_SERVICE, provider, secret)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "credential store is unavailable"
            ) from exc

    def clear(self, provider: str) -> None:
        try:
            self.backend.delete_password(KEYRING_SERVICE, provider)
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "credential store is unavailable"
            ) from exc
```

- [ ] **Step 5: 运行测试确认 GREEN**

Run:

```powershell
python -m pip install -e .
$env:PYTHONPATH="src"
python -m unittest tests.test_credential_store -v
```

Expected: PASS。

- [ ] **Step 6: 用户提交 Task 1**

建议提交信息：

```text
feat: 增加系统 keyring 凭据存储边界
```

---

### Task 2: 重构 CLI 凭据解析并移除 .env

**Files:**
- Modify: `src/specgate/credentials.py`
- Modify: `src/specgate/cli.py`
- Modify: `tests/test_credentials.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 写环境变量优先级和 keyring 生命周期 RED 测试**

将 `tests/test_credentials.py` 改为使用内存 store：

```python
import unittest

from specgate.credentials import (
    CredentialStatus,
    clear_credential,
    credential_status,
    read_credential,
    set_credential,
)


class MemoryStore:
    def __init__(self):
        self.values = {}

    def get(self, provider):
        return self.values.get(provider)

    def set(self, provider, secret):
        self.values[provider] = secret

    def clear(self, provider):
        self.values.pop(provider, None)


class CredentialTests(unittest.TestCase):
    def test_environment_overrides_keyring(self):
        store = MemoryStore()
        store.set("openai-compatible", "keyring-secret")
        environ = {"OPENAI_COMPATIBLE_API_KEY": "environment-secret"}

        self.assertEqual(
            read_credential("openai-compatible", store=store, environ=environ),
            "environment-secret",
        )
        self.assertEqual(
            credential_status(
                "openai-compatible",
                store=store,
                environ=environ,
            ).source,
            "environment",
        )

    def test_keyring_is_used_when_environment_is_missing(self):
        store = MemoryStore()
        set_credential("openai-compatible", "keyring-secret", store=store)

        status = credential_status(
            "openai-compatible",
            store=store,
            environ={},
        )

        self.assertEqual(status.source, "keyring")
        self.assertEqual(
            read_credential("openai-compatible", store=store, environ={}),
            "keyring-secret",
        )
        clear_credential("openai-compatible", store=store)
        self.assertFalse(
            credential_status(
                "openai-compatible",
                store=store,
                environ={},
            ).configured
        )

    def test_clear_does_not_hide_active_environment_variable(self):
        store = MemoryStore()
        store.set("openai", "keyring-secret")
        environ = {"OPENAI_API_KEY": "environment-secret"}

        clear_credential("openai", store=store)
        status = credential_status("openai", store=store, environ=environ)

        self.assertTrue(status.configured)
        self.assertEqual(status.source, "environment")
```

- [ ] **Step 2: 写 CLI 不接受 --env-file 的 RED 测试**

在 `tests/test_cli.py` 增加：

```python
class MemoryCredentialStore:
    def __init__(self):
        self.values = {}

    def get(self, provider):
        return self.values.get(provider)

    def set(self, provider, secret):
        self.values[provider] = secret

    def clear(self, provider):
        self.values.pop(provider, None)


def test_credentials_cli_uses_store_and_rejects_env_file(self):
    store = MemoryCredentialStore()

    with (
        patch.dict(os.environ, {}, clear=True),
        patch(
            "specgate.credentials.KeyringCredentialStore",
            return_value=store,
        ),
    ):
        self.assertEqual(
            main(
                [
                    "credentials",
                    "set",
                    "openai",
                    "--value",
                    "sk-test-secret-123456",
                ]
            ),
            0,
        )
        self.assertEqual(main(["credentials", "status", "openai"]), 0)
        self.assertEqual(main(["credentials", "clear", "openai"]), 0)

    with self.assertRaises(SystemExit):
        main(
            [
                "credentials",
                "status",
                "openai",
                "--env-file",
                ".env",
            ]
        )
```

- [ ] **Step 3: 运行测试确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_credentials tests.test_cli -v
```

Expected: FAIL，当前函数仍要求 `env_file`，CLI 仍接受 `--env-file`。

- [ ] **Step 4: 实现 CLI facade**

将 `src/specgate/credentials.py` 收敛为以下公开接口：

```python
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from specgate.credential_store import (
    CredentialStore,
    CredentialStoreUnavailable,
    KeyringCredentialStore,
)


MAX_CREDENTIAL_CHARS = 4096
ENV_NAMES = {
    "openai": "OPENAI_API_KEY",
    "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
SUPPORTED_PROVIDERS = frozenset(ENV_NAMES)


@dataclass(frozen=True)
class CredentialStatus:
    provider: str
    configured: bool
    safe_to_run: bool
    source: str
    message: str


def _store(store: CredentialStore | None) -> CredentialStore:
    return store or KeyringCredentialStore()


def _validate_provider(provider: str) -> None:
    if provider == "mock":
        return
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")


def _validate_secret(secret: str) -> str:
    normalized = secret.strip()
    if not normalized or len(normalized) > MAX_CREDENTIAL_CHARS:
        raise ValueError("invalid_credential")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("invalid_credential")
    return normalized


def read_credential(
    provider: str,
    *,
    store: CredentialStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    _validate_provider(provider)
    if provider == "mock":
        return None
    values = os.environ if environ is None else environ
    environment_value = values.get(ENV_NAMES[provider])
    if environment_value:
        return environment_value
    return _store(store).get(provider)


def credential_status(
    provider: str,
    *,
    store: CredentialStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> CredentialStatus:
    if provider == "mock":
        return CredentialStatus(
            "mock", True, True, "mock", "mock mode does not require credentials"
        )
    _validate_provider(provider)
    values = os.environ if environ is None else environ
    if values.get(ENV_NAMES[provider]):
        return CredentialStatus(
            provider, True, True, "environment",
            f"{provider} credential is configured via environment",
        )
    try:
        configured = bool(_store(store).get(provider))
    except CredentialStoreUnavailable:
        return CredentialStatus(
            provider, False, False, "unavailable",
            "credential store is unavailable",
        )
    return CredentialStatus(
        provider,
        configured,
        configured,
        "keyring" if configured else "none",
        (
            f"{provider} credential is configured via system keyring"
            if configured
            else f"{provider} credential is not configured"
        ),
    )


def set_credential(
    provider: str,
    secret: str,
    *,
    store: CredentialStore | None = None,
) -> None:
    _validate_provider(provider)
    if provider == "mock":
        raise ValueError("mock provider does not need credentials")
    _store(store).set(provider, _validate_secret(secret))


def clear_credential(
    provider: str,
    *,
    store: CredentialStore | None = None,
) -> None:
    _validate_provider(provider)
    _store(store).clear(provider)
```

- [ ] **Step 5: 接通 run/eval/credentials CLI**

在 `src/specgate/cli.py`：

- 删除 `credential_status_from_env` 导入和调用。
- 删除 run、eval、credentials 子命令的 `--env-file` 参数。
- 删除 `run_real_llm` 与 `run_real_eval` 的 `env_file` 参数。
- `run_real_llm` 和 `run_real_eval` 使用：

```python
status = credential_status(provider)
if not status.safe_to_run:
    print(status.message)
    return 1
api_key = read_credential(provider)
if not api_key:
    print(f"{provider} credential is not configured")
    return 1
```

- credentials 命令使用：

```python
if args.credentials_command == "status":
    status = credential_status(args.provider)
    print(status.message)
    return 0 if status.safe_to_run else 1
if args.credentials_command == "set":
    secret = args.value if args.value is not None else getpass.getpass("API key: ")
    set_credential(args.provider, secret)
    print(f"{args.provider} credential saved to system keyring; secret value hidden")
    return 0
if args.credentials_command == "clear":
    clear_credential(args.provider)
    status = credential_status(args.provider)
    print(
        f"{args.provider} keyring credential cleared; "
        f"effective source={status.source}"
    )
    return 0
```

- [ ] **Step 6: 运行 CLI 聚焦测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_credential_store tests.test_credentials tests.test_cli -v
```

Expected: PASS，且测试临时目录中不产生 `.env`。

- [ ] **Step 7: 用户提交 Task 2**

建议提交信息：

```text
feat: 将 CLI 凭据迁移到系统 keyring
```

---

### Task 3: 实现 Web 主密钥与 AES-GCM 核心

**Files:**
- Create: `src/specgate/web_credentials.py`
- Create: `tests/test_web_credentials.py`

- [ ] **Step 1: 写主密钥与 AES-GCM RED 测试**

创建 `tests/test_web_credentials.py`：

```python
import base64
import unittest

from specgate.web_credentials import (
    CredentialDecryptionFailed,
    InvalidCredentialKey,
    WebCredentialCipher,
    load_web_credential_key,
)


TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


class WebCredentialCipherTests(unittest.TestCase):
    def test_loads_exactly_32_byte_base64_key(self):
        key = load_web_credential_key(TEST_KEY)
        self.assertIsNotNone(key)
        self.assertEqual(key.version, 1)
        self.assertTrue(key.key_id)

        with self.assertRaises(InvalidCredentialKey):
            load_web_credential_key(base64.urlsafe_b64encode(b"short").decode("ascii"))

    def test_encrypt_round_trip_uses_random_nonce(self):
        cipher = WebCredentialCipher(load_web_credential_key(TEST_KEY))

        first = cipher.encrypt(7, "openai-compatible", "secret-value")
        second = cipher.encrypt(7, "openai-compatible", "secret-value")

        self.assertNotEqual(first.nonce, second.nonce)
        self.assertNotEqual(first.ciphertext, second.ciphertext)
        self.assertEqual(
            cipher.decrypt(7, "openai-compatible", first),
            "secret-value",
        )

    def test_ciphertext_cannot_move_between_users(self):
        cipher = WebCredentialCipher(load_web_credential_key(TEST_KEY))
        encrypted = cipher.encrypt(7, "openai-compatible", "secret-value")

        with self.assertRaises(CredentialDecryptionFailed):
            cipher.decrypt(8, "openai-compatible", encrypted)

    def test_tampering_fails_without_secret_in_error(self):
        cipher = WebCredentialCipher(load_web_credential_key(TEST_KEY))
        encrypted = cipher.encrypt(7, "openai-compatible", "SECRET_SENTINEL_web")
        tampered = encrypted.with_ciphertext(
            encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1])
        )

        with self.assertRaises(CredentialDecryptionFailed) as raised:
            cipher.decrypt(7, "openai-compatible", tampered)

        self.assertNotIn("SECRET_SENTINEL_web", str(raised.exception))
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_credentials -v
```

Expected: FAIL，原因是 `web_credentials.py` 尚不存在。

- [ ] **Step 3: 实现主密钥与 cipher**

在 `src/specgate/web_credentials.py` 定义：

```python
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, replace
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


WEB_PROVIDER = "openai-compatible"
WEB_KEY_VERSION = 1
MAX_CREDENTIAL_CHARS = 4096


class WebCredentialError(ValueError):
    code = "web_credential_error"


class InvalidCredentialKey(WebCredentialError):
    code = "invalid_credential_key"


class InvalidCredential(WebCredentialError):
    code = "invalid_credential"


class CredentialStoreUnavailable(WebCredentialError):
    code = "credential_store_unavailable"


class CredentialDecryptionFailed(WebCredentialError):
    code = "credential_decryption_failed"


class CredentialRequiresReentry(WebCredentialError):
    code = "credential_requires_reentry"


@dataclass(frozen=True)
class WebCredentialKey:
    value: bytes
    version: int
    key_id: str


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: bytes
    nonce: bytes
    key_version: int
    key_id: str

    def with_ciphertext(self, ciphertext: bytes) -> "EncryptedCredential":
        return replace(self, ciphertext=ciphertext)


def load_web_credential_key(raw: str | None) -> WebCredentialKey | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = base64.b64decode(
            raw.strip(),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise InvalidCredentialKey("invalid credential master key") from exc
    if len(value) != 32:
        raise InvalidCredentialKey("invalid credential master key")
    key_id = base64.urlsafe_b64encode(
        hashlib.sha256(value).digest()[:12]
    ).decode("ascii").rstrip("=")
    return WebCredentialKey(value, WEB_KEY_VERSION, key_id)


def _validate_secret(secret: str) -> str:
    normalized = secret.strip()
    if not normalized or len(normalized) > MAX_CREDENTIAL_CHARS:
        raise InvalidCredential("invalid credential")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise InvalidCredential("invalid credential")
    return normalized


class WebCredentialCipher:
    def __init__(self, key: WebCredentialKey):
        self.key = key
        self.aes = AESGCM(key.value)

    def _aad(self, user_id: int, provider: str) -> bytes:
        return (
            f"specgate:web:user:{user_id}:provider:{provider}:"
            f"v{self.key.version}:key:{self.key.key_id}"
        ).encode("utf-8")

    def encrypt(self, user_id: int, provider: str, secret: str) -> EncryptedCredential:
        plaintext = _validate_secret(secret).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self.aes.encrypt(nonce, plaintext, self._aad(user_id, provider))
        return EncryptedCredential(
            ciphertext,
            nonce,
            self.key.version,
            self.key.key_id,
        )

    def decrypt(
        self,
        user_id: int,
        provider: str,
        encrypted: EncryptedCredential,
    ) -> str:
        if (
            encrypted.key_version != self.key.version
            or encrypted.key_id != self.key.key_id
        ):
            raise CredentialRequiresReentry("credential requires re-entry")
        try:
            plaintext = self.aes.decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                self._aad(user_id, provider),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise CredentialDecryptionFailed(
                "credential could not be decrypted"
            ) from exc
```

- [ ] **Step 4: 运行 cipher 测试确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_credentials -v
```

Expected: PASS。

- [ ] **Step 5: 用户提交 Task 3**

建议提交信息：

```text
feat: 实现 Web AES-GCM 凭据加密核心
```

---

### Task 4: 增加数据库 version 2 与旧 HMAC 迁移

**Files:**
- Modify: `src/specgate/web_db.py`
- Modify: `tests/test_web_db.py`

- [ ] **Step 1: 写新库与旧库迁移 RED 测试**

在 `tests/test_web_db.py` 增加：

```python
def create_version_one_database(self, *, configured: bool) -> Path:
    tmp = tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    db_path = Path(tmp.name) / "web.sqlite3"
    configured_value = 1 if configured else 0
    ciphertext = "'hmac_sha256$legacy'" if configured else "null"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            f"""
            create table users (
                id integer primary key,
                username text,
                password_hash text
            );
            create table user_settings (
                user_id integer primary key,
                governance_profile text not null default 'review',
                context_strategy text not null default 'injection-safe',
                api_key_configured integer not null default 0,
                api_key_ciphertext text
            );
            insert into users values (1, 'alice', 'hash');
            insert into user_settings values (
                1, 'review', 'injection-safe',
                {configured_value}, {ciphertext}
            );
            pragma user_version = 1;
            """
        )
    return db_path


def test_new_database_uses_schema_version_two_and_credentials_table(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "web.sqlite3"

        init_db(db_path)

        with closing(sqlite3.connect(db_path)) as conn:
            version = conn.execute("pragma user_version").fetchone()[0]
            columns = self.table_columns(conn, "user_credentials")

        self.assertEqual(version, 2)
        self.assertGreaterEqual(
            set(columns),
            {
                "user_id",
                "provider",
                "status",
                "ciphertext",
                "nonce",
                "key_version",
                "key_id",
                "updated_at",
            },
        )


def test_version_one_hmac_state_requires_reentry(self):
    db_path = self.create_version_one_database(configured=True)

    init_db(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        credential = conn.execute(
            "select * from user_credentials where user_id = 1"
        ).fetchone()
        legacy = conn.execute(
            """
            select api_key_configured, api_key_ciphertext
            from user_settings where user_id = 1
            """
        ).fetchone()
        version = conn.execute("pragma user_version").fetchone()[0]

    self.assertEqual(version, 2)
    self.assertEqual(credential[2], "requires_reentry")
    self.assertIsNone(credential[3])
    self.assertEqual(legacy, (0, None))


def test_newer_database_version_fails_closed(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "web.sqlite3"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("pragma user_version = 99")

        with self.assertRaisesRegex(RuntimeError, "newer schema"):
            init_db(db_path)
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_db -v
```

Expected: FAIL，当前 schema version 为 1，且没有 `user_credentials`。

- [ ] **Step 3: 定义 version 2 schema**

在 `src/specgate/web_db.py`：

```python
LATEST_SCHEMA_VERSION = 2

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
```

把新表加入 fresh database `SCHEMA`，并把末尾改为：

```sql
pragma user_version = 2;
```

- [ ] **Step 4: 实现显式迁移**

实现以下迁移入口：

```python
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
            return
        if version == LATEST_SCHEMA_VERSION:
            conn.execute(USER_CREDENTIALS_SCHEMA)
            conn.commit()
            return
        if version > LATEST_SCHEMA_VERSION:
            raise RuntimeError("database uses a newer schema version")
        raise RuntimeError("unsupported database schema version")
    finally:
        conn.close()
```

- [ ] **Step 5: 增加迁移幂等与失败回滚测试**

在 `tests/test_web_db.py` 增加：

```python
def test_version_one_migration_is_idempotent(self):
    db_path = self.create_version_one_database(configured=True)

    init_db(db_path)
    init_db(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        version = conn.execute("pragma user_version").fetchone()[0]
        count = conn.execute(
            "select count(*) from user_credentials"
        ).fetchone()[0]
    self.assertEqual(version, 2)
    self.assertEqual(count, 1)


def test_version_one_migration_rolls_back_on_schema_error(self):
    db_path = self.create_version_one_database(configured=True)

    with patch(
        "specgate.web_db.USER_CREDENTIALS_SCHEMA",
        "create table broken(",
    ):
        with self.assertRaises(sqlite3.OperationalError):
            init_db(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        version = conn.execute("pragma user_version").fetchone()[0]
        legacy = conn.execute(
            """
            select api_key_configured, api_key_ciphertext
            from user_settings
            """
        ).fetchone()
        table = conn.execute(
            """
            select name from sqlite_master
            where type = 'table' and name = 'user_credentials'
            """
        ).fetchone()
    self.assertEqual(version, 1)
    self.assertEqual(legacy, (1, "hmac_sha256$legacy"))
    self.assertIsNone(table)
```

测试文件补充 `from unittest.mock import patch`。

- [ ] **Step 6: 运行数据库测试确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_db -v
```

Expected: PASS。

- [ ] **Step 7: 用户提交 Task 4**

建议提交信息：

```text
feat: 增加 Web 凭据数据库迁移
```

---

### Task 5: 实现 Web 凭据 repository 并接入 Settings

**Files:**
- Modify: `src/specgate/web_credentials.py`
- Modify: `src/specgate/web_settings.py`
- Modify: `src/specgate/web_runs.py`
- Modify: `tests/test_web_credentials.py`
- Modify: `tests/test_web_settings.py`
- Modify: `tests/test_web_runs.py`

- [ ] **Step 1: 写加密存储与状态 RED 测试**

在 `tests/test_web_credentials.py` 的测试类中增加以下 helper 和测试，并导入 `tempfile`、`Path`、`closing`、`create_user`、`connect_db` 与 `init_db`：

```python
def make_database_user(self):
    tmp = tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    db_path = Path(tmp.name) / "web.sqlite3"
    init_db(db_path)
    user = create_user(db_path, "alice", "correct-password")
    return db_path, int(user["id"])


def test_service_stores_ciphertext_and_round_trips(self):
    db_path, user_id = self.make_database_user()
    service = WebCredentialService.from_key_value(db_path, TEST_KEY)
    secret = "SECRET_SENTINEL_database"

    status = service.put(user_id, secret)

    self.assertTrue(status.configured)
    self.assertEqual(status.storage, "encrypted")
    self.assertEqual(service.get(user_id), secret)
    with closing(connect_db(db_path)) as conn:
        row = conn.execute(
            """
            select ciphertext, nonce, key_version, key_id
            from user_credentials
            where user_id = ? and provider = 'openai-compatible'
            """,
            (user_id,),
        ).fetchone()
    self.assertNotIn(secret.encode("utf-8"), row["ciphertext"])
    self.assertEqual(len(row["nonce"]), 12)


def test_changed_master_key_requires_reentry_without_decrypting(self):
    db_path, user_id = self.make_database_user()
    first = WebCredentialService.from_key_value(db_path, TEST_KEY)
    second_key = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii")
    second = WebCredentialService.from_key_value(db_path, second_key)
    first.put(user_id, "secret-value")

    status = second.status(user_id)

    self.assertFalse(status.configured)
    self.assertTrue(status.requires_reentry)
    self.assertEqual(status.storage, "requires_reentry")
    with self.assertRaises(CredentialRequiresReentry):
        second.get(user_id)


def test_missing_key_blocks_put_but_allows_clear(self):
    db_path, user_id = self.make_database_user()
    configured = WebCredentialService.from_key_value(db_path, TEST_KEY)
    unavailable = WebCredentialService.from_key_value(db_path, None)
    configured.put(user_id, "secret-value")

    with self.assertRaises(CredentialStoreUnavailable):
        unavailable.put(user_id, "replacement")

    unavailable.clear(user_id)
    status = unavailable.status(user_id)
    self.assertEqual(status.storage, "not_stored")
    self.assertFalse(status.store_available)
```

- [ ] **Step 2: 写 Settings 状态 RED 测试**

更新 `tests/test_web_settings.py`，删除 HMAC 断言，增加：

```python
def test_settings_exposes_encrypted_credential_status(self):
    db_path, user_id = self.make_user()
    service = WebCredentialService.from_key_value(db_path, TEST_KEY)

    settings = upsert_api_key(db_path, user_id, "secret-value", service)

    self.assertTrue(settings["api_key_configured"])
    self.assertEqual(settings["api_key_storage"], "encrypted")
    self.assertFalse(settings["api_key_requires_reentry"])
    self.assertTrue(settings["credential_store_available"])
    self.assertEqual(settings["llm_mode"], "mock")
    self.assertNotIn("secret-value", repr(settings))


def test_legacy_status_is_requires_reentry(self):
    db_path, user_id = self.make_user()
    with closing(connect_db(db_path)) as conn:
        conn.execute(
            """
            insert into user_credentials (
                user_id, provider, status
            )
            values (?, 'openai-compatible', 'requires_reentry')
            """,
            (user_id,),
        )
        conn.commit()
    service = WebCredentialService.from_key_value(db_path, TEST_KEY)

    settings = get_settings(db_path, user_id, service)

    self.assertFalse(settings["api_key_configured"])
    self.assertEqual(settings["api_key_storage"], "requires_reentry")
    self.assertTrue(settings["api_key_requires_reentry"])
```

- [ ] **Step 3: 运行测试确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_credentials tests.test_web_settings -v
```

Expected: FAIL，`WebCredentialService` 和新 Settings 字段尚不存在。

- [ ] **Step 4: 实现 WebCredentialService**

在 `src/specgate/web_credentials.py` 增加以下导入和实现：

```python
from pathlib import Path

from specgate.web_db import connect_db


@dataclass(frozen=True)
class WebCredentialStatus:
    configured: bool
    storage: str
    requires_reentry: bool
    store_available: bool


class WebCredentialService:
    def __init__(
        self,
        db_path: Path,
        cipher: WebCredentialCipher | None,
        unavailable_code: str | None = None,
    ):
        self.db_path = db_path
        self.cipher = cipher
        self.unavailable_code = unavailable_code

    @classmethod
    def from_key_value(
        cls,
        db_path: Path,
        raw_key: str | None,
    ) -> "WebCredentialService":
        try:
            key = load_web_credential_key(raw_key)
        except InvalidCredentialKey:
            return cls(db_path, None, "invalid_credential_key")
        if key is None:
            return cls(db_path, None, "credential_store_unavailable")
        return cls(db_path, WebCredentialCipher(key))

    def status(self, user_id: int) -> WebCredentialStatus:
        row = self._load(user_id)
        if row is None:
            return WebCredentialStatus(
                False,
                "not_stored",
                False,
                self.cipher is not None,
            )
        if row is not None and row["status"] == "requires_reentry":
            return WebCredentialStatus(False, "requires_reentry", True, self.cipher is not None)
        if row is not None and self.cipher is not None:
            if (
                row["key_version"] != self.cipher.key.version
                or row["key_id"] != self.cipher.key.key_id
            ):
                return WebCredentialStatus(False, "requires_reentry", True, True)
            return WebCredentialStatus(True, "encrypted", False, True)
        if row is not None and self.cipher is None:
            return WebCredentialStatus(False, "unavailable", False, False)
        raise RuntimeError("unreachable credential status")

    def _require_cipher(self) -> WebCredentialCipher:
        if self.cipher is not None:
            return self.cipher
        if self.unavailable_code == "invalid_credential_key":
            raise InvalidCredentialKey("invalid credential master key")
        raise CredentialStoreUnavailable("credential store is unavailable")

    def put(self, user_id: int, secret: str) -> WebCredentialStatus:
        cipher = self._require_cipher()
        encrypted = cipher.encrypt(user_id, WEB_PROVIDER, secret)
        conn = connect_db(self.db_path)
        try:
            conn.execute(
                """
                insert into user_credentials (
                    user_id, provider, status, ciphertext, nonce,
                    key_version, key_id, updated_at
                )
                values (?, ?, 'configured', ?, ?, ?, ?, current_timestamp)
                on conflict(user_id, provider) do update set
                    status = 'configured',
                    ciphertext = excluded.ciphertext,
                    nonce = excluded.nonce,
                    key_version = excluded.key_version,
                    key_id = excluded.key_id,
                    updated_at = current_timestamp
                """,
                (
                    user_id,
                    WEB_PROVIDER,
                    encrypted.ciphertext,
                    encrypted.nonce,
                    encrypted.key_version,
                    encrypted.key_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.status(user_id)

    def get(self, user_id: int) -> str | None:
        row = self._load(user_id)
        if row is None:
            return None
        if row["status"] == "requires_reentry":
            raise CredentialRequiresReentry("credential requires re-entry")
        cipher = self._require_cipher()
        if (
            row["key_version"] != cipher.key.version
            or row["key_id"] != cipher.key.key_id
        ):
            raise CredentialRequiresReentry("credential requires re-entry")
        encrypted = EncryptedCredential(
            row["ciphertext"],
            row["nonce"],
            row["key_version"],
            row["key_id"],
        )
        return cipher.decrypt(user_id, WEB_PROVIDER, encrypted)

    def _load(self, user_id: int):
        conn = connect_db(self.db_path)
        try:
            return conn.execute(
                """
                select * from user_credentials
                where user_id = ? and provider = ?
                """,
                (user_id, WEB_PROVIDER),
            ).fetchone()
        finally:
            conn.close()

    def clear(self, user_id: int) -> WebCredentialStatus:
        conn = connect_db(self.db_path)
        try:
            conn.execute(
                """
                delete from user_credentials
                where user_id = ? and provider = ?
                """,
                (user_id, WEB_PROVIDER),
            )
            conn.commit()
        finally:
            conn.close()
        return self.status(user_id)
```

- [ ] **Step 5: 重构 Web Settings**

将 `web_settings.py` 的 HMAC、Base64 和旧字段读取全部删除。公开接口改为：

```python
def get_runtime_settings(db_path: Path, user_id: int) -> dict:
    conn = connect_db(db_path)
    try:
        _ensure_settings(conn, user_id)
        conn.commit()
        row = conn.execute(
            """
            select governance_profile, context_strategy
            from user_settings where user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("settings not found")
        return {
            "governance_profile": row["governance_profile"],
            "context_strategy": row["context_strategy"],
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
    credentials: WebCredentialService,
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
    finally:
        conn.close()
    return get_settings(db_path, user_id, credentials)
```

- [ ] **Step 6: 隔离后台 run 与凭据状态**

在 `src/specgate/web_runs.py`：

```python
from specgate.web_settings import get_runtime_settings
```

把 execute/resume 路径中的 `get_settings(db_path, user_id)` 改为：

```python
settings = get_runtime_settings(db_path, user_id)
```

测试应 patch `get_runtime_settings` 并断言返回值中没有 API key、ciphertext 或 credential service。

- [ ] **Step 7: 运行聚焦测试确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_credentials tests.test_web_settings tests.test_web_runs -v
```

Expected: PASS。

- [ ] **Step 8: 用户提交 Task 5**

建议提交信息：

```text
feat: 接入 Web 加密凭据 repository
```

---

### Task 6: 接通 Web API 和前端安全状态

**Files:**
- Modify: `src/specgate/web_app.py`
- Modify: `src/specgate/web_static/app.js`
- Modify: `tests/test_web_app.py`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1: 写 API 缺失主密钥和安全存储 RED 测试**

在 `tests/test_web_app.py` 增加：

```python
def test_api_key_put_requires_configured_credential_store(self):
    client, _app = self.make_client(credential_key=None)
    self.register(client)

    response = client.put(
        "/api/settings/api-key",
        json={"api_key": "SECRET_SENTINEL_missing_key"},
    )

    self.assertEqual(response.status_code, 503)
    self.assertEqual(
        response.json()["detail"]["code"],
        "credential_store_unavailable",
    )
    self.assertNotIn("SECRET_SENTINEL_missing_key", response.text)


def test_api_key_is_encrypted_and_never_returned(self):
    client, app = self.make_client(credential_key=TEST_KEY)
    self.register(client)
    db_path = app.state.db_path
    secret = "SECRET_SENTINEL_api"

    response = client.put(
        "/api/settings/api-key",
        json={"api_key": secret},
    )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(
        response.json()["settings"]["api_key_storage"],
        "encrypted",
    )
    self.assertNotIn(secret, response.text)
    with closing(connect_db(db_path)) as conn:
        row = conn.execute(
            "select ciphertext from user_credentials"
        ).fetchone()
    self.assertNotIn(secret.encode("utf-8"), row["ciphertext"])


def test_delete_works_without_master_key(self):
    client, app = self.make_client(credential_key=TEST_KEY)
    registered = self.register(client)
    user_id = int(registered["user"]["id"])
    stored = client.put(
        "/api/settings/api-key",
        json={"api_key": "secret-value"},
    )
    self.assertEqual(stored.status_code, 200, stored.text)
    app.state.web_credentials = WebCredentialService.from_key_value(
        app.state.db_path,
        None,
    )

    response = client.delete("/api/settings/api-key")

    self.assertEqual(response.status_code, 200)
    self.assertFalse(response.json()["settings"]["api_key_configured"])
    self.assertEqual(response.json()["settings"]["api_key_storage"], "not_stored")
    with closing(connect_db(app.state.db_path)) as conn:
        count = conn.execute(
            "select count(*) from user_credentials where user_id = ?",
            (user_id,),
        ).fetchone()[0]
    self.assertEqual(count, 0)
```

测试文件导入 `base64`、`WebCredentialService`，并定义：

```python
TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
```

- [ ] **Step 2: 写前端状态 RED 测试**

在 `tests/test_web_static.py` 增加：

```python
def test_settings_renders_secure_credential_states(self):
    self.assertIn("api_key_requires_reentry", self.app_js)
    self.assertIn("credential_store_available", self.app_js)
    self.assertIn("需要重新录入", self.app_js)
    self.assertIn("安全存储不可用", self.app_js)
    self.assertIn("已加密存储", self.app_js)
```

- [ ] **Step 3: 运行测试确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_app tests.test_web_static -v
```

Expected: FAIL，`create_app` 尚未初始化 service，API 仍使用 HMAC secret。

- [ ] **Step 4: 初始化 WebCredentialService**

修改 `create_app` 签名：

```python
def create_app(
    data_root: Path | None = None,
    db_path: Path | None = None,
    secure_cookies: bool | None = None,
    credential_key: str | None = None,
) -> FastAPI:
```

数据库初始化完成后：

```python
raw_credential_key = (
    credential_key
    if credential_key is not None
    else os.environ.get("SPECGATE_WEB_CREDENTIAL_KEY")
)
app.state.web_credentials = WebCredentialService.from_key_value(
    resolved_db_path,
    raw_credential_key,
)
```

删除 `app.state.api_key_encryption_secret`，并删除 `SPECGATE_WEB_SECRET`、`SPECGATE_WEB_API_KEY_SECRET` 作为 API key HMAC 输入的 fallback。凭据模块只读取 `SPECGATE_WEB_CREDENTIAL_KEY`。

- [ ] **Step 5: 接通 Settings endpoints**

```python
@app.get("/api/settings")
def read_settings(user=Depends(current_user)) -> dict[str, Any]:
    return {
        "settings": get_settings(
            app.state.db_path,
            int(user["id"]),
            app.state.web_credentials,
        )
    }


@app.put("/api/settings")
def put_settings(payload: SettingsRequest, user=Depends(current_user)) -> dict[str, Any]:
    try:
        settings = update_settings(
            app.state.db_path,
            int(user["id"]),
            payload.governance_profile,
            payload.context_strategy,
            app.state.web_credentials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"settings": settings}


@app.put("/api/settings/api-key")
def put_api_key(payload: ApiKeyRequest, user=Depends(current_user)) -> dict[str, Any]:
    try:
        settings = upsert_api_key(
            app.state.db_path,
            int(user["id"]),
            payload.api_key,
            app.state.web_credentials,
        )
    except WebCredentialError as exc:
        raise _http_error_for_credential_error(exc) from exc
    return {"settings": settings}


@app.delete("/api/settings/api-key")
def delete_api_key(user=Depends(current_user)) -> dict[str, Any]:
    try:
        settings = clear_api_key(
            app.state.db_path,
            int(user["id"]),
            app.state.web_credentials,
        )
    except WebCredentialError as exc:
        raise _http_error_for_credential_error(exc) from exc
    return {"settings": settings}
```

扩展错误映射：

```python
def _http_error_for_credential_error(exc: WebCredentialError) -> HTTPException:
    status_by_code = {
        "invalid_credential": 400,
        "credential_requires_reentry": 409,
        "credential_store_unavailable": 503,
        "invalid_credential_key": 503,
        "credential_decryption_failed": 500,
    }
    code = exc.code
    return HTTPException(
        status_code=status_by_code.get(code, 500),
        detail={
            "code": code,
            "message": "安全凭据操作失败 / Secure credential operation failed",
        },
    )
```

端点只捕获 `WebCredentialError`，不得把包含用户输入的任意 `ValueError` 原样返回。

- [ ] **Step 6: 更新前端状态文本**

在 `app.js` 增加：

```javascript
function credentialStateLabel(settings) {
  if (settings.api_key_requires_reentry) {
    return "API Key：需要重新录入";
  }
  if (!settings.credential_store_available) {
    return "API Key：安全存储不可用";
  }
  if (settings.api_key_configured && settings.api_key_storage === "encrypted") {
    return "API Key：已加密存储";
  }
  return "API Key：未配置";
}
```

`loadSettings`、保存成功和清除成功后的状态文本统一改为：

```javascript
setText("settings-api-state", credentialStateLabel(state.settings));
```

Settings 汇总行中的 API Key 值也调用 `credentialStateLabel(settings)`，不再只根据 `api_key_configured` 二选一。页面不得渲染 ciphertext、nonce、key id 或异常详情。

- [ ] **Step 7: 运行 Web API 与静态测试确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_settings tests.test_web_app tests.test_web_static -v
```

Expected: PASS。

- [ ] **Step 8: 用户提交 Task 6**

建议提交信息：

```text
feat: 接通 Web 安全凭据状态与 API
```

---

### Task 7: 补齐脱敏回归和中文文档

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_web_app.py`
- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: 增加端到端 secret sentinel 回归**

CLI 测试必须捕获 stdout/stderr 和异常，断言：

```python
self.assertNotIn(secret, stdout.getvalue())
self.assertNotIn(secret, stderr.getvalue())
self.assertNotIn(secret, repr(raised.exception))
```

Web 测试必须断言：

```python
self.assertNotIn(secret, response.text)
self.assertNotIn(secret, repr(response.json()))
self.assertNotIn(secret, trace_path.read_text(encoding="utf-8"))
```

数据库测试只允许 secret 存在于测试进程内存；`user_credentials` 之外的表和所有文本列都不得包含 sentinel。

- [ ] **Step 2: 运行脱敏测试并确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_credentials tests.test_cli tests.test_web_credentials tests.test_web_app -v
```

Expected: PASS。

- [ ] **Step 3: 更新 README CLI 凭据说明**

README 必须包含以下准确说明：

- MockLLM 不需要凭据。
- `credentials set/status/clear` 使用系统 keyring。
- 进程环境变量具有最高优先级，适合 CI 或临时运行。
- SpecGate 不再读写 `.env`。
- Linux/Docker 没有 keyring backend 时使用进程环境变量，不回退到明文文件。
- Web 保存的凭据仍不会启用真实 LLM。

示例命令：

```powershell
python -m specgate.cli credentials set openai-compatible
python -m specgate.cli credentials status openai-compatible
$env:OPENAI_COMPATIBLE_API_KEY="<临时凭据>"
```

- [ ] **Step 4: 更新部署文档**

`docs/DEPLOYMENT.md` 增加：

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
  $rng.GetBytes($bytes)
} finally {
  $rng.Dispose()
}
[Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
```

说明把输出设置为 `SPECGATE_WEB_CREDENTIAL_KEY`，并明确：

- 主密钥不提交到 Git。
- 主密钥与 SQLite 备份分开保存。
- 更换或丢失主密钥后旧 API key 需要重新录入。
- 本阶段 Web 仍只运行 MockLLM。

- [ ] **Step 5: 更新计划和执行日志**

`PLAN.md` 追加本阶段链接、任务状态和待用户填写的 commit/PR/CI 字段。`AGENT_LOG.md` 记录：

- 已确认的安全架构。
- TDD RED/GREEN 命令。
- 数据库迁移结果。
- 全量测试和 CI 结果。
- Agent 未执行 Git 写操作。

- [ ] **Step 6: 用户提交 Task 7**

建议提交信息：

```text
docs: 更新安全凭据使用与部署说明
```

---

### Task 8: 完整验证与交付审查

**Files:**
- Verify: `src/specgate/credential_store.py`
- Verify: `src/specgate/credentials.py`
- Verify: `src/specgate/web_credentials.py`
- Verify: `src/specgate/web_db.py`
- Verify: `src/specgate/web_settings.py`
- Verify: `src/specgate/web_app.py`
- Verify: `src/specgate/web_runs.py`
- Verify: `src/specgate/cli.py`
- Verify: `README.md`
- Verify: `docs/DEPLOYMENT.md`

- [ ] **Step 1: 运行全部凭据与 Web 聚焦测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_credential_store tests.test_credentials tests.test_cli tests.test_web_credentials tests.test_web_db tests.test_web_settings tests.test_web_app tests.test_web_runs tests.test_web_static -v
```

Expected: 0 failures，0 errors；只允许既有平台权限类 skip。

- [ ] **Step 2: 运行完整测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

Expected: `OK`，0 failures，0 errors。

- [ ] **Step 3: 运行语法和差异检查**

Run:

```powershell
python -m compileall -q src tests
git diff --check
```

Expected: 两条命令 exit code 均为 0。

- [ ] **Step 4: 扫描旧 .env 接口和 HMAC 占位**

Run:

```powershell
rg -n -- "--env-file|credential_status_from_env|hmac_sha256\\$|api_key_encryption_secret" src tests README.md docs/DEPLOYMENT.md
```

Expected: 生产代码无匹配；迁移测试可以包含 `hmac_sha256$legacy`，文档只能在历史说明中提及旧方案。

- [ ] **Step 5: 扫描敏感输出模式**

Run:

```powershell
git diff -U0 -- src README.md docs/DEPLOYMENT.md | rg -n "sk-[A-Za-z0-9]|OPENAI_API_KEY=.+|OPENAI_COMPATIBLE_API_KEY=.+"
```

Expected: 无真实或示例硬编码 secret；环境变量文档只使用 `<临时凭据>` 占位。

- [ ] **Step 6: 人工 smoke 系统 keyring**

仅在用户本机执行，不作为 CI 前提：

```powershell
python -m specgate.cli credentials set openai-compatible
python -m specgate.cli credentials status openai-compatible
python -m specgate.cli credentials clear openai-compatible
```

Expected: secret 不回显；status 显示来源为 system keyring；clear 后没有 keyring 凭据。

- [ ] **Step 7: 用户执行最终 Git 与 PR**

建议提交信息：

```text
feat: 实现安全凭据存储
```

建议 PR 标题：

```text
feat: 实现 CLI keyring 与 Web 加密凭据存储
```

用户负责 push、PR 和 Ubuntu CI，并把 commit、PR、CI 结果回填到 `PLAN.md` 与 `AGENT_LOG.md`。

---

## 最终评审清单

- [ ] CLI 不再读取或写入 `.env`。
- [ ] 环境变量优先于 keyring，且 clear 不修改环境变量。
- [ ] keyring 不可用时失败关闭，不回退到明文文件。
- [ ] Web 主密钥与 `SPECGATE_WEB_SECRET` 分离。
- [ ] Web API key 使用 AES-256-GCM 与随机 nonce。
- [ ] AAD 绑定 user id、provider、key version 和 key id。
- [ ] 数据库不包含 API key 明文。
- [ ] 旧 HMAC 记录迁移为 `requires_reentry`。
- [ ] 更换主密钥后旧记录要求重新录入。
- [ ] 主密钥缺失时 MockLLM 和非凭据 Web 功能正常。
- [ ] DELETE 不依赖主密钥。
- [ ] 响应、异常、日志和 Trace 不泄漏 secret。
- [ ] Web Runner 未读取或使用凭据。
- [ ] 全量测试和 Ubuntu CI 通过。
- [ ] README、部署文档、PLAN 和 AGENT_LOG 与行为一致。

---

### 合并后热修复：补齐 GitHub Pages 依赖安装

**根因：** `pages.yml` 在全新 Ubuntu runner 中直接导入 `specgate.cli`，但没有像 CI 与 Docker 一样执行 `python -m pip install -e .`，因此新增的 `keyring` 依赖不可用。

**Files:**
- Create: `tests/test_workflows.py`
- Modify: `.github/workflows/pages.yml`

- [x] **Step 1: 写 Pages workflow 顺序 RED 测试**

测试读取 `.github/workflows/pages.yml`，断言 `python -m pip install -e .` 存在，且位于 `run-mock-demo` 之前。

- [x] **Step 2: 运行测试确认 RED**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_workflows -v
```

Expected: FAIL，提示 Pages workflow 缺少依赖安装命令。

- [x] **Step 3: 增加安装步骤**

在 `Set up Python` 与 `Regenerate mock demo` 之间加入：

```yaml
      - name: Install package dependencies
        run: python -m pip install -e .
```

- [x] **Step 4: 运行聚焦与全量测试**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_workflows -v
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

Expected: 全部通过；GitHub Pages 在下一次合并到 `main` 后重新生成并部署静态站点。
