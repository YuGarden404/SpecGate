# SpecGate 安全凭据存储设计

日期：2026-07-14

## 1. 背景

当前 CLI 在 `src/specgate/credentials.py` 中读取和写入明文 `.env`。Web 在 `src/specgate/web_settings.py` 中只保存 API key 的 HMAC 摘要，无法恢复原值，因此它只是“已配置”状态占位，不是真正可用的安全凭据存储。

本阶段需要替换这两种实现，但仍保持 MockLLM 为唯一 Web 和自动验收运行模式。安全凭据模块只提供可验证的存储基础设施，不把真实 LLM、网络请求或模型配置引入本 PR。

## 2. 已确认决策

- 允许增加 `keyring` 和 `cryptography` 依赖。
- CLI 保留进程环境变量作为只读、最高优先级来源。
- CLI 的日常持久化改用操作系统 keyring，彻底移除 `.env` 读写。
- Web 使用 AES-256-GCM 加密后存入 SQLite。
- Web 主密钥使用独立环境变量，不复用 `SPECGATE_WEB_SECRET`。
- 旧 HMAC 记录迁移为 `requires_reentry`。
- 本阶段不实现在线主密钥轮换，更换密钥后要求重新录入。
- Web 本阶段只保存 `openai-compatible` 凭据。
- Web 和 CLI 的核心测试继续使用 MockLLM，不调用真实 LLM。

## 3. 目标

- 为 CLI 提供环境变量与系统 keyring 组合的统一凭据解析接口。
- 为 Web 提供多用户隔离、带认证的可逆加密存储。
- 让所有凭据状态、错误和迁移结果可确定性测试。
- 保证响应、日志、Trace、异常和数据库诊断不泄漏敏感值。
- 主密钥缺失时保持 MockLLM 与其他 Web 功能可用，同时让凭据写入失败关闭。

## 4. 非目标

- 不启用真实 LLM。
- 不把 Web API key 传给 Runner 或 LLMClient。
- 不实现主密钥在线轮换或双密钥迁移。
- 不在 WebUI 增加 provider 下拉框。
- 不实现团队共享凭据、云 KMS、Vault 或硬件安全模块。
- 不承诺抵御已经控制 SpecGate 进程、主机账户或浏览器会话的攻击者。

## 5. 威胁模型

本阶段主要防护静态存储泄漏：

- 只得到 SQLite 文件的攻击者不能恢复 Web API key。
- 只得到仓库或工作区文件的攻击者不能得到 CLI API key。
- 不同 Web 用户之间不能通过替换数据库行复用密文。
- 修改 ciphertext、nonce、AAD 或认证标签必须导致解密失败。
- 日志、错误和状态接口不能泄漏 API key、密文、nonce 或主密钥。

以下情况不在本阶段防护范围：

- 攻击者同时控制 Web 进程和主密钥环境变量。
- 攻击者已经取得操作系统用户账户或 keyring 解锁权限。
- 浏览器会话已经被接管。

## 6. 模块结构

### 6.1 `src/specgate/credential_store.py`

定义通用存储协议、稳定错误和 keyring 后端：

```python
class CredentialStoreError(ValueError):
    code = "credential_store_error"


class CredentialStoreUnavailable(CredentialStoreError):
    code = "credential_store_unavailable"


class CredentialStore(Protocol):
    def get(self, provider: str) -> str | None: ...
    def set(self, provider: str, secret: str) -> None: ...
    def clear(self, provider: str) -> None: ...
```

`KeyringCredentialStore` 使用可注入 backend，避免单元测试访问真实 Windows Credential Manager 或 Linux Secret Service。

keyring 标识固定为：

```text
service = specgate
username = provider
```

### 6.2 `src/specgate/credentials.py`

作为 CLI facade，负责：

- provider 校验。
- 凭据格式与长度校验。
- 环境变量优先级。
- keyring store 调用。
- 返回不含敏感值的 `CredentialStatus`。

解析顺序固定为：

```text
进程环境变量 -> 系统 keyring -> 未配置
```

环境变量存在时，`status/get` 使用环境变量。`set/clear` 只修改 keyring，不尝试修改外部环境变量。

如果环境变量当前存在：

- `set` 仍把新值保存到 keyring，但 `status/get` 在该进程内继续使用环境变量，并明确显示来源为 environment。
- `clear` 只删除 keyring 记录；若环境变量仍存在，状态仍是已配置，并提示环境变量没有被命令修改。

这样可以避免用户误以为 `clear` 能修改父进程或 CI 注入的环境变量。

### 6.3 `src/specgate/web_credentials.py`

负责：

- Web 主密钥解析与状态。
- AES-GCM 加密、解密和 AAD 构造。
- `user_credentials` 表的读取、写入和清除。
- 旧记录与主密钥变更后的 `requires_reentry` 状态。

`web_settings.py` 不再直接实现加密算法，只调用此模块并把安全状态映射到 API。

## 7. CLI 行为

### 7.1 命令

保留：

```text
specgate credentials status <provider>
specgate credentials set <provider>
specgate credentials clear <provider>
```

删除 credentials、run 和 real eval 路径中的 `--env-file` 参数。`credentials set --value` 可以保留用于自动化，但帮助文本必须提示命令行历史风险；交互模式继续使用 `getpass`。

### 7.2 环境变量

继续支持现有只读映射：

- `OPENAI_API_KEY`
- `OPENAI_COMPATIBLE_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`

环境变量适合 CI 或临时进程，不由 SpecGate 写入。

### 7.3 keyring 不可用

当 keyring 没有可用 backend、被锁定或拒绝访问时：

- `set/clear` 返回 `credential_store_unavailable`。
- `status` 在没有环境变量时返回不可用状态和非零退出码。
- `run/eval` 在没有环境变量时失败关闭，不创建 Runner 或 Trace。
- 不回退到 `.env` 或其他明文文件。

## 8. Web 主密钥

新增环境变量：

```text
SPECGATE_WEB_CREDENTIAL_KEY
```

格式必须是 URL-safe Base64 编码的 32 字节随机值。生成示例由文档给出，不在应用中自动生成，避免重启后使用新随机密钥导致旧密文不可读。

主密钥解析产生：

- `key_bytes`：AES-256-GCM 使用的 32 字节密钥。
- `key_version`：本阶段固定为 `1`。
- `key_id`：`SHA-256(key_bytes)` 的截断、Base64 编码非秘密标识，用于检测部署者更换了密钥。

`key_id` 不能用于恢复主密钥。数据库记录的 `key_id` 与当前主密钥不一致时，状态映射为 `requires_reentry`，不尝试用错误密钥解密。

主密钥缺失或格式错误时应用仍可启动，MockLLM、项目、审批、产物和审计继续工作。保存或内部读取凭据失败关闭；清除凭据不需要主密钥，仍可执行。

## 9. AES-GCM 格式

每次保存执行：

1. 验证 API key 非空、长度不超过 4096 个字符且不包含控制字符。
2. 使用 `os.urandom(12)` 生成 nonce。
3. 构造 AAD：

```text
specgate:web:user:<user_id>:provider:openai-compatible:v<key_version>:key:<key_id>
```

4. 使用 `AESGCM.encrypt(nonce, plaintext, aad)` 得到带认证标签的 ciphertext。
5. 在一个 SQLite 事务内覆盖用户的 `openai-compatible` 凭据记录。

相同 API key 重复保存必须生成不同 nonce 和 ciphertext。

解密前先比较 provider、key version 和 key id。任何元数据不一致、密文篡改或认证失败都返回稳定错误，不暴露 `InvalidTag` 等底层异常细节。

## 10. 数据库 schema 与迁移

新增表：

```sql
create table user_credentials (
    user_id integer not null references users(id) on delete cascade,
    provider text not null,
    status text not null check (status in ('configured', 'requires_reentry')),
    ciphertext blob,
    nonce blob,
    key_version integer,
    key_id text,
    updated_at text not null default current_timestamp,
    primary key (user_id, provider)
);
```

数据库 `user_version` 从 1 升到 2。`init_db` 必须显式区分：

- version 0：创建最新 schema 并设置 version 2。
- version 1：在一个事务内创建 `user_credentials`、迁移旧状态并设置 version 2。
- version 2：只验证或补齐 `create table if not exists`，不得重复迁移。
- 大于 2：失败关闭，避免新数据库被旧程序静默修改。

version 1 迁移规则：

- `api_key_configured = 1` 或 `api_key_ciphertext is not null` 时，为该用户插入 `openai-compatible / requires_reentry`。
- 新记录的 ciphertext、nonce、key version 和 key id 均为 NULL。
- 清空旧 `api_key_configured` 和 `api_key_ciphertext`，防止旧字段继续表示可用凭据。
- 没有旧配置的用户不创建 `user_credentials` 行。

旧列保留以避免 SQLite 复杂表重建，但 version 2 代码不得再读取它们。

## 11. Web API

保留现有路由：

```text
GET    /api/settings
PUT    /api/settings/api-key
DELETE /api/settings/api-key
```

Web provider 固定为 `openai-compatible`。接口不返回明文、密文、nonce、AAD、key id 或主密钥状态细节。

Settings 增加或调整为：

```json
{
  "api_key_configured": true,
  "api_key_storage": "encrypted",
  "api_key_requires_reentry": false,
  "credential_store_available": true,
  "llm_mode": "mock"
}
```

`api_key_storage` 只允许：

- `not_stored`
- `encrypted`
- `requires_reentry`
- `unavailable`

DELETE 在主密钥缺失时仍删除对应数据库行并返回 `not_stored`。

## 12. 错误码与脱敏

稳定错误码：

- `credential_store_unavailable`
- `credential_decryption_failed`
- `invalid_credential_key`
- `invalid_credential`
- `credential_requires_reentry`

HTTP 映射：

- 用户输入非法：400。
- 旧记录需要重新录入：409。
- 主密钥或存储 backend 不可用：503。
- 密文损坏或认证失败：500，并只返回通用安全消息。

所有异常在进入 CLI、HTTP、日志或 Trace 前必须脱敏。测试应使用唯一 sentinel secret，断言它不出现在响应、异常文本、日志、Trace 和数据库非密文字段中。

## 13. 依赖

`pyproject.toml` 增加受约束版本：

- `keyring`
- `cryptography`

核心代码不得动态降级到自制加密算法。依赖缺失属于安装错误；keyring backend 缺失属于可处理的运行时不可用状态。

## 14. 测试策略

### 14.1 CLI 与 keyring

- 环境变量优先于 keyring。
- 环境变量缺失时读取 keyring。
- `set/clear/status` 不创建或修改 `.env`。
- keyring backend 通过内存 fake 注入，不访问开发机真实 keyring。
- backend 不可用、拒绝访问和未配置产生稳定状态。
- CLI 输出和错误不包含 secret。
- `run/eval` 在凭据缺失时仍在创建 Runner 前失败关闭。

### 14.2 Web 加密

- AES-GCM round trip。
- 相同明文产生不同密文。
- SQLite 不包含明文。
- 不同 user id、provider、key id 或 version 的 AAD 不能解密。
- nonce、ciphertext 或认证标签篡改后失败。
- 主密钥缺失或格式错误时凭据写入失败，但应用与 MockLLM 可用。
- 更换主密钥后旧记录显示 `requires_reentry`。
- 清除操作不依赖主密钥。

### 14.3 数据库迁移

- 新数据库直接创建 version 2。
- version 1 HMAC 记录迁移为 `requires_reentry`。
- version 1 未配置用户不产生凭据行。
- 重复运行 `init_db` 不重复或覆盖迁移结果。
- 高于当前版本的数据库失败关闭。

### 14.4 API 与回归

- Settings 只返回安全状态。
- PUT/DELETE 状态映射正确。
- 所有错误响应不泄漏 secret。
- Web run 继续固定使用 MockLLM，不读取 Web 凭据。
- 聚焦测试、全量测试、语法检查和差异检查通过。

建议验证命令：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_credentials tests.test_web_settings tests.test_web_db tests.test_web_app -v
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

## 15. 文档更新

- README 删除 CLI `.env` 持久化示例，改为 keyring 与环境变量说明。
- README 明确 Web 仍只运行 MockLLM。
- 部署文档增加 `SPECGATE_WEB_CREDENTIAL_KEY` 生成、配置和备份说明。
- 不在示例命令、截图或测试输出中出现真实 API key。
- `PLAN.md` 与 `AGENT_LOG.md` 记录设计、TDD 和验证证据。

## 16. 验收标准

- CLI 不再读写明文 `.env`。
- CLI 环境变量与 keyring 优先级符合设计。
- Web API key 以 AES-256-GCM 密文存储，数据库不含明文。
- 旧 HMAC 记录和主密钥变更都稳定显示 `requires_reentry`。
- 主密钥缺失不影响 MockLLM 和非凭据 Web 功能。
- 没有响应、日志、Trace 或异常泄漏敏感值。
- 本阶段没有真实 LLM 或网络调用。
- 全量测试与 Ubuntu CI 通过。
