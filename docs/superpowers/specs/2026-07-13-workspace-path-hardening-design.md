# Workspace 真实路径边界加固设计

日期：2026-07-13

## 1. 背景

当前 policy 只验证字符串路径是否绝对或包含 `..`，ToolDispatcher、Snapshot、Context Selector、
Retrieval、Gate 和 Web debug 随后直接执行 `root / relative_path`。符号链接、Windows junction 或
其他 reparse point 可让这些访问跟随到 workspace 外。部分 Web artifact 检查虽然使用 `resolve()`，
但“检查路径后再次打开”的模式仍存在祖先目录替换窗口。

## 2. 目标

- 所有 Harness 文件访问共享同一个安全路径与安全 I/O 模块。
- workspace 内完全禁止符号链接、junction 和 reparse point，包括指向 workspace 内部的链接。
- 读操作从同一个已验证文件描述符读取，避免校验后按路径重新打开。
- 写操作在写入内容前验证路径组件、父目录和已打开目标的真实位置。
- Snapshot、审批目标状态、上下文扫描、RAG、Gate、Web audit/artifact 和 run workspace 复制均不跟随链接。
- ZIP 导入拒绝链接型条目。
- 安全拒绝使用稳定 `rule_family`，可以进入 trace/report/benchmark。

## 3. 统一模块

新增 `src/specgate/workspace_fs.py`：

- `WorkspacePathError(message, rule_family)`
- `normalize_workspace_relative(value)`
- `is_link_like(path)`
- `open_workspace_file(root, relative, access, create=False)`
- `read_workspace_text/bytes`
- `write_workspace_text`
- `workspace_file_state`
- `iter_workspace_files`
- `copy_workspace_tree`

`normalize_workspace_relative` 拒绝空路径、绝对路径、驱动器路径、UNC、`.`、`..` 和反斜杠歧义。
`is_link_like` 同时检查 `is_symlink()`、可用时的 `is_junction()`、`lstat` 模式和
`FILE_ATTRIBUTE_REPARSE_POINT`。

## 4. 安全打开

POSIX 优先逐级使用已打开目录 fd 与 `dir_fd`/`O_NOFOLLOW` 解析路径，最终文件由同一 fd 读取或
写入。Windows 在打开前逐级拒绝 reparse point，打开后通过文件句柄获得最终规范路径并再次确认
位于预先解析的可信 root 内；内容写入只发生在句柄验证之后。

如果平台缺少某项底层能力，必须 fail closed 或使用保守回退，不能静默恢复为普通 `Path.open()`。
安全函数返回的文件对象/描述符由 context manager 负责关闭。

## 5. 安全扫描与复制

扫描使用 `os.scandir`，对每个目录项执行 `follow_symlinks=False` 检查；链接型对象作为 skipped
evidence 返回或抛出边界错误，绝不递归。`iter_workspace_files` 产出规范相对路径。

`copy_workspace_tree` 只复制经安全扫描得到的普通目录和普通文件，目标路径同样经安全创建逻辑。
run 初始化与 workspace 提升不再使用会跟随链接的普通 `shutil.copytree`。

## 6. 接入点

- `policy.py`：复用规范化函数，保持规则判断与真实 I/O 边界一致。
- `tools.py`：read/write/replace/list 全部使用安全 API；路径错误返回 blocked。
- `snapshot.py`：捕获、检查和更新通过安全 file state。
- `approvals.py`：审批目标摘要通过安全 file state，链接变化导致不匹配。
- `context_selector.py`、`retrieval.py`：安全扫描、同句柄读取，链接记录 skipped/dropped。
- `runner.py`/`gate.py`：Gate 读取 index/checklist 使用安全 API。
- `web_debug.py`、`web_app.py`：audit、evidence 与 artifact 通过统一安全打开，不保留局部重复实现。
- `run_storage.py`：初始化和提升使用安全复制。
- `web_projects.py`：ZIP 链接条目在提取前拒绝。

## 7. 错误与审计

稳定规则族：

- `invalid_path`
- `path_escape`
- `linked_path`
- `reparse_point`
- `unsafe_file_type`
- `path_race`

ToolResult 对这些错误设置 `blocked=True`。Context/RAG 对链接记录相对路径与规则族，不读取内容。
Web 下载统一返回 404，不向远程用户泄露真实服务器路径；内部 debug 只展示脱敏规则族。

## 8. 测试

- 文件链接、目录链接、内部链接、外部链接均被拒绝。
- Windows junction/reparse 通过真实能力或兼容 mock 覆盖，Python 3.11 不依赖 `Path.is_junction`。
- 缺失目标的链接父目录被拒绝。
- 校验与打开之间替换祖先目录时，POSIX dirfd/Windows final-handle 验证拒绝逃逸。
- Snapshot、approval state、context selector、RAG、Gate、debug 与 artifact 不跟随链接。
- run 初始化/提升遇到链接时失败且不污染项目 workspace。
- ZIP symlink 条目被拒绝。
- 全量测试通过。

## 9. 非目标

- 不提供链接白名单或“允许 workspace 内部链接”的兼容模式。
- 不实现操作系统级容器或用户命名空间沙箱。
- 不改变业务 policy 允许的 action/path 集合，仅加固真实文件系统边界。
