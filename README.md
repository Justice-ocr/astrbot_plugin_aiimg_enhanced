<p align="center">
  <img src="./logo.png" width="112" alt="AI绘图站图标">
</p>

<h1 align="center">AI绘图站</h1>

<p align="center">
  面向 AstrBot 的多服务商 AI 绘图工作台：文生图、改图、视频、批量任务与多人设自拍，一处配置即可使用。
</p>

<p align="center">
  <strong>AstrBot &gt;= 4.16.0, &lt; 5</strong>
  · v4.5.0
  · MIT
  · <a href="https://github.com/Justice-ocr/astrbot_plugin_aiimg_enhanced">GitHub 仓库</a>
</p>

![AI绘图站功能概览](./docs/assets/readme-banner.jpg)

## 能做什么

| 能力 | 使用方式 | 说明 |
| --- | --- | --- |
| 文生图 | `/aiimg 一只窗边的橘猫 1:1` | 支持多服务商链路与失败自动兜底 |
| 改图 | 发送图片并输入 `/aiedit 改成水彩画` | 支持单图、多图和预设指令 |
| 人设自拍 | `/自拍 海边的傍晚` | 每套人设拥有独立描述与参考图组 |
| 批量任务 | `/批量4 aiimg 四季主题海报` | 并发生成，支持 LLM 规划差异化提示词 |
| 视频生成 | `/视频 云海中的列车` | 支持异步任务和首尾帧能力 |
| LLM 工具 | 在 AstrBot 中启用对应工具 | 让模型自动判断生图、改图或自拍模式 |

支持 OpenAI Images、Gemini、Gitee AI、Grok、Flow2API、Vertex AI、魔搭、即梦等多类接口。不同服务商可组合为主用与备用链路。

## 五分钟上手

### 1. 安装插件

在 AstrBot 插件市场搜索 **AI绘图站**，或使用仓库地址安装：

```text
https://github.com/Justice-ocr/astrbot_plugin_aiimg_enhanced
```

要求：

- AstrBot `>=4.16.0,<5`
- Python 依赖会随插件安装
- 当前元数据标记的已验证平台为 `aiocqhttp`

### 2. 添加服务商

打开 `AstrBot WebUI -> 插件 -> AI绘图站 -> 插件页面`，进入 **服务商**：

1. 点击 **新建服务商**。
2. 选择服务商类型。
3. 填写服务商 ID、API 地址、API Key 和模型名。
4. 保存服务商。

服务商 ID 是链路和临时指定服务商时使用的短名称，例如 `openai`、`gemini`。

#### 服务商模板与端点适配

多数模板只需要填写服务商根地址或 `/v1` 地址，插件会按模板自动拼接实际请求端点；只有 `OpenAI ImagesURL` 和 `自定义视频` 需要直接填写完整接口地址或路径。

| 服务商模板 | 适配接口 | 地址字段怎么填 | 实际请求端点 / 备注 |
| --- | --- | --- | --- |
| OpenAI Images | OpenAI Images API | `Base URL` 填根地址或 `/v1`，例如 `https://api.openai.com/v1`；也可粘贴 `/v1/images/generations`，保存后会自动归一化 | 文生图走 `/images/generations`，改图走 `/images/edits` |
| OpenAI Chat图 | OpenAI Chat Completions 多模态出图 | `Base URL` 填根地址或 `/v1`；如果网关只给 `/v1/chat/completions`，也可以直接粘贴 | 主请求走 `/chat/completions`，改图不兼容时会尝试 Images API 兜底 |
| Gemini 原生 | Google Gemini 原生 `generateContent` | `API URL` 填 `https://generativelanguage.googleapis.com`、`.../v1beta` 或 `.../v1beta/models`，模型名单独填到 `Model` | 最终请求 `.../v1beta/models/{model}:generateContent`；不要把模型名和 `:generateContent` 混到模型字段里 |
| Flow2API | Flow2API / Gemini 代理的 OpenAI Chat Completions | `API URL` 填服务根地址、`/v1` 或完整 `/v1/chat/completions` | 插件会归一化到 `/v1/chat/completions`，适合只提供 OpenAI 兼容聊天端点的 Gemini 代理 |
| Vertex AI 匿名 | Google Cloud Console 匿名 GraphQL | 通常保持默认；需要代理时填 `Proxy URL`，高级字段用于覆盖 reCAPTCHA、GraphQL API Key 或 Vertex Base API | 请求 `.../v3/entityServices/AiplatformEntityService/schemas/AIPLATFORM_GRAPHQL:batchGraphql` |
| Grok Images | xAI Images API | `Base URL` 默认 `https://api.x.ai/v1`；模型使用 `grok-imagine-image-quality` 或 `grok-imagine-image` | 文生图走 `/v1/images/generations`；改图按 xAI JSON 协议走 `/v1/images/edits`，支持最多三张独立参考图；像素尺寸会转换为 `aspect_ratio` 与 `1k/2k` |
| Grok Images 改图 | Grok Images Edit API | `Base URL` 填网关的 OpenAI 兼容根地址，例如 CCODE 的 `http://pro.ccode.vip/v1`；默认模型 `grok-imagine-image-edit` | 直接走 `/v1/images/edits`，不会调用 Chat Completions，也不会降级模型；旧的 Grok Chat图配置会按模型自动迁移 |
| Grok Chat图 | xAI Chat Completions 出图 | `Base URL` 默认 `https://api.x.ai/v1` | 请求 `/chat/completions`；适合 chat 形态的 grok imagine 网关 |
| Grok2API Images | Grok2API Images 兼容接口 | `Base URL` 填部署根地址或 `/v1` | 文生图走 `/images/generations`，改图优先走 `/images/edits`，兼容部分实现的编辑入参差异 |
| Gemini Images | Gemini 的 OpenAI Images 兼容网关 | `Base URL` 填代理提供的 OpenAI 兼容根地址或 `/v1` | 文生图走 `/images/generations`，改图走 `/images/edits` |
| Gemini Chat图 | Gemini 的 OpenAI Chat 兼容网关 | `Base URL` 填代理提供的根地址、`/v1` 或 `/v1/chat/completions` | 请求 `/chat/completions`，适合只暴露聊天接口的 Gemini 网关 |
| Gitee Images | Gitee AI 同步 Images 接口 | `Base URL` 默认 `https://ai.gitee.com/v1` | 文生图走 `/images/generations`；当前模板默认不启用改图 |
| Gitee 异步改图 | Gitee AI 异步改图接口 | `Base URL` 默认 `https://ai.gitee.com/v1` | 创建任务走 `/async/images/edits`，轮询走 `/task/{task_id}` |
| 即梦 | 即梦代理接口 | `API URL` 填代理提供的完整生成接口地址 | 插件直接 GET 这个地址，并附带 apikey、cookie、模型、比例等参数 |
| Grok 视频 | xAI Chat Completions 视频接口 | `Server URL` 默认 `https://api.x.ai` | 请求 `/v1/chat/completions`，从响应文本中提取视频 URL |
| Grok2API 视频 | Grok2API 视频接口 | `Base URL` 填部署根地址或 `/v1` | 请求 `/v1/videos` |
| Flow2API 视频 | Flow2API 视频代理 | `API URL` 填服务根地址、`/v1` 或完整 `/v1/chat/completions` | 插件会归一化到 `/v1/chat/completions`，从流式或非流式响应中提取视频 URL |
| 自定义视频 | 任意视频生成 / 轮询接口 | `Base URL` 填服务根地址；`Generate Path` 填生成路径，`Poll Path` 填轮询路径，可用 `{task_id}` 占位 | 生成请求为 `Base URL + Generate Path`；配置 `Poll Path` 后按 `Base URL + Poll Path` 轮询 |
| 魔搭 Images | 魔搭 OpenAI Images 兼容接口 | `Base URL` 填魔搭或代理提供的 OpenAI 兼容根地址或 `/v1` | 文生图走 `/images/generations`；当前模板默认不启用改图 |
| OpenAI ImagesURL | 完整 URL 直连模式 | `Full Generate URL` 填完整文生图接口，`Full Edit URL` 填完整改图接口；可用于 `/v1/images/generations`、`/v1/images/edits` 或 `/v1/responses` 类网关 | 插件不会再自动拼接路径，直接向填写的完整 URL 发请求 |

如果你拿到的是类似 `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent` 的 Gemini 原生端点，建议选择 **Gemini 原生**：`API URL` 填 `https://generativelanguage.googleapis.com` 或 `https://generativelanguage.googleapis.com/v1beta/models`，`Model` 填 `gemini-3.1-flash-image-preview`。如果服务商只提供 OpenAI 兼容的 `/v1/chat/completions`，则选择 **Gemini Chat图** 或 **Flow2API**。

### 3. 配置功能链路

进入 **功能开关**，把刚创建的服务商加入文生图、改图、自拍或视频链路，然后点击左下角 **保存更改**。

```mermaid
flowchart LR
    A["用户指令"] --> B["功能链路"]
    B --> C["主服务商"]
    C -->|失败| D["备用服务商"]
    C --> E["返回图片或视频"]
    D --> E
```

建议第一次只配置一个文生图服务商。确认 `/aiimg` 可用后，再增加改图、自拍和视频链路。

### 4. 发送第一条指令

```text
/aiimg 一只坐在窗边的橘猫，柔和晨光，细腻插画 1:1
```

需要临时绕过默认链路时，可直接指定服务商：

```text
/aiimg @openai 未来城市的雨夜
```

可用 `/服务商` 查看服务商状态，使用 `/链路` 查看当前功能链路。

## 人设与参考图

进入 **人设管理** 后：

1. 点击 **新建人设**。
2. 填写人设 ID、显示名称和人物描述。
3. 在右侧参考图栏顶部上传 JPG、PNG、WebP 或 GIF，单张不超过 20 MB。
4. 保存人设，再点击页面左下角 **保存更改**。
5. 在聊天中发送 `/人设`，使用 `/切换人设 名称` 切换。

参考图会显示在右侧面板，按原比例预览，并通过插件接口按需加载；页面同时最多加载 5 张，避免大量参考图阻塞配置初始化。上传后配置里只保存服务端路径，不再把大段 base64 图片塞进 `save_config`，因此打开配置页和保存配置都会更轻。

> 参考图中的稳定特征应清晰可见。建议使用光线自然、无遮挡、主体明确的图片，不要混用外观差异过大的角色。

## 配置页面

| 页面 | 主要内容 |
| --- | --- |
| 功能开关 | 功能启停、默认尺寸、批量并发、服务商链路 |
| 服务商 | 新建、编辑、删除服务商，按类型显示专用字段 |
| 预设指令 | 管理文生图、改图与视频预设 |
| 人设管理 | 管理人物描述、参考图组与当前启用人设 |
| 状态文案 | 自定义等待、完成和失败文案 |
| 高级配置 | 防抖、缓存、网络安全与兼容选项 |

配置保存后会立即刷新插件运行状态，通常无需重启 AstrBot。

## 维护结构

当前代码将高频变动逻辑拆成了几个独立单元：

| 文件 | 责任 |
| --- | --- |
| `pages/Settings/app.js` | Settings 页面状态、表单读写、保存和渲染编排 |
| `pages/Settings/output_sizes.js` | 分辨率选项加载、归一化和下拉框渲染 |
| `pages/Settings/persona_refs.js` | 人设参考图上传、预览、并发加载和清空操作 |
| `pages/Settings/provider_catalog.js` | 服务商类型推断、模板默认值、展示名称和视频服务商分类 |
| `pages/Settings/provider_form.js` | 服务商弹窗表单生成、字段读取和尺寸字段归一化 |
| `core/pages_config_service.py` | 配置页 payload 合并、provider 清洗和变更标记 |
| `core/persona_ref_service.py` | 参考图格式检测、保存、base64 转存和安全预览 |

修改 UI 或页面 API 时，优先在对应模块内调整，并补充 `tests/test_settings_*`、`tests/test_pages_config_service.py` 或 `tests/test_persona_ref_service.py` 的回归测试。

## 常用指令

| 指令 | 说明 |
| --- | --- |
| `/aiimg <提示词>` | 文生图；别名：`/生图`、`/画图`、`/绘图`、`/出图` |
| `/文生图 <提示词>` | 文生图及文生图预设入口 |
| `/aiedit <提示词>` | 改图；别名：`/改图`、`/图生图`、`/修图` |
| `/<预设名> [补充提示词]` | 调用自定义改图预设 |
| `/自拍 [提示词]` | 使用当前人设和参考图生成自拍 |
| `/自拍参考 查看` | 查看命令方式设置的自拍参考图 |
| `/视频 <提示词>` | 生成视频 |
| `/批量N <模式> <提示词>` | 批量生成，例如 `/批量4 aiimg 四季街景` |
| `/人设` | 查看人设列表 |
| `/切换人设 <序号/ID/名称>` | 切换当前人设 |
| `/服务商` | 查看服务商状态 |
| `/链路` | 查看或调整功能链路 |
| `/重发图片` | 重新发送上一张生成结果 |
| `/图片历史` | 查看当前用户在当前会话最近 10 张结果的固定编号 |
| `/重发图片 #12` | 重发指定历史图片，不重新调用生成接口 |
| `/继续改图 [#12] <修改要求>` | 编辑指定历史图片；省略编号使用当前会话最新结果 |

### 图片历史与连续改图

生成结果的历史元数据保存在插件数据目录的 `image_history.sqlite3`，图片副本保存在 `history_images`。历史总量最多 100 张，超出后自动删除最旧记录和对应历史副本，不影响用户上传的参考图。聊天中的历史访问按机器人、消息来源、用户和 AstrBot 会话隔离；固定记录 ID 不重复利用，批量生成的每张结果单独记录。

```text
/图片历史
/重发图片 #12
/继续改图 #12 把背景换成雨夜街道
/继续改图 保留主体，把画面改成水彩风格
```

继续改图时，当前消息或引用中的图片优先于历史图片；如果提供的图片读取失败，不会自动换用历史图片。LLM 图片工具也支持 `history_id`；未指定编号时，“把上一张背景换掉”之类明确指向上一张图片的请求可使用最近 30 分钟内的结果。明确的自拍请求仍沿用原来的自拍逻辑。

历史副本不受普通图片缓存清理影响。如果历史文件被手动删除，页面会显示“已过期”；重发旧图不会改变生成时间或“最新结果”。生成成功但发送失败的图片也会记录，可随后通过重发命令再次发送。升级前的内存重发记录不会迁移到新历史。

### Web 生成历史

在插件页面左侧进入 **生成历史**，可浏览全局最近 100 张图片，搜索提示词、翻页、查看详情、复制提示词和下载原图。每张卡片显示生成会话和生成时间；详情补充用户、消息来源、会话 ID 和机器人信息。时间按浏览器本地时区显示。

图片按生成时间倒序排列，页面序号从 1 开始，1 为最新结果；新增图片后序号会变化。聊天命令使用详情中的固定 **记录 ID**，不是页面序号。搜索保留图片在全局历史中的序号。Web 管理页面通过 AstrBot 已认证的插件 API 查看所有会话，聊天命令仍只能读取当前用户当前会话的记录。

### 会话人设与参考图角色

`/切换人设 名称` 只修改当前机器人、消息来源及 AstrBot 会话的人设。同一群聊会话中的用户共用此选择，不影响其他群聊、私聊或新建的 AstrBot 会话。`/切换人设 默认` 恢复跟随全局默认；`/人设` 显示当前会话生效的人设。选择保存在 `session_personas.sqlite3`，重启后保留；被删除的人设自动回退全局默认。

Web **人设管理 → 会话人设** 可以调整已记录的会话，选择立即保存，无需点击“保存更改”。下方人设列表中的“设为默认”只调整全局默认，不覆盖会话独立选择。每次生成在开始时固定人设快照，中途切换或修改人设只影响后续任务。

编辑人设时，每张参考图下方可指定 **身份、服装、姿势、场景**。旧参考图默认属于身份。自拍至少需要一张可读取的身份图；读取失败的图片会跳过，职责说明按实际提交的图片重新编号。用户当次附带的图片作为补充素材，不自动替换身份。角色分工通过提示词传达，最终遵循程度、独立参考图数量和拼图兼容行为取决于服务商，并非所有模型都有原生角色控制能力。

### 任务管理

Web **任务管理** 展示图片、批量与后台视频任务的会话、用户、时间、人设及已生成/已发送数量，支持准备、生成、下载、发送、完成、部分完成、失败与取消状态。页面打开时每 3 秒刷新；批量任务显示整体当前活动阶段，可能同时有多张图片处于不同阶段。

- `/任务列表`：查看当前用户当前会话最近 10 个任务。
- `/取消任务 任务ID`：请求取消指定任务；Web 管理员也可取消任务。
- 取消会停止本地等待、后续发送及备用服务商尝试，并释放并发名额；不能保证上游停止生成或退款。已生成的历史图片不会因取消而删除，已经发出的消息不会撤回。

任务列表为当前插件运行期间的内存状态，最多保留 100 条记录（执行中的任务不淘汰）；插件重载会停止执行中的本地任务，列表不跨重启恢复。当前版本沿用已有并发限制，超额请求不会自动排队，也不会自动重试付费生成。任务状态中的“完成”指结果发送成功，不代表上游支持进度百分比查询。

## 常见问题

### 配置页面一直加载

先确认 AstrBot 版本符合要求，再重载插件并刷新浏览器。参考图预览使用懒加载，不会在读取主配置前一次性加载全部图片。

### 上传参考图显示 `Network Error`

- 确认插件已更新到包含上传桥接回退的版本，并在更新后重载插件。
- 使用 JPG、JPEG、PNG、WebP 或 GIF，单张不超过 20 MB。
- 从 AstrBot 插件详情页进入配置，不要单独打开 `pages/Settings/index.html` 静态文件。
- 检查反向代理是否允许 POST 请求体，并适当提高请求体大小限制。
- 如果 multipart 上传被 Pages Bridge 或代理拦截，页面会自动回退到 base64 上传接口，仍然只在配置中保留服务端图片路径。

### 参考图路径存在但预览失败

容器内路径必须在当前 AstrBot 实例中真实存在。浏览器不能直接读取服务器本地路径，预览由插件接口转换后返回；迁移 AstrBot 数据目录后需要同步迁移 `plugin_data/astrbot_plugin_aiimg_enhanced/persona_refs`。

### 服务商配置正确但生成失败

使用 `/服务商` 和 `/链路` 检查启用状态；再查看 AstrBot 日志中的实际 HTTP 状态码。兼容 OpenAI 的接口还需要确认 API 地址是否包含正确的版本路径。

## 项目信息

- 维护者：[Justice-ocr](https://github.com/Justice-ocr)
- 仓库：[Justice-ocr/astrbot_plugin_aiimg_enhanced](https://github.com/Justice-ocr/astrbot_plugin_aiimg_enhanced)
- 问题反馈：[GitHub Issues](https://github.com/Justice-ocr/astrbot_plugin_aiimg_enhanced/issues)
- 开源协议：MIT

## 致谢

- 原版插件：[astrbot_plugin_gitee_aiimg](https://github.com/muyouzhi6/astrbot_plugin_gitee_aiimg)，作者木有知、Zhalslar
- 配置页面参考：[astrbot_plugin_omnidraw](https://github.com/diaomin66/astrbot_plugin_omnidraw)，作者雪碧bir

本项目是在原有工作基础上的持续增强与维护，感谢相关作者和社区贡献者。
