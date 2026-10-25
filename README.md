# dot-bilibili

面向 **dot 云端受支持浏览器宿主** 的自研只读 B 站控制组件。MIT 许可；非哔哩哔哩或 OpenAI 官方插件。

当前进度见 [progress.json](docs/progress.json)：本阶段严格 5/5，已盘点业务范围 5/122（4.10%）。最初研究报告是历史基线，不随此处状态自动改写。

## 0.3.0：能做什么

已对冻结的五项原语完成 **5/5 有界严格验收**：

1. 提交公开搜索。
2. 独立读取当前可见搜索结果。
3. 从第二步的新鲜结果中精确选择并打开视频。
4. 读取当前可见视频元数据。
5. 读取当前视口相交的公开评论线程。

两个独立宿主执行会话、两个不同搜索目标完成了真实五步工作流。第二轮通过下述 Python AI 接口实际调用；随后状态查询没有增加平台操作。空评论视口不代表视频没有评论；元数据可明确返回 `not_visible`。本轮新流程未验证正向评论正文读取或完整评论分页。

**这是可使用的宿主驱动只读版，不是全部 122 项业务原语完成，不是独立无人值守浏览器驱动，也没有自动注册为聊天界面的原生工具。** 暂不支持账号写入、私信读取、投稿、完整字幕/视频理解、任意 URL 导航或自动绕过挑战。

## AI 入口：两个工具、两个必要业务参数

模型只需要选择搜索词和选择方式，不需要构造数据库路径、标签页 ID、操作摘要或中转路径。

```json
{"tool":"bili_search_read","arguments":{"query":"公开搜索词","select":"first_visible","comments":true}}
```

`select` 必须显式提供：`first_visible` 或本次搜索结果中的精确 BVID。前者只是第一个可见结果，不保证“最佳”。`comments` 默认 `false`：四步；开启时五步。当前查询不能以 `-` 开头，该限制来自原型 CLI 传输并在调用前显式拒绝。

```json
{"tool":"bili_status","arguments":{"request_id":"上次返回的请求引用"}}
```

统一返回 `request_id / status / data / coverage / error / next_action`。未知结果不自动重发。状态查询不启动、恢复或重复工作流。导航可能产生平台历史记录或自动播放，不能宣称完全没有网站侧副作用。

实际 Python 接入（宿主预先绑定 `HostProfile`，并发服务浏览器请求）：

```python
from facade import HostProfile, search_read, status

# 以下由可信宿主配置，不作为模型工具参数暴露。
profile = HostProfile(
    db="/absolute/private/state.sqlite3",
    spool="/absolute/private/host-spool",
    source_url=host_observed_source_url,
    tab=host_observed_tab_id,
    timeout=180,
)
result = search_read(
    {"query": "公开搜索词", "select": "first_visible", "comments": True},
    profile=profile,
    invocation_id=durably_saved_host_call_id,
)
view = status({"request_id": result["request_id"]}, profile=profile)
```

以上示例从仓库根目录运行。**`search_read` 是同步调用，必须与可信宿主的 spool dispatcher 并发运行。** 普通 Python 进程不会因安装本包就获得 dot 浏览器访问权；没有宿主服务时会按期限失败关闭。首次完整调用意图必须持久化，同一调用重试使用相同 invocation ID，不能换 ID 规避未知结果。入口 schema、状态读取限制及接线见 [AI API 当前用法](docs/ai-tool-usage.md)（另保留验收前合同快照）。

## 分层与防耦合

AI façade → 有界工作流 → 固定 CLI 能力 → 分层中转/内核 → 可信浏览器宿主。

- façade 隐藏内部标识，但不隐藏权限、范围、拒绝或未知结果。
- 工作流固定顺序：搜索 → 新鲜搜索读取 → 精确打开 → 元数据 → 可选评论；不接受任意命令、脚本或路径。
- 全流程共享同一持久账本和 spool；预算与冷却不因更换进程而清零。
- 选择插件只获得 `SelectionConsumer` 单方法端口，不持有整个内核。其回调提供者依赖仍显式保留，不冒充恶意代码沙箱。
- 固定宿主采集器保留原始链接/URL，先验证目标再规范化；页面文字不能成为授权指令。

初始验证预算：每个有限模型实例 **10,000 状态 / 5 秒 / 32 MiB Python 跟踪分配**，每模块本地导入依赖上限 16，插件完整内核注入数上限 0。超标即失败，需要审查/拆分；这些是可执行工程警戒线，不是“超过某维数必然天文复杂”的定理，也不是 RSS 限制。详见 [验证预算](docs/verification-budget.md)、[交付层依赖与模型](docs/delivery-boundaries.md)。

## 复现离线检查

Python 3.12+、Linux 可靠文件锁；业务运行时只用标准库。Node 仅用于 JS 检查。

```sh
python -m unittest discover -s tests -v
python scripts/check_model.py
python scripts/check_verification_budget.py
python scripts/check_delivery_boundaries.py
python scripts/check_milestone_five.py
node scripts/host_projection_smoke.cjs
node scripts/host_capture_smoke.cjs
```

精确测试数量和证据见 [五项验收](docs/milestone-five-acceptance.md)。源码/模型/离线测试不会替代真实页面验收；有限状态检查不是 Python 实现精化证明或平台正确性证明。该仓库未配置 GitHub 自动 CI，以上命令不意味着已在 GitHub Actions 运行。

可选二维码实验不属于已验收链路，不能自动启动。依赖 `qrcode` 与 Pillow 未随仓库打包、各有许可；当前可选依赖清单并非完整锁文件。不会导出浏览器 Cookie、自动恢复登录或开启私信监听。

## 宿主运行与证据

- [单命令工作流与 dispatcher](docs/read-workflow.md)
- [固定只读 DOM 采集器](docs/host-capture-recipes.md)
- [公开搜索](docs/browser-public-search.md)
- [新鲜结果精确打开](docs/browser-video-open.md)
- [视频与评论范围](docs/browser-host-contract.md)、[评论](docs/browser-comments.md)
- [安全边界](SECURITY.md)、[贡献规范](CONTRIBUTING.md)

公开交付仅包含第一方源码、合成测试、模型和去标识验收说明。凭据、运行数据库、原始浏览器回执、私有仓库研究材料不包含在内。三个后端方向仍互补：独立接口连接器、浏览器桥接、未来客户端内部控制器；目前只有本仓的受限浏览器链得到上述验收。

## 后续产品重点

直接接入版以自动性和效率为重点；网页／客户端版以人机互助与交互为重点。它们共用语义合同但不强行统一体验。当前能力、未来缺口和拟议指标见 [产品方向](docs/product-directions.md)。
