# Antigravity Bilibili 模块化控制实验

**离线候选里程碑，不是完整插件，也不是已部署的真实账号控制器。** 本目录以新增实验目录的形式保留原仓库代码，不替换旧 dot 浏览器适配器。

目标是让 agent 自主组合小而独立的工具，而不是把“搜索→打开→读标题”等固定流程包装成唯一入口。每个模块应有独立输入、结果、前置条件和可验证的关系契约。

## 当前状态分层

| 层 | 已有证据 | 不能据此宣称 |
|---|---|---|
| 原仓库 dot / 浏览器适配 | 原有代码保持不变；本目录不重新验收它 | 旧入口的能力数不是完整插件完成率 |
| `minimal_slice_vnext` | 4 个独立 fixture MCP 工具；真实 Antigravity CLI 宿主已发现并调用；重启保留 pause；最终 clean build 又验证了缓存 status | 不是真实 Bilibili 元数据、账号授权或通用部署 |
| `next_phase` | 国内 QR 响应解析、合成 marker 存储、账号 pause、身份票据/read lease、typed metadata；实际三模块离线组合已测试 | 假 cookie/opaque marker 不是可用凭据；未新增公开 MCP 登录工具 |
| `credential-store-candidate` | 独立 POSIX 明文文件端口；合成材料的跨进程恢复、完整 handle CAS、原子替换与权限边界通过 35 + 18 项测试 | 尚未接入 QR/session/metadata，也未保存或使用真实凭据；不是加密或永久云磁盘保证 |
| 真实 Bilibili | 此候选没有实时验收 | 未证明真实扫码/手机登录、当前 NAV/metadata、写操作或恢复成功 |

这些证据层不能互相替代：源码入库不等于部署，mock 测试不等于实网验收。新的可逆写功能必须另外留下“实际动作 + 恢复原状态”的证据，不能只验证回包或模拟回滚。

## 最小可用工具面

`minimal_slice_vnext.server` 提供：

- `capabilities.list`：列出本服务工具与 pause 状态。
- `video.reference.resolve`：验证显式 BVID / 规范视频 URL，产生进程内 reference；不搜索、不证明视频存在。
- `video.metadata.read`：显式 reference + expected BVID + operation ID 的一次 fixture 读取。仅 `BV17x411w7KC` 有明确合成数据；其他合法 ID 返回 `not_found`。
- `operation.status`：只读本地记录，不重放操作。

全部返回 `backend=fixture, live=false`。`_meta` 是协议元数据，不是授权；可省略的 `arguments` 不触发隐藏业务行为。暂停后新读取阻断，历史状态仍可观察；重启不解除暂停。

新三模块是独立 Python 组件，不是一个强制工作流：QR coordinator、session authority、metadata parser/adapter 可分别测试；`composition.py` 只是验证它们连接契约的可信合成 harness。身份未验、目标不符、未知 pause 等阻断新出站；`partial` 保留有效字段；`unknown` 不冒充拒绝，也不自动重试或将账号改成过期。

## 本地运行

使用 Python 标准库；本轮实际测试版本为 Python 3.12.14（Linux/POSIX）。代码语法使用 Python 3.10+ 特性，其他解释器版本兼容性待验证。无需 pip 安装。从本目录运行：

```sh
python -B scripts/test_offline.py
python -B -m minimal_slice_vnext.server --db ./fixture-state.sqlite3
```

服务默认 paused。只有可信本地测试操作员可使用 `--fixture-ready` 初始化一个**新** fixture DB 为未暂停；它不会清除已存在的暂停状态。不要把该参数理解成真实账号授权。

`minimal_slice_vnext/MCP_CONFIG.INERT.example.json` 是 disabled 模板，不是活动安装。占位路径应指向本目录；是否支持该配置格式取决于宿主。实际测试过的 AG CLI 通路需检查 `/mcp` 发现状态，必要时 Restart，再核实真实工具结果；仅写入配置不算可用。模板不修改宿主审批策略，运行时遵循宿主设置。

## 测试与边界

见 [TESTING.md](TESTING.md)。测试使用合成响应、fake opener 和临时 SQLite，包含实际本地 stdio 子进程及预留后进程退出测试，未访问任何 Bilibili 账号或网络。

`NarrowViewHttpTransport` **含有真实 urllib 分支**，默认 network disabled 且 paused；测试仅注入 fake opener。通过测试不授权开启该分支。独立文件存储候选到生产凭据后端的接入/真实验收、跨进程账号级 pending-login owner、真实身份验证、写授权与恢复、完整能力目录、对新模块的宿主安装验收仍待实现/验证。手机/SMS 未实现不等于永久禁止。

未知/暂停/未实现不等同用户拒绝；纯解析不授予权限。可信 Python ports 不是可让模型传 `approved=true` 就放行的公开工具。当前 metadata 记录的 `recorded` 仅代表保存观察，不代表实时动作完成。

## 新增独立存储端口

`credential-store-candidate` 接收可信内部 opaque bytes，公开结果只返回账号/handle/generation 与状态；恢复始终 `unverified`，callback entry 不是业务成功或授权。CAS、非阻塞协作锁与 fsync/replace 用于隔离验证存储关系，不改变现有 marker-only 组合。

本轮只用临时 `FAKE_ONLY` 材料，未读取、保存、备份任何真实凭据。受限明文文件不等于加密、同 UID 恶意代码隔离或不可回滚存储。跨进程与同文件系统崩溃恢复也不证明 dot 云磁盘重置/替换/快照回滚后的永久保留；不会据此将真实材料备份到 GitHub、Library、Drive 或新服务。真正启用须另行审查目标私有目录并确认实际材料范围。

## 来源与许可

保留各目录 MIT LICENSE，根 LICENSE 同属 MIT。fixture URL 校验依据原公开项目的固定提交；metadata schema 事实来自固定版本的社区 MIT 实现，未复制其重试、签名或第三方源码。详见 [metadata-adapter-candidate/SOURCES.json](metadata-adapter-candidate/SOURCES.json)；社区实现不是官方实时接口保证。没有 vendored 第三方依赖。

`MANIFEST.json` 与 `SHA256SUMS.txt` 记录本候选文件；不包含数据库、凭据、AG 日志、内部提示词或回执。该目录的复制/提交本身不会改变原服务、账号或部署。
