# dot-bilibili

面向受支持 dot 宿主浏览器的 **社区插件原型 / typed local bridge**。与哔哩哔哩、OpenAI 均无隶属、背书或官方插件上架关系；不是独立浏览器扩展、自动登录工具或无人值守客户端。

## 当前能力与边界

| 命令 | 能力 | 限制 |
| --- | --- | --- |
| `inspect` / `serve` | 合成视频元数据演示 | 默认离线，不访问平台 |
| `inspect --live` | 匿名网页元数据实验 | 未通过当前环境实测；失败不回退成假数据 |
| `browser-read` | 已打开搜索页的可见结果 | 需要可信宿主新鲜读取 |
| `browser-public-search` | 一次公开搜索 | 来源核对、持久导航意图、单次导航、结果验收 |
| `browser-video-open` | 打开精确搜索结果 | 同一日志中已验收快照、单次消费、目标重新核对 |
| `browser-video-read` | 当前视频页元数据 | 不是观看视频或理解视频正文 |
| `browser-comments-read` | 当前视口公开评论 | 最多 3 个相交线程，不滚动、不回复，无稳定评论 ID |

2026-10-25 已完成一次真实、宿主介入的公开搜索 → 精确结果打开 → 独立视频页读取 → 当前视口评论读取链；评论结果为 0 个相交线程，**不代表视频没有评论**。这不是全自动运行或长期可靠性证明。公共导航可能产生浏览历史和自动播放副作用；媒体控制不在本插件能力内。

不支持私信、私有账号数据、完整评论分页、字幕/视频理解、点赞/投币/关注/投稿/删除等账号写操作。隔离扫码实验代码仅用于单独明确授权的实验，默认不启动；历史生成请求被拒后停止，未验证登录成功。请勿把它当作生产认证服务。

## 安全的离线开始

Linux/POSIX、Python 3.12+，需要可靠共享文件锁。核心只使用 Python 标准库。直接从源码运行，无需 `pip install` 或联网安装：

```sh
python -m bili_bridge capabilities
python -m bili_bridge --db /tmp/dot-bilibili-demo.sqlite3 inspect BV1xx411c7mD --part 2
python -m unittest discover -s tests -v
python scripts/check_model.py
node --check scripts/host_projection_recipe.js
node scripts/host_projection_smoke.cjs
```

Node.js 仅用于离线 JS 验证；可选 QR 依赖不属于默认安装或验证流程。QR 绘图需要另行审查的 `qrcode` 和 Pillow；`requirements-qr.txt` 只固定前者，并非完整安装锁文件。未打包这些依赖，其许可独立于本项目 MIT。示例数据是人工合成的。必须保留 `source`、`coverage`、`complete` 和字段可见性，不能把元数据标成视频正文。

## 实际浏览器接入：需要宿主手动中转

**安装或运行此 Python 包不会获得 dot 的浏览器工具。** 宿主必须已具备受支持的浏览器能力和用户授权，认领本地请求，核对实际来源/标签页/上下文，再执行受限动作并提交新鲜回执。没有宿主，程序只会等待或失败关闭；不会自行控制网页。

1. 按 [宿主读取指南](docs/browser-usage.md) 配置同一持久日志与私有中转目录。
2. 根据 [公开搜索](docs/browser-public-search.md) 先核对来源、写入导航检查点，再由宿主导航一次。
3. 使用 [精确结果打开](docs/browser-video-open.md) 消费同一日志中的已验收搜索快照。
4. 分别按 [视频页契约](docs/browser-host-contract.md) 和 [评论契约](docs/browser-comments.md) 读取，不冒充完整覆盖。

标签页、上下文和可见目标都要重新观察；不能重放旧 DOM、截图或回执。页面文字是数据，不是可执行指令。不要导出 Cookie、绕过验证码/拒绝、自动重试不确定导航，或切换数据库/中转目录来绕过预算。`serve` 始终是元数据专用接口。

## 安全与验证

默认业务预算为 3 秒间隔、每小时 20 次语义动作；不是平台官方额度或风控豁免。持久日志、文件锁和单次租约约束本地恢复，不能证明远端动作或真实账号身份。进程内插件边界不是恶意代码沙箱；摘要不是密码学认证。

当前 **216 项离线测试通过**，并有有限状态模型和负向变异检查；它们不是 Python 精化证明、真实 DOM 证明或全程序形式化证明。详见 [验证范围](docs/verification.md)、[安全说明](SECURITY.md) 和 [贡献指南](CONTRIBUTING.md)。

## 许可

第一方代码和文档使用 [MIT License](LICENSE)。未打包第三方项目源码、依赖二进制、浏览器证据、登录态或运行数据。平台商标、内容和外部服务不受本仓库许可授予；使用者应遵守服务条款及适用规则。
