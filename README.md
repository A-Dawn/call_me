# 📞 Call Me - 实时语音通话插件使用手册

> 如果项目对你有用，烦请点个 star，这对我非常重要！
>
> 如果你希望我针对你的需求进行适配或扩展，请先给仓库点一个 Star，并在 issue 中描述你的环境与需要功能。

## 1. 简介

`Call Me` 是为 MaiBot 设计的高性能实时语音通话插件。它允许用户通过 WebSocket 与机器人进行全双工语音对话，集成了 VAD (语音活动检测)、TTS (语音合成) 和 LLM (大模型) 能力。

主要特性：

- **独立服务**: 运行在独立的 FastAPI 进程中 (默认端口 8989)，不阻塞主程序。
- **低延迟**: 优化的流式传输协议。
- **可视化管理**: 提供 REST API 管理立绘和资源。
- **热插拔**: 支持通过指令动态启停服务。

立绘工作台白痴版（一步一步部署）：[`AVATAR_STUDIO_USER_GUIDE_LITE_CN.md`](./AVATAR_STUDIO_USER_GUIDE_LITE_CN.md)  

立绘工作台详细版：[`AVATAR_STUDIO_USER_GUIDE_CN.md`](./AVATAR_STUDIO_USER_GUIDE_CN.md)

TTS 配置与部署指南（GPT-SoVITS）：[`TTS_USER_GUIDE_CN.md`](./TTS_USER_GUIDE_CN.md)

TTS 配置与部署指南（豆包双向流式）：[`DOUBAO_TTS_USER_GUIDE_CN.md`](./DOUBAO_TTS_USER_GUIDE_CN.md)

ASR 配置与部署指南（推荐 Sherpa）：[`ASR_USER_GUIDE_CN.md`](./ASR_USER_GUIDE_CN.md)

## 2. 快速开始

### 2.1 启用插件

1. 确保插件已安装在 `plugins/call_me` 目录。
2. 重启 MaiBot，配置文件 `plugins/call_me/config.toml` 将自动生成。
3. 插件服务会自动随 Bot 启动。

### 2.2 验证运行

在浏览器访问: `http://127.0.0.1:8989/docs`
如果能看到 Swagger UI 界面，说明服务运行正常。

### 2.3 外部依赖 (必读)

本插件已经内置前端页面（`/` 可直接访问），外部依赖主要是 TTS 与 ASR：

1.  **TTS 服务 (语音合成)**:
    - 支持: **GPT-SoVITS**、**豆包双向流式 TTS** 或 **CosyVoice HTTP(FastAPI runtime)**。
    - 要求: 需配置对应 provider 地址与鉴权参数。

2.  **ASR 服务 (语音转文本)**:
    - 主推: **Sherpa**（本地实时识别，延迟稳定）。
    - 推荐优先使用 `zipformer2_ctc` 模型。

### 2.4 最低配置要求（按 TTS 方案区分）

#### 2.4.1 本地 GPT-SoVITS + Sherpa（默认高质量方案）

- `TTS = GPT-SoVITS`（`[tts].type = "sovits"`）
- `ASR = Sherpa Zipformer-CTC`（`[asr].type = "sherpa"`）
- 浏览器前端 + 本插件实时 WS 通话

有 GPU（推荐，满足实时体验）：

- CPU: `>= 6` 物理核（建议 `>= 8`）
- 内存: `>= 16 GB`（建议 `24 GB`）
- GPU: NVIDIA 显存 `>= 6 GB`（建议 `8 GB`）
- 磁盘: 建议预留 `>= 15 GB`（模型 + 运行缓存 + 日志）

说明：

- 这是“可稳定日常使用”的最低线。
- 若想更低延迟、更高并发，建议直接上 `8C/16T + 32GB + 8~12GB VRAM`。

无 GPU（可运行，不推荐实时主用）：

- CPU: `>= 8` 物理核（建议 `>= 12`）
- 内存: `>= 24 GB`（建议 `32 GB`）
- 磁盘: 建议预留 `>= 15 GB`

说明：

- 纯 CPU 方案通常可以跑通，但延迟会明显升高，实时对话体验会下降。
- 无 GPU 场景更建议：本机跑 Sherpa ASR，TTS 使用豆包双向流式服务。

#### 2.4.2 豆包双向流式 TTS + Sherpa（低本地占用方案）

- `TTS = 豆包`（`[tts].type = "doubao_ws"`，远端合成）
- `ASR = Sherpa Zipformer-CTC`（本地）
- 本地资源主要消耗在 Sherpa ASR，内存占用显著低于本地 SoVITS 方案。

建议起步配置：

- CPU: `>= 2` 物理核（建议 `>= 4`）
- 内存: `>= 4 GB`
- GPU: 非必须

### 2.5 手动控制指令

在 MaiBot 聊天窗口发送以下命令：

| 指令             | 说明                     |
| :--------------- | :----------------------- |
| `/callme status` | 查看当前后台服务运行状态 |
| `/callme stop`   | 停止后台服务 (释放端口)  |
| `/callme start`  | 启动后台服务             |

---

## 3. 配置说明 (`config.toml`)

位于 `plugins/call_me/config.toml`。修改后需**重启 Bot** 或使用 `/callme stop` 然后 `/callme start` 生效。

```toml
[plugin]
enabled = true          # 插件总开关

[server]
host = "127.0.0.1"      # 监听地址 (0.0.0.0 允许局域网访问)
port = 8989             # 服务端口
cors_origins = ["*"]    # 跨域设置，开发环境建议保持 ["*"]

[vad]
# VAD (语音检测) 参数，通常保持默认即可
speech_start_ms = 150   # 检测到人声的灵敏度 (毫秒)
speech_end_ms = 800     # 判定说话结束的静音时长 (毫秒) - 调小反应快，调大不易打断
mode = "webrtc"         # 检测模式

[audio]
sample_rate = 24000     # 输出音频采样率
channels = 1            # 单声道

[tts]
type = "sovits"         # "sovits" / "doubao_ws" / "cosyvoice_http"
api_url = "http://127.0.0.1:9880"  # doubao_ws 时填写 wss 地址, cosyvoice_http 填 FastAPI 根地址
voice_id = "default"
doubao_app_key = ""
doubao_access_key = ""
doubao_resource_id = ""
doubao_voice_type = ""  # 独立字段，不复用 voice_id
cosyvoice_mode = "cross_lingual"   # "cross_lingual" / "zero_shot"
cosyvoice_ref_audio_path = ""
cosyvoice_ref_text = ""            # zero_shot 模式必填
cosyvoice_sample_rate = 22050

[asr]
type = "sherpa"         # 推荐生产使用 sherpa
api_url = "http://127.0.0.1:10095"  # 仅非 sherpa 模式生效

[sherpa]
model_kind = "zipformer2_ctc"   # 推荐 CTC 单文件模型
tokens_path = "D:/models/sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30/tokens.txt"
model_path = "D:/models/sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30/model.int8.onnx"
num_threads = 1
provider = "cpu"
```

### 3.1 TTS provider 说明

- `tts.type = "sovits"`: 走 GPT-SoVITS HTTP 接口。
- `tts.type = "doubao_ws"`: 走豆包双向流式 TTS（WebSocket）。
- `tts.type = "cosyvoice_http"`: 走 CosyVoice 官方 FastAPI 协议（`multipart/form-data` -> 原始 PCM 流）。
- `doubao_voice_type` 与 `voice_id` 独立；豆包模式只使用 `doubao_voice_type`。
- CosyVoice 模式:
  - `cross_lingual`: `/inference_cross_lingual`，需要 `cosyvoice_ref_audio_path`
  - `zero_shot`: `/inference_zero_shot`，除参考音频外还需要 `cosyvoice_ref_text`
- 豆包模式采用显式失败策略：鉴权失败、协议异常、无音频返回时直接报错，不自动回退到其他 TTS。

---

## 4. 开发者接口 (API)

### 4.1 REST API (资源管理)

完整的 API 文档请查阅 Swagger UI: `http://127.0.0.1:8989/docs`

#### 核心端点:

- `GET /api/assets`: 列出所有上传的图片资源。
- `POST /api/assets/upload`: 上传新图片 (multipart/form-data)。
- `GET /api/assets/{asset_id}/file`: 获取上传资源文件。
- `GET /api/avatar-map/active`: 获取当前情绪立绘映射。
- `PUT /api/avatar-map/bind`: 绑定情绪与立绘资源。
- `GET /api/presets/`: 获取所有立绘预设。
- `POST /api/presets/`: 创建新的立绘预设 (定义不同状态下的图片映射)。
- `GET /api/presets/{id}`: 获取指定预设详情。

### 4.2 WebSocket 协议 (实时通话)

- **连接地址**: `ws://127.0.0.1:8989/ws/call`
- **数据格式**: JSON

#### 4.2.1 握手流程

1.  **Client 发送**: `{"type": "client.hello"}`
2.  **Server 响应**: `{"type": "server.hello", "session_id": "..."}`

#### 4.2.2 客户端发送消息

- **上传音频块**:
  ```json
  {
    "type": "input.audio_chunk",
    "data": {
      "chunk": "<Base64编码的PCM音频数据>"
    }
  }
  ```
- **文本输入** (可选，用于测试):
  ```json
  {
    "type": "input.text",
    "data": {
      "text": "你好"
    }
  }
  ```
- **中断信号** (打断机器人说话):
  ```json
  { "type": "control.interrupt" }
  ```

#### 4.2.3 服务器推送消息

- **状态更新**:
  ```json
  { "type": "state.update", "state": "listening" }
  // 状态: listening (监听中), thinking (思考中), speaking (说话中)
  ```
- **TTS 音频数据**:
  ```json
  {
    "type": "tts.audio_chunk",
    "data": {
      "chunk": "<Base64编码的WAV/PCM数据>",
      "sample_rate": 24000
    }
  }
  ```
- **文本字幕**:
  ```json
  {
    "type": "tts.text_stream",
    "data": { "text": "你好，我是" }
  }
  ```

---

## 5. 常见问题 (Troubleshooting)

### Q1: 启动时提示端口被占用？

- **原因**: 可能有旧的 Python 进程未关闭，或者其他程序占用了 8989 端口。
- **解决**:
  1. 尝试发送 `/callme stop`。
  2. 修改 `config.toml` 中的 `port` 为其他值 (如 8990)，然后 `/callme start`。

### Q2: 浏览器无法录音或连接？

- **原因**: 浏览器安全策略要求麦克风权限必须在 HTTPS 或 localhost 环境下使用。
- **解决**: 如果是局域网访问 (非 localhost)，请配置 SSL 证书启用 HTTPS，或在 Chrome `chrome://flags` 中将你的 IP 添加到 `Insecure origins treated as secure`。

### Q3: 机器人说话无限打断自己？

- **原因**: 扬声器的声音被麦克风重新录入 (回声)。
- **解决**:
  1. 佩戴耳机。
  2. 使用带有硬件回声消除 (AEC) 的麦克风设备。
  3. 调大 `config.toml` 中的 `speech_start_ms` 阈值。

---

## Fork 与修改说明（Friendly Fork Policy）

本项目基于 AGPL-3.0 协议发布，允许 Fork 与衍生开发。
但我们强烈反对任何形式的“去署名 / 去来源”的再发布行为。

若您公开发布本项目的 Fork 或衍生版本，请至少做到：

保留原始版权声明、LICENSE 文件与协议文本（AGPL 要求）

在 README 或发布页明确标注来源（指向本仓库），并说明是否做了修改

为了保持项目架构的一致性与长期可维护性，我们建议优先通过 Issue 或邮件与ARC沟通后再进行公开衍生发布。

### 关于sovits模型托管：

目前项目支持sovits的模型托管，当前阶段不收取托管费用，也不主动收集用户个人信息，详情请直接联系作者 ARC