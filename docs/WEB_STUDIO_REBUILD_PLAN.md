# Yukina + Nova + AI绘图站统一工作台实施方案

日期：2026-09-22
状态：执行中。本文件是可执行的分阶段方案；已实现内容以 `docs/migration/implementation-log.md` 和代码为准，未完成能力不得按已上线宣称。

> 2026-09-23 起，剩余工作改按 `docs/migration/remaining-execution-plan.md`
> 集中实施。R1-R5 全部实现前不运行测试、构建、类型检查或浏览器验收；
> 原文各阶段的功能范围仍然有效，但中间验收门不再执行。

## 0. 交付目标与执行规则

目标不是嵌入两个网站，而是一个工作台：

> Yukina 页面基础与视觉语言 + Nova 创作交互 + 本插件服务商、聊天、人设和任务系统。

最终用户只需要安装 AstrBot 插件，不需要启动 Node、Next.js、Nova 后端或第二套数据库服务。
开发和发布机器需要 Node；发布包必须包含构建好的静态页面。

执行规则：

1. 按 S00 至 S12 顺序实施。每阶段通过验收后才进入下一阶段。
2. 每阶段单独提交。不得一个提交同时重写后端、替换页面和迁移数据库。
3. 不满足验收时报告具体失败项，不把页面出现了当成功能完成。
4. 未提供商家测试凭据时使用模拟协议测试，真实接口验收单独标为未测。
5. 不用生产任务测试自动重试；任何付费验证必须先说明模型、数量与预算并得到授权。
6. 不提交、恢复或覆盖当前工作区中用户已有的 `_conf_schema.json` 修改。
7. 不以“后续再做”为由删除原有功能。新页面未覆盖旧功能时保留旧入口。
8. Nova 全部目标功能都列入范围，但不是一期同时上线。任何删减须由用户确认。

### 测试范围约束（按用户要求）

- 复用现有测试，不另建庞大测试体系，不设覆盖率门槛。
- 新增自动化仅覆盖本次改动的高风险逻辑：鉴权/会话隔离、重复付费提交、请求参数类型、文件清理和数据保留。已有用例能覆盖时只修改原用例。
- 以下各阶段的“验收”默认是简短人工检查，不要求逐项编写测试文件；同一条创作流程可同时覆盖多项验收。
- 页面只检查桌面、手机两个代表视口；不做浏览器、主题、服务商、设备的组合矩阵。
- 不为此次重构强制引入 Vitest、独立 E2E 工程、负载测试或复杂 mock 平台。浏览器工具用于少量冒烟检查和截图即可。
- 每阶段只跑受影响的现有测试；现有全量测试在基线和发布前各跑一次，不在每次页面修改后重复运行。
- 安全检查和防重复计费验证不能省略，但采用少量可复现用例，不扩大为专项测试工程。

完成标志：

- 现有命令、LLM 工具、服务商、预设、自拍、人设、历史、批量和任务管理通过回归。
- 图片、视频、画布、Agent、GIF、反推提示词、提示词库、切图/网页复刻进入同一工作台。
- 聊天任务与 Web 任务进入同一任务系统，素材不靠浏览器之间手工复制。
- 前端不持有服务商 Key，不直接请求商家接口，不维护独立生成队列。
- 断线、重载和升级不会自动重发已提交的付费生成任务。

## 1. 起点与备份

工作仓库：

```text
E:\Codex\astrbot_plugin_aiimg_enhanced
```

本地参考仓库：

```text
E:\Codex\reference_yukina_20260922
E:\Codex\reference_nova_20260922
```

### S00：冻结基线、许可和功能清单

操作顺序：

1. 在工作仓库运行 `git status --short` 和 `git rev-parse HEAD`，记录到实施记录。
2. 检查分支是否存在；不存在时执行 `git switch -c refactor/unified-web-studio`。
3. 对两个参考仓库分别运行 `git rev-parse HEAD`，记录所参考的精确提交，不跟随浮动 main。
4. 从运行环境定位插件实际 data_dir 和实际配置文件。不能把代码仓库当成运行数据。
5. 停止测试实例写入后，备份配置、人设、参考图、图片历史 SQLite 和媒体文件。
6. 在测试实例恢复备份并检查历史图片可打开，再认定备份可用。备份不得提交 Git。
7. 建立以下文件：

```text
docs/migration/feature-inventory.md
docs/migration/source-manifest.md
docs/migration/acceptance.md
docs/migration/implementation-log.md
THIRD_PARTY_NOTICES.md
```

`source-manifest.md` 每条记录：

```text
来源仓库 | 提交 SHA | 原文件 | 目标文件 | 许可 | 修改说明 | 素材授权凭据位置
```

许可门槛：

- Yukina 本地 LICENSE 为 MIT；图片、字体等素材单独登记，不能推定代码许可涵盖素材。
- 用户已说明素材取得非商业使用许可；记录具体文件、授权范围、署名和可否再分发。
- Nova 本地 LICENSE 为 AGPL-3.0。复制代码前，确认组合项目的发布方案和许可证兼容性。
- 不自行把整个已有项目改许可，也不认为标注来源就完成许可义务。
- 若整体组合的许可或素材分发条件未确认，停止引入相关代码/素材；后端安全修复仍可继续。
- Electron 和 PWA 属于部署能力，不自动随工作台迁入；是否提供独立桌面版另立项目。

验收：

- 有基线 SHA、两个来源 SHA、可恢复备份、许可清单。
- 功能清单覆盖所有注册命令、工具、页面、服务商，而不是只列热门功能。
- `_conf_schema.json` 的用户修改保持原样。

## 2. 固定架构，不再每个功能另起一套

```text
浏览器
  Yukina 派生 Astro 布局、背景素材、主题变量
  一个 React StudioApp：导航、工作台、画布、设置、历史
  ApiClient：只访问同源插件 API
       |
AstrBot 鉴权边界
  Studio API + 旧 Pages API（迁移期保留）
       |
  应用服务：提交任务、选择参考图、加载人设、验证权限
       |
  持久任务记录 + ProviderRegistry + 现有图像/视频后端
       |
  媒体存储、历史、项目数据
```

具体约束：

- Astro 沿用 Yukina 模板结构；React 通过 `@astrojs/react` 挂载。
- 用一个 React 根维护业务状态，避免多个互不连通的工作台 islands。
- 工作台导航用 hash 路由，如 `#/create/image`，避免 AstrBot 子路径刷新 404。
- Yukina 的导航样式和主题保留；需要交互的导航迁入统一 React 根。
- 移除博客内容集合、RSS、sitemap、Pagefind、文章页；工作台不运行 Swup 页面替换。
- 不保留 Nova 的 Next 路由、Node server.js、独立 Key 设置和上游 HTTP 调用。
- 不同时加载 Tailwind 3 和 4。先用纯 CSS 主题变量完成 Yukina 外壳，移植 Nova 时统一到一套构建样式。
- Svelte 搜索等博客专属组件不带入；不要为一个非必要控件引入第三套运行时。
- Nova 的 Zustand 只存选中项、面板展开、草稿等客户端状态；服务器任务为事实来源。
- localStorage 只允许无敏感信息的界面偏好。不存 Key、授权头、永久素材正文。
- 默认不开启 service worker；不能缓存配置、鉴权 API、任务响应和用户媒体。
- 新静态文件先输出到 `pages/Studio/`，旧 `pages/Settings/` 不覆盖。

建议目录（标记为新增的均需创建）：

```text
web/                                  新增前端源代码
  package.json
  package-lock.json
  astro.config.mjs
  src/pages/index.astro
  src/layouts/YukinaStudioLayout.astro
  src/styles/tokens.css
  src/styles/yukina-shell.css
  src/app/StudioApp.tsx
  src/app/routes.ts
  src/api/client.ts
  src/api/contracts.ts
  src/components/ui/
  src/features/create/
  src/features/canvas/
  src/features/assets/
  src/features/tasks/
  src/features/personas/
  src/features/settings/
  src/features/agent/
  src/features/gif/
  src/features/design/
  src/features/prompts/
  tests/
  e2e/
  public/authorized-assets/
pages/Studio/                         新构建产物
core/studio/                          新应用层；不重写现有 provider
  contracts.py
  generation_service.py
  reference_resolver.py
  capability_catalog.py
  job_store.py
  asset_store.py
  project_store.py
  migrations/
handlers/studio_api.py                新 Web API
scripts/build_studio.mjs              新发布脚本
scripts/check_studio_compat.py         新完整性检查
```

## 3. 功能迁移矩阵

在 feature-inventory.md 中给每一行追加：负责人、状态、旧入口、简短验收结果；不要求每行配套自动化测试。
“保留”表示不移除；不是承诺当前实现没有缺陷。

| 功能 | 现有实现/来源 | 新位置 | 必须满足 |
| --- | --- | --- | --- |
| 文生图、改图 | draw_service/edit_router | 图片工作台 | 与聊天使用同一生成服务 |
| 自拍、多人设 | persona_manager/session_personas/main | 人设 + 图片工作台 | 会话选择不修改全局默认 |
| 身份/衣服/姿势/场景 | persona_ref_service/main | 参考图槽位 | 明确用途，不自动当同一原生能力 |
| 所有服务商模板 | provider_registry/provider_catalog | 设置 + 能力表单 | 不因新 UI 丢字段或 Key |
| 视频与全部模式 | 视频后端 + Nova 表单 | 视频工作台 | 参数和参考图上限按能力约束 |
| 命令和 LLM 工具 | main/handlers | 聊天入口保留 | 名称、返回语义和权限不变 |
| 批量、并发、去重 | batch_executor/debouncer/main | 工作台 + 任务 | Web 不能绕过限流 |
| 自然语言转标签 | nai_prompt | 提示词工具 | 原文、有效标签分别保存 |
| 预设与批量规划 | image_task_parser/llm_batch_planner | 提示词/预设 | 旧预设可读，引用不失效 |
| 历史、重发、继续改图 | image_history/history_page_service | 素材与历史 | 图片历史仍全局最多 100 张 |
| 任务取消和进度 | task_manager | 任务中心 | 取消本地不谎称上游已取消 |
| 发送回退 | main/video_manager | 可选发送到聊天 | 不重新生成，只重发结果 |
| 代理、下载安全、缓存 | net_safety/image_manager/video_manager | 设置 | 原有选项继续可配置 |
| 图片/视频工作台 | Nova ImageGenerationWorkbench/PluginWorkbench | 创作 | 改接插件 API |
| 无限画布 | Nova canvas | 画布 | 节点引用 asset_id，生成调用统一任务 |
| 提示词反推、优化、图库 | Nova ReversePrompt/PromptGallery | 提示词 + 创作 | 使用 AstrBot 文本/视觉模型 |
| Agent 模式 | Nova Agent 相关组件 | Agent | 生成前确认数量和目标服务商 |
| GIF 生成与调帧 | Nova GifGenerationWorkspace/GifFrameTuner | GIF | 帧为受管素材，生成帧进入任务系统 |
| UI 切图、修补、网页复刻 | Nova slice | 设计 | 预览与代码执行隔离 |
| 素材、项目、导入导出 | Nova assets/store | 素材与项目 | 项目不携带 Key，不靠 localStorage 唯一保存 |

原插件中清单未列出的注册命令、设置字段和特殊平台行为必须补登记后再迁移。
不将 Nova 桌面壳、独立账号体系、任意服务端插件执行等部署机制伪装成已有功能。

## 4. 页面和操作路径

默认进入创作工作台，不建营销首页，不用博客文章列表作为入口。

导航：创作、画布、素材、任务、人设/预设、Agent、GIF、设计、设置。
创作内部切换图片/视频，共享会话、人设、素材选择和提示词。

桌面：

- 左侧为紧凑导航，中间为作品与编辑区域，参数在侧栏或可折叠面板。
- Yukina 背景/插画限定在品牌和空白区域，不能压在表单、文字或图片预览上。
- 结果预览显示原图/原视频，不用背景效果遮盖内容。

手机：

- 底部显示主要入口，其余放“更多”；参数面板为抽屉。
- 生成按钮、取消按钮不互相遮挡；上传、排序和删除支持触控。
- 画布提供适合触控的工具栏，精细编辑不依赖 hover。

跨页面操作：

1. 上传图 -> 获取 asset_id -> 放入“身份/首帧/风格”等槽位。
2. 生成成功 -> 结果自动成为素材 -> 点击“放入画布”。
3. 画布选中图 -> 点击“继续改图/生成视频” -> 填入原素材引用。
4. 任何入口发起的任务 -> 同一任务中心显示来源、时间、状态、上游任务 ID。
5. 历史条目 -> “复用参数”加载快照；“再次生成”必须新建任务并明确触发。
6. 任务生成成功但发送失败 -> 只提供重发，不默认重新生成。

## 5. 统一数据契约

### 5.1 GenerationSpec：业务请求，不等于商家请求

所有入口转换为同一结构；后端再次校验，不能只靠前端禁用按钮。

```json
{
  "schema_version": 1,
  "client_request_id": "browser-generated-uuid",
  "operation": "video.generate",
  "provider_id": "grok",
  "session_id": null,
  "persona_id": null,
  "prompt": "午后海面，镜头缓慢推进",
  "reference_policy": "explicit",
  "references": [
    {"asset_id": "asset-uuid", "role": "first_frame", "order": 0}
  ],
  "parameters": {
    "duration_seconds": 8,
    "aspect_ratio": "16:9",
    "resolution": "720p"
  },
  "delivery": {"mode": "web"}
}
```

- `operation`：image.generate、image.edit、video.generate；扩展功能新增版本化值。
- `provider_id` 指插件服务商 ID，不允许浏览器提交任意上游地址。
- `reference_policy`：none / explicit / persona_fallback；纯文生必须 none。
- `session_id` 由有权限的会话选择器提供，服务端校验，不信任任意客户端字符串。
- `role` 保留 identity/clothing/pose/scene，扩展 source/first_frame/last_frame/style。
- 可选字段必须区分“未设置”和“显式为 0/false”；不使用 `value or default` 吞掉合法值。
- 参数快照记录原文、转换后提示词、实际模型和非敏感配置版本，不含 Key。
- Web 选择人设默认仅影响本次任务；改变会话人设必须独立操作并确认。
- 能力不支持某个角色时，明确提示；不默默丢图、不擅自拼图。

### 5.2 任务状态与恢复

持久业务状态：

```text
queued -> preparing -> submitting -> submitted -> polling
       -> downloading -> completed
failed / cancelled / submit_unknown / interrupted
```

发送状态独立：not_requested / pending / sending / sent / failed。
旧 task_manager 的 preparing/generating/sending 等由适配器映射，不立即删除旧字段。

规则：

- `submitting` 超时且无法确认受理情况：submit_unknown，不自动重提。
- 已有 upstream_request_id：只能继续查、下载、发送，不走另一个服务商重新生成。
- 明确的请求校验失败可以按兼容策略修正；不得无限重试或盲猜协议。
- 重启后 polling 任务按原配置版本恢复查询；密钥失效则等待人工处理。
- 本地取消终止等待，记录 remote_cancel_supported=false，不声称已退费。
- completed 表示素材已保存；发送失败不把生成结果抹掉。
- 任务与素材先持久化，再发事件。浏览器断线不影响后台任务。

### 5.3 素材与历史

素材表建议：

```text
assets:
 id, owner_scope, media_type, storage_key, content_hash,
 width, height, duration, byte_size, created_at, source_job_id,
 retention_class, reference_count
```

- 图片历史继续使用原 image_history.sqlite3，保留 ID 和会话规则。
- 新 studio.sqlite3 管理任务、项目与素材索引，先用关联表连接旧历史，不改旧表结构。
- 历史最多 100 张；收藏/项目素材是明确的独立副本或受引用保护的对象，不能借引用无限保留历史缓存。
- 视频单独设容量/数量限额，不悄悄计入“100 张图片”。
- 临时下载、生成结果、收藏、项目附件有不同保留策略。
- 不允许用户直接指定磁盘路径；下载通过 asset_id 找 storage_key。
- 清理先查询引用和使用锁，排除 .part、活动任务与待发送文件。

## 6. 后端 API 约定

拟定前缀：`/astrbot_plugin_aiimg_enhanced/studio/v1`。
S02 验证真实 AstrBot 挂载方式后，通过 bootstrap 提供实际 api_base，不让前端猜地址。
保留旧 `get_config/save_config/get_history/get_tasks` 等 API，逐步委托新服务。

| 方法与相对路径 | 作用 | 验收 |
| --- | --- | --- |
| GET /bootstrap | API 地址、版本、权限、功能开关 | 不含 Key |
| GET /providers | 服务商脱敏列表、能力描述 | 不返回完整配置秘密 |
| GET /sessions | 当前操作者可选会话 | 非授权 scope 不可枚举 |
| GET/PUT /config | 带 revision 的配置读取/更新 | 冲突返回 409 |
| POST /assets | 受限 multipart 上传 | 类型、大小、解码与权限校验 |
| GET /assets | 分页、搜索、类型过滤 | scope 隔离 |
| GET /assets/{id}/content | 下载/预览 | 安全路径，视频 Range 支持 |
| POST /assets/{id}/pin | 收藏素材 | 独立保留策略和配额 |
| DELETE /assets/{id} | 删除 | 项目引用时 409，或明确解除引用 |
| POST /jobs | 校验并入队 | 返回 202 与 job_id，不阻塞到出图 |
| GET /jobs | 分页状态、更新游标 | 刷新页面仍能找回任务 |
| GET /jobs/{id} | 详情、结果、上游 ID | 无 Key 或敏感签名 URL |
| POST /jobs/{id}/cancel | 本地取消 | 幂等，明确上游是否支持取消 |
| POST /jobs/{id}/resume | 继续查询/下载 | 禁止重新提交生成 |
| POST /jobs/{id}/deliver | 发送已有结果 | 目标会话授权校验 |
| GET /history | 旧历史桥接 | 保留原记录 ID 与倒序编号 |
| GET/POST/PUT /projects | 画布、GIF、设计项目 | version 乐观锁 |
| POST /prompt-actions | 反推、优化、转换 | 选定文本/视觉模型，限流 |
| GET/POST/PUT /presets | 提示词与预设 | 兼容旧预设 |

统一成功响应示例：

```json
{"ok":true,"data":{"job_id":"job-uuid","state":"queued"},"trace_id":"trace-uuid"}
```

统一错误响应示例：

```json
{
  "ok": false,
  "error": {
    "code": "REFERENCE_COUNT_EXCEEDED",
    "message": "单图首帧只允许一张图片",
    "field": "references",
    "retryable": false
  },
  "trace_id": "trace-uuid"
}
```

状态码约定：400 格式错误；401/403 鉴权；409 配置或项目冲突；
413 上传过大；422 能力/参数不支持；429 限流。不要将上游密钥、整段响应或 Base64透传。

幂等：

- client_request_id 按已认证操作者建立唯一约束。
- 同 ID 同请求返回原 job_id；同 ID 不同内容返回 409。
- 幂等判断在数据库事务内完成，不能只靠按钮 disabled。

实时状态：

- 第一版 GET /jobs 游标轮询：可见且有活动任务时约 2 秒，后台页面降低频率。
- 断线重连从游标补数据；页面卸载取消本地轮询，不取消服务端任务。
- SSE/WebSocket 后续仅在宿主鉴权、代理和心跳测试通过后增加，不作为一期前置。

鉴权：

- 所有写操作和用户媒体必须进入真实 AstrBot 鉴权链。
- 在 S02 实测 cookie/token 方式，不能以 URL 隐蔽作为鉴权。
- cookie 鉴权时，写操作验证 CSRF token 和 Origin；不同认证方式按宿主规范实现。
- 开发代理同源转发，不允许生产环境 `Access-Control-Allow-Origin: *` 搭配凭据。
- Key 更新使用保持不变/替换/清空三态；不能把脱敏星号保存为真正 Key。
- 新老设置页面共同调用原子配置服务：先验证，再备份，再持久化，再切换实例。

## 7. 按阶段实施

### S01：修复后端基础风险

修改范围：

```text
core/video_manager.py
core/openai_video_service.py
core/agnes_video_service.py
core/task_manager.py
handlers/pages_api.py
main.py 视频生成链路
tests/ 对应新增回归测试
```

操作：

1. 所有媒体预解析请求统一经过 net_safety；逐次校验重定向，限制预读字节。
2. 给上游错误分类型：ValidationError、SubmissionUnknown、PollError、DownloadError。
3. 禁止已提交任务因轮询/下载失败而自动换服务商。
4. 文件 token 只对本插件创建的记录应用特殊行为，其他调用走宿主原实现。
5. 清理只作用于完成且未被引用的文件；增加生成中/发送中的使用登记。
6. 热更新保留旧后端的活动引用，任务结束后调用 close，再回收。
7. 有类型的请求对象分别编码 JSON/multipart，停止从 multipart 反推 JSON。

验收测试：

- 内网 URL 和公网重定向到内网在首次连接前阻止。
- 超大预览响应被限制，不先完整加载。
- 模拟提交被接收但响应断开：只能出现一次提交。
- 模拟已取得上游 ID 后查询失败：不能调用第二个服务商。
- 用一个活动下载与一次清理验证活动文件不会被删除，不做并发压测。
- 修改服务商配置时，旧任务继续运行，新任务使用新实例，旧实例最后关闭。

S01 不改 UI，不扩展模型能力，不顺手重命名所有模块。

### S02：Yukina 外壳与宿主可行性验证

操作：

1. 创建 web/，依据 Yukina 固定提交复制布局、样式、必要素材，登记来源。
2. 配置 Astro 静态输出和 React 集成。锁定兼容依赖版本，提交一个锁文件。
3. 创建 StudioApp，只做导航、主题、空内容区、登录状态和 API 连通。
4. 把资源路径设置为子路径兼容；不把绝对 `/assets` 写死。
5. 通过现有 pages 机制新增 Studio 入口；真实测试实例启动后确认路径。
6. 若 pages 机制只暴露 HTML、不暴露资源，增加受控静态路由，禁止路径穿越和源码读取。
7. 将默认 API 根由宿主 bootstrap 注入。
8. 用开发代理连接测试实例，不在浏览器请求上游模型。

本阶段须创建并能执行这些脚本：

```powershell
# 从仓库根目录执行；脚本未创建前不要照抄当作现有命令。
npm --prefix web ci
npm --prefix web run dev -- --host 127.0.0.1 --port 4321
npm --prefix web run check
npm --prefix web run build
node scripts/build_studio.mjs
```

端口已占用则改为 4322。启动后把实际地址告诉用户。
build_studio 只能原子替换 pages/Studio，自检目录范围，不删除 pages/Settings。

验收：

- 正常根路径和带反代子路径均可打开、刷新、加载图片和 JS。
- 未登录无法读配置、历史、任务和媒体。
- 浅色/深色，390x844、768x1024、1440x900、1920x1080 无溢出或遮挡。
- 浏览器控制台无错误。生产页面不需要 Node 服务。
- 若此阶段失败，不开始搬 Nova 业务组件。

### S03：能力目录与统一表单

操作：

1. 新建 core/studio/capability_catalog.py，以 provider template + model 配置生成能力。
2. 每项包含 operation、输入槽位、数量、类型、时长、尺寸、分辨率、流式支持、可取消能力。
3. 区分“不支持”和“未知”。不根据模型名称包含 grok/nai 就开放所有参数。
4. 为自定义中转保留管理员显式能力配置，默认保守；标记实际验证日期与协议。
5. 移植 Nova plugin/SchemaMediaField、SchemaToolbar 等表单交互，
   用我们的能力契约替换 Nova plugin manifest 运行时。
6. 不执行 Nova 服务端插件 JavaScript。后续支持导入 UI schema 时只接受白名单声明字段。
7. 初期现有 provider_catalog 保留；用现有校验方式检查字段一致性，随后由统一描述生成新页面字段。
8. 旧配置未知字段 round-trip 保留，不因为新 UI 未显示就删除。

验收：

- xAI 和 OpenAI Videos 的字段不混用。
- 纯文生不回退自拍图；单图、多图、首尾帧各自校验。
- JSON bool/number/object 往返保持类型。
- 旧服务商配置读取、编辑、保存后除了明确改动外完全保留。

### S04：统一任务与 Web 提交接口

操作：

1. 新增 contracts、job_store、generation_service，复用 ProviderRegistry。
2. 从 main.py 抽出生成编排，不把整个事件处理函数移动到新模块。
3. 聊天入口只负责消息提取和回复；Web 入口只负责 HTTP 与权限。
4. 不构造虚假 AstrMessageEvent 来调用聊天命令。
5. 新建 studio.sqlite3，使用版本化增量迁移；SQLite 访问置于受控线程并有事务。
6. 实现 jobs 创建、详情、取消、恢复、幂等和轮询 API。
7. 给旧任务管理器增加持久记录桥接，不破坏旧取消命令。
8. 队列限制复用并发规则；Web 用户不能靠指定不同 session 绕过用户限额。

验收：

- 双击生成/客户端重试创建请求只产生一个 job。
- 刷新页面还能看到同一个任务。
- 重启恢复轮询不会重复 POST 上游。
- 发送失败显示生成成功、发送失败，可单独重发。
- 指定会话的人设读取与聊天一致；无授权的会话不能提交或发送。

### S05：图片工作台

来源入口：Nova ImageGenerationWorkbench.tsx、TextToImageForm.tsx、
ImageToImageForm.tsx、GenerationParamsBar.tsx、PromptOptimizeDialog.tsx。

操作：

1. 逐组件复制到 web/src/features/create/image，不整目录搬依赖。
2. 搜索并替换 `next/`、`/api/`、localStorage Key 和 Nova store 引用。
3. 表单绑定 GenerationSpec；图片上传返回 asset_id。
4. 统一选择会话、人设、预设、服务商、模型能力、输出尺寸、批量数量。
5. 展示原提示词与转换结果；生成参数由后端确认，不由前端推测最终值。
6. 输出接入素材和历史，提供继续改图、放入画布、生成视频、下载、发送。
7. 批量部分失败显示逐项结果，不丢失成功图片。

验收：人工走通文生、改图和自拍主流程，顺带检查多图、预设、批量、取消，不为每项新建 E2E 用例；
不支持操作时在提交前显示明确错误，后端仍再次校验。

### S06：视频工作台

来源入口：Nova PluginWorkbench、PluginJobProgressPanel、SchemaMediaField。

操作：

1. 用服务商能力描述生成参数，不使用 Nova 的上游视频 provider 实现。
2. 图片槽位显示用途、顺序和上限，允许显式关闭人设回退。
3. 选择 single-first-frame 时由用户明确选一张人设图，不静默取第一张。
4. 首尾帧仅对已有支持的后端开放；不支持 xAI 首尾帧时明确禁用。
5. 上游进度缺失时显示“处理中”，不伪造百分比。
6. 成功后受控下载到素材存储，短效 URL 不作为唯一历史记录。
7. 轮询失败保留任务 ID，提供继续查询而非默认重新生成。

验收：模拟 202、pending、done、各 URL 变体、415、422、502、超时、
审核失败、下载失败和发送失败；这些状态不能都被显示成“生成失败”。

### S07：人设、预设、设置与旧功能全量迁移

操作：

1. 按 feature-inventory 逐项把旧设置迁到统一界面。
2. 会话人设选择和全局默认选择分开；删除人设的回退规则保持现状。
3. 参考图上传/排序/职责可视化，身份、服装、姿势、场景语义不变。
4. 预设支持搜索、标签、预览和作用范围；旧格式用适配器读写。
5. 服务商 Key 仅显示是否配置，替换必须明确操作。
6. 修改配置采用 revision 防止两个浏览器相互覆盖。
7. 旧页面与新页面共享新的原子保存服务，不出现两种配置行为。

验收：旧页面能改、新页面能读，反向也成立；所有旧表单字段有映射；
测试配置保存失败、并发编辑冲突、删除服务商被功能链引用等场景。

### S08：素材、历史与画布

来源入口：Nova AssetsWorkspace、CanvasWorkspace、CanvasEditor。

操作：

1. 先实现素材 API 和旧历史桥接，再导入画布组件。
2. 画布文档只存节点、变换、边、asset_id 和版本号，不嵌入 Base64 图像。
3. 生成节点调用 jobs API；刷新后按 job_id 恢复，不重新提交。
4. 同一画布允许使用不同服务商，但每个节点显示其服务商与参数快照。
5. 保存项目用乐观锁；冲突提供另存副本，不无声覆盖。
6. undo/redo 只撤销编辑动作，不撤销已计费的上游生成。
7. 导出 ZIP 使用服务器可访问的素材，禁止从任意客户端路径读文件。
8. 历史超过 100 张清理时，收藏或项目已保留的素材仍可用。

验收：保存/刷新/继续编辑无损；跨页面素材复用无重复上传；
生成中删除节点不会丢失任务中心记录；移动端能选择和拖动，键盘用户能操作工具栏。

### S09：反推、提示词库与 Agent

操作：

1. 反推和优化调用 AstrBot 配置的视觉/文本模型，通过 prompt-actions API 统一限流。
2. 提示词广场第一版作为本地提示词库；远程社区源作为显式选择项，不默认上传私有提示词。
3. Agent 会话保存到项目，工具只开放 jobs、assets、projects 的受限接口。
4. Agent 不获得 API Key、任意文件读取、shell 或商家任意 URL 请求权限。
5. 提交生成前展示服务商、任务数量、尺寸与费用是否可知；未知费用标未知。
6. 使用批准后的任务参数哈希绑定执行，模型不能在确认后增加数量或换服务商。
7. 工具结果失败禁止 Agent 自动无限重发，沿用任务幂等和额度。

验收：提示词注入不能读秘密、改配置或绕过确认；会话隔离；
取消 Agent 不影响其他任务；批准一张不能产生第二张付费任务。

### S10：GIF

操作：

1. 移植 GifGenerationWorkspace、GifFrameTuner，把生成帧接到统一任务。
2. 帧顺序、时长、循环、尺寸保存为项目参数；源图为素材引用。
3. 浏览器编码在 Worker 执行，默认限制 60 帧、最长边 1024、单次输入总量 100MB。
4. 超限明确提示；不能卡住主线程后再报错。
5. 编码结果上传为受管素材，支持下载和发送。
6. 中断只取消编码或未提交帧任务，不能声称已取消上游所有付费任务。

验收：生成、调序、删帧、预览、导出、恢复项目和移动端降级都可操作。

### S11：切图与网页复刻

操作：

1. 移植 SliceWorkspace、SliceEditor、WebReplicaWorkspace 的交互。
2. 切图、修补输出都登记为素材；调用图片模型仍进入 jobs API。
3. 保存切片坐标、源图尺寸和版本，缩放后不丢失原始坐标精度。
4. 网页生成输出按文件清单存项目，不直接写插件源目录。
5. 默认只展示静态预览；需要脚本时放入独立沙箱 iframe，禁止 same-origin 权限。
6. CSP 禁止预览访问插件 API、外网连接和顶层导航；不要把后台凭据传给预览。
7. 所有导出路径规范化，拒绝 `..`、绝对路径、驱动器路径及 ZIP 路径穿越。
8. 生成的代码禁止在 AstrBot 主进程执行，Node/Electron 执行功能不移植。

验收：恶意生成 HTML 无法读主页面 cookie、请求设置接口或导航顶层；
导出的 ZIP 无越界条目；多轮修改可回退项目版本。

### S12：发布、迁移和回退

新增前端 scripts 约定：

```text
dev        Astro 开发
check      类型及 Astro 检查
lint       ESLint
build      静态构建
```

首次安装前端依赖时执行 `npm --prefix web ci`；依赖锁文件变化后再执行。
各阶段只运行受影响的现有测试与前端检查，不强制增加测试框架。
发布前从仓库根执行以下命令一次：

```powershell
py -3.12 -m pytest -q
npm --prefix web ci
npm --prefix web run check
npm --prefix web run lint
npm --prefix web run build
node scripts/build_studio.mjs
py -3.12 scripts/check_studio_compat.py
git diff --check
git status --short
```

`py` 不可用时使用已确认可执行的 Python 绝对路径，不把工具缺失当成测试通过。
浏览器冒烟检查只走一条完整创作流程，并查看桌面/手机截图。
无商家凭据时复用现有测试替身，明确标记真实生成未测，不为此搭建独立 mock 服务。

发布操作：

1. 更新版本、CHANGELOG、来源清单与未完成事项。
2. 生成静态产物并验证无 source map 秘密、Key、开发地址或硬编码本机路径。
3. CI 构建后对产物做确定性检查，避免源代码与 pages/Studio 不同步。
4. 发布包同时带 Settings 和 Studio，默认先保持旧入口。
5. 在测试 AstrBot 上完成全部核心验收，再切换 `features.web_studio.default_ui`。
6. `features.web_studio.enabled` 关闭时不挂载新业务入口，旧页面仍能使用。
7. 两个开关新增到配置模型时，先与用户本地 `_conf_schema.json` 差异协调，
   不把已有本地改动一并提交。
8. 至少跨一个稳定发布周期后，用户确认才能移除旧页面。

回退：

- UI 故障：切回 Settings，不清空项目/任务数据库，不重发任务。
- 新任务故障：停止接受 Web 新任务；仍可查询、下载、发送已有任务。
- 数据故障：停止写入后恢复已验证备份，不在运行中覆盖 SQLite 文件。
- 旧版回退不得删除新版本数据；迁移只增量添加，破坏性迁移另行审批。

## 8. 验收清单

每项记录简短检查结果即可；同一张截图或一段日志可覆盖多项，不要求逐项新增测试或截图。

- [ ] 所有原服务商模板可读取和保存，未知扩展字段不丢失。
- [ ] 原命令和 LLM 工具清单没有非计划变化。
- [ ] 图片、改图、自拍、视频与批量可从聊天和 Web 共用任务执行。
- [ ] 人设按会话隔离；Web 临时选择不污染默认人设。
- [ ] 上传、多参考图、顺序、职责、自动回退行为都可见且可验证。
- [ ] 参数 JSON 类型正确；空值、0、false 不被默认值覆盖。
- [ ] 任务提交幂等；上游结果未知不会重复计费式重试。
- [ ] 重启/断线恢复不重发生成请求。
- [ ] 结果已生成但发送失败时可重发。
- [ ] 图片历史最多 100 张，倒序显示会话和时间；收藏与项目有独立配额。
- [ ] 清理不删除活动下载、发送或受引用素材。
- [ ] Web API 和媒体均鉴权，非授权会话不可访问。
- [ ] 私网、重定向、超大下载、路径穿越和恶意 HTML 测试通过。
- [ ] 所有服务商 Key 不出现在普通响应、日志、项目导出和 localStorage。
- [ ] 配置热更新无连接泄漏，不中断运行中的旧任务。
- [ ] Yukina 外壳与 Nova 功能视觉统一，不是 iframe 嵌入两个站点。
- [ ] 桌面/手机无溢出遮挡；抽查主题切换、键盘焦点、触控和 reduced-motion，不做组合矩阵。
- [ ] 无多余 Node 服务，无外部 CDN 强依赖，无生产浏览器控制台错误。
- [ ] 画布、Agent、GIF、提示词、设计功能分别完成 S08-S11 验收。
- [ ] 许可证和素材授权清单齐全，旧页面回退已实际演练。

## 9. 提交拆分与估算

提交建议：

```text
S00 docs: freeze studio baseline and migration inventory
S01 fix: secure media fetching and prevent duplicate generation
S01 fix: scope file tokens and coordinate media cleanup
S01 fix: retire provider clients safely
S02 feat: add Yukina-based studio shell
S03 feat: expose provider capabilities and validated forms
S04 feat: persist shared generation jobs and add studio API
S05 feat: integrate image workbench
S06 feat: integrate video workbench
S07 feat: migrate personas presets and settings
S08 feat: unify assets history and canvas projects
S09 feat: integrate prompt tools and guarded agent workflow
S10 feat: integrate GIF workspace
S11 feat: integrate sandboxed design workspace
S12 release: enable unified studio with legacy fallback
```

估算仅用于安排，不是交付保证：

- S00-S02：约 5-9 人日。
- S03-S07：约 12-20 人日。
- S08-S11：约 15-25 人日。
- S12 与发布检查：约 4-7 人日（含打包、迁移、回退，不代表专门编写测试的工期）。
- 合计约 36-61 人日；未知的宿主鉴权、许可证审批和真实商家接口问题可能延长。

可并行：契约冻结后，图片工作台与素材页可并行；安全修复和许可清单可并行。
不可并行抢改：配置持久化、任务状态机、数据库迁移和 provider 生命周期须指定单一负责人。

## 10. 第一位执行者现在应该做什么

1. 完成 S00 的 Git 基线、备份、许可证确认和全量功能清单。
2. 原样跑一次现有测试，把环境和结果写入 implementation-log.md。
3. 先为视频预解析安全漏洞和重复提交风险写失败测试。
4. 只修 S01，不修改页面。
5. 验收 S01 后实施 S02 的最小 Yukina 外壳，在真实 AstrBot 中验证挂载与鉴权。
6. 把能打开的测试地址、桌面和手机两张截图、接口连通结果交给用户确认。
7. 再依次执行其余阶段，不直接把 Nova 仓库复制进插件。

## 11. 参考来源

- Yukina：https://github.com/WhitePaper233/yukina
- Nova：https://github.com/tianjiangqiji/nova-image-studio
- Astro React 集成：https://docs.astro.build/en/guides/integrations-guide/react/
- 许可原文以固定源码快照内 LICENSE 为准；本文不替代许可兼容性确认。

已检查的来源文件包括：

- Yukina：astro.config.mjs、src/layouts/BaseLayout.astro、package.json、LICENSE。
- Nova：frontend/package.json、frontend/next.config.ts、frontend/src/app/page.tsx、
  frontend/src/components 下的工作台、画布、GIF、切图组件与根 LICENSE。
- 插件：handlers/pages_api.py、core/pages_config_service.py、provider_registry、
  task_manager、image_history、video_manager、参考图与生成路由。

本方案不是“所有代码都已审查完毕”的声明。每阶段开始前仍需追踪其实际依赖，
若来源版本或宿主接口变化，先更新契约与验收，不在业务组件中临时打补丁绕过。
