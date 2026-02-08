# Call Me 使用与架构文档

本文档面向 `plugins/call_me` 插件的维护者与集成开发者，覆盖：
- 架构分层与核心调用链
- 部署与启动方式
- 配置项说明与调优建议
- WebSocket 协议与 REST API 用法
- 常见故障排查

## 1. 插件定位

`call_me` 是 MaiBot 的实时语音通话插件，提供：
- FastAPI HTTP/WS 服务（默认 `127.0.0.1:8989`）
- 流式语音通话链路（VAD -> ASR -> LLM -> TTS）
- 情绪驱动立绘映射（avatar map）
- 资源与预设管理 API
- 前端控制台（位于 `plugins/call_me/frontend`，构建产物在 `plugins/call_me/static`）

## 2. 目录总览

```text
plugins/call_me/
  plugin.py                 # 插件注册入口
  api.py                    # FastAPI app 入口
  websocket_handler.py      # WS 主协议与语音流程
  config.py                 # 配置 schema
  config.toml               # 运行配置
  database.py               # SQLite/SQLAlchemy 初始化
  models.py                 # 数据模型
  core/
    service.py              # Uvicorn 后台服务管理
    handlers.py             # ON_START / ON_STOP
    commands.py             # /callme start|stop|status
    session_manager.py      # 会话上下文 + 并发控制
    state_machine.py        # 通话状态机
    vad.py                  # VAD 逻辑
    asr_adapter.py          # ASR 适配层（mock/http/sherpa）
    llm_adapter.py          # LLM 流式适配
    tts_manager.py          # TTS 适配（SoVITS/mock）
    text_chunker.py         # LLM 输出分句给 TTS
    emotion.py              # 情绪标签解析/推断
    prompt_builder.py       # system prompt 构建
    prethink.py             # 预思考 prompt/清洗
  routers/
    assets.py               # 资源上传/查询/删除
    avatar_map.py           # 情绪->资源绑定
    presets.py              # 预设管理
  frontend/                 # React 前端
  static/                   # 前端构建产物
```

## 3. 架构分层

### 3.1 生命周期层（Plugin System）

- 插件入口：`plugin.py`
- 组件注册：
  - `CallMeStartHandler`（ON_START）
  - `CallMeStopHandler`（ON_STOP）
  - `CallMeCommand`（`/callme start|stop|status`）
- 服务实例：`core/service.py` 中 `call_me_service`（单例）

职责：将 `call_me` 作为 MaiBot 插件接入，负责服务启停与配置注入。

### 3.2 服务层（FastAPI）

- 入口：`api.py`
- 生命周期：
  - 启动时：加载 standalone 配置（必要时）、初始化数据库
  - 退出时：关闭 TTS HTTP 会话、关闭数据库
- 路由：
  - REST：`/api/assets`、`/api/avatar-map`、`/api/presets`
  - WS：`/ws/call`
- 静态资源：`/` 与 `/assets`

职责：承载管理 API、实时 WS、前端页面分发。

### 3.3 会话编排层（Session + State）

- `SessionContext`：每条 WS 连接一个上下文
- 核心并发控制：
  - `process_lock`：同会话一次只跑一条完整轮次流水线
  - `cancel_event + tracked_tasks`：支持抢占式打断
- 状态机：`idle/listening/thinking/speaking/interrupted`

职责：保证一条通话链路内状态一致、可打断、可回收。

### 3.4 实时语音处理层

- VAD：`core/vad.py`
- ASR：`core/asr_adapter.py`
- LLM：`core/llm_adapter.py`
- Chunking：`core/text_chunker.py`
- TTS：`core/tts_manager.py`
- Emotion：`core/emotion.py`

职责：把音频输入转换为文本理解，再转为音频输出并驱动表情状态。

### 3.5 数据与资源层

- SQLite DB：`call_me.db`
- 模型：`models.py`
  - `assets`
  - `avatar_maps`
  - `presets` / `preset_rules`
  - `tts_providers`

职责：存储立绘资源、映射关系和预设规则。

## 4. 核心时序（语音一轮）

### 4.1 握手

1. 客户端连接 `ws://host:port/ws/call`
2. 客户端发送 `client.hello`
3. 服务端返回：
   - `server.hello`
   - `client.config`（播放参数）
   - `avatar.state`（默认 neutral）

### 4.2 语音输入到语音输出

1. 客户端按 20ms chunk 推送 `input.audio_chunk`（Base64 PCM16）
2. 服务端 VAD 检测：
   - `start`：启动/重置 ASR stream，回灌 pre-roll 语音，必要时打断当前播报
   - `end`：触发 ASR final，进入调度
3. `schedule_turn`：
   - 若前一轮未结束，先取消并等待清理
   - 写入用户历史
   - 状态 -> `thinking`
4. `process_turn`：
   - 构建 prompt（system + history + 可选 prethink hint）
   - LLM 流式生成
   - 文本分句并并发送入 TTS 队列
   - 推送 `tts.text_stream` + `tts.audio_chunk`
   - 状态 -> `speaking` -> `listening`
5. 轮次结束后：异步触发 prethink（下一轮预测）

### 4.3 打断机制

- 客户端可主动发 `control.interrupt`
- 或在服务端 `speaking` 阶段检测到新 speech 时自动 barge-in
- 行为：
  - 置 cancel token
  - 取消 tracked tasks
  - 状态推送 `interrupted`

## 5. 配置说明（`config.toml`）

### 5.1 plugin

- `enabled`：插件总开关
- `config_version`：配置版本

### 5.2 server

- `host`：监听地址（局域网请配 `0.0.0.0`）
- `port`：监听端口（默认 8989）
- `cors_origins`：跨域来源

### 5.3 vad

- `mode`：`webrtc` / `silero` / `energy`（当前代码主用 webrtc/energy）
- `speech_start_ms`：起说话阈值
- `speech_end_ms`：结束说话阈值
- `pre_roll_ms`：句首预缓冲，减轻首字丢失
- `pre_start_silence_tolerance_ms`：起说话前静默容忍
- `energy_threshold`：能量 VAD 阈值
- `webrtc_aggressiveness`：WebRTC 灵敏度（0-3）

### 5.4 asr

- `type`：`mock` / `sherpa` / 其他（走 HTTPASR）
- `api_url`：HTTP ASR 地址（非 sherpa 时）
- `final_delay_ms`：VAD end 后等待时间，减少尾字丢失

### 5.5 sherpa

- `model_kind`：`transducer` 或 `zipformer2_ctc`
- `tokens_path` / `model_path` 或 `encoder_path+decoder_path+joiner_path`
- `num_threads`、`provider`

### 5.6 tts

- `type`：`sovits` / `mock`
- `api_url`：SoVITS API 地址（默认 `http://127.0.0.1:9880`）
- `voice_id`：默认音色 ID
- `ref_audio_path`、`prompt_text`、`prompt_lang`、`text_lang`、`text_split_method`

### 5.7 llm

- `model_name`：支持分号优先级串（如 `utils.gemini-3-flash;replyer`）
- `history_window_messages`：主回复历史窗口消息数

### 5.8 prethink

- `enabled`：是否启用预思考
- `model_name`：可单独指定预思考模型
- `timeout_ms`、`max_history_messages`、`max_output_chars`、`min_user_text_chars`

### 5.9 audio

- `sample_rate` / `channels`
- `playback_startup_buffer_ms`
- `playback_startup_max_wait_ms`
- `playback_schedule_lead_ms`

## 6. 运行与部署

### 6.1 随 MaiBot 启动

- 确认 `plugin.enabled = true`
- Bot 启动后 ON_START 自动拉起服务

### 6.2 手动控制

在 MaiBot 对话中发送：
- `/callme start`
- `/callme stop`
- `/callme status`

### 6.3 独立调试启动

```bash
uvicorn plugins.call_me.api:app --host 127.0.0.1 --port 8989
```

说明：`api.py` 带有 standalone 配置兜底，会在 service 尚未注入配置时读取 `config.toml`。

### 6.4 前端开发与构建

```bash
cd plugins/call_me/frontend
bun install
bun run dev
```

可通过环境变量覆盖后端地址：

```bash
VITE_CALL_ME_BASE_URL=http://127.0.0.1:8989 bun run dev
```

构建：

```bash
bun run build
```

构建产物输出到 `plugins/call_me/static`。

## 7. WebSocket 协议

连接地址：`ws://127.0.0.1:8989/ws/call`

### 7.1 Client -> Server

#### `client.hello`

```json
{"type":"client.hello"}
```

#### `input.audio_chunk`

```json
{
  "type": "input.audio_chunk",
  "data": {"chunk": "<base64_pcm16>"}
}
```

建议音频：16kHz / mono / PCM16 / 20ms 每包。

#### `input.text`

```json
{
  "type": "input.text",
  "data": {"text": "你好"}
}
```

#### `control.interrupt`

```json
{"type":"control.interrupt"}
```

### 7.2 Server -> Client

#### 握手与配置

- `server.hello`
- `client.config`
- `avatar.state`

#### 状态

```json
{"type":"state.update","state":"thinking"}
```

状态值：`thinking` / `speaking` / `listening` / `interrupted`

#### ASR 文本

```json
{"type":"input.text_update","text":"...","is_final":false}
```

#### TTS 文本流

```json
{"type":"tts.text_stream","seq":1,"data":{"seq":1,"text":"..."}}
```

#### TTS 音频流

```json
{
  "type": "tts.audio_chunk",
  "seq": 1,
  "is_final": false,
  "data": {
    "chunk": "<base64_wav>",
    "sample_rate": 24000
  }
}
```

#### 错误

```json
{"type":"error","message":"..."}
```

## 8. REST API 速查

### 8.1 Assets

- `POST /api/assets/upload`
- `GET /api/assets/`
- `GET /api/assets/{asset_id}/file`
- `DELETE /api/assets/{asset_id}`

### 8.2 Avatar Map

- `GET /api/avatar-map/active`
- `PUT /api/avatar-map/active`
- `PUT /api/avatar-map/bind`
- `DELETE /api/avatar-map/bind/{emotion}`

### 8.3 Presets

- `GET /api/presets/`
- `POST /api/presets/`
- `GET /api/presets/{preset_id}`
- `PATCH /api/presets/{preset_id}`
- `DELETE /api/presets/{preset_id}`
- `POST /api/presets/{preset_id}/rules`

## 9. 前端集成要点

- 核心状态在 `frontend/src/state/call.ts`
- `useCallSession` 负责：
  - WS 连接
  - 麦克风采集（48k -> 16k 下采样）
  - 音频分包上传
  - 流式音频排队播放
- `useAvatarManager` 负责：
  - 情绪立绘上传
  - 情绪绑定/解绑
  - 默认映射加载

## 10. 调优建议

### 10.1 首字被截断

- 增加 `vad.pre_roll_ms`（例如 420 -> 520）
- 适当增加 `vad.pre_start_silence_tolerance_ms`

### 10.2 尾字吞字

- 增加 `asr.final_delay_ms`（例如 80 -> 120）

### 10.3 回声导致误触发/自打断

- 佩戴耳机，减少回采
- 提高 `vad.webrtc_aggressiveness`
- 能量模式下提高 `vad.energy_threshold`

### 10.4 播放断续

- 提高 `audio.playback_startup_buffer_ms`
- 提高 `audio.playback_startup_max_wait_ms`
- 适当调大 `audio.playback_schedule_lead_ms`

## 11. 常见问题

### Q1: `/docs` 正常但语音无返回

排查：
1. 看 WS 是否收到 `server.hello`
2. 看是否有 `state.update thinking`
3. 看是否有 `tts.audio_chunk`
4. 检查 `tts.type` 与 `tts.api_url`

### Q2: Sherpa 无法识别

排查：
1. `asr.type = "sherpa"`
2. `tokens/model` 路径是否存在且对应同一模型包
3. `model_kind` 与配置文件组合是否匹配
4. 若加载失败，代码会回退到 `MockASR`

### Q3: 端口占用

- 修改 `server.port`
- 或先执行 `/callme stop`

## 12. 依赖说明

当前 `requirements.txt` 仅列出：
- `sqlalchemy`
- `aiosqlite`

实际运行还需要（按功能启用）：
- `fastapi`
- `uvicorn`
- `aiohttp`
- `webrtcvad`（若用 webrtc VAD）
- `sherpa_onnx` + `numpy`（若用 sherpa）

## 13. 测试建议

可参考：
- `plugins/test/call_me/TEST_PLAN_CN.md`
- `plugins/test/call_me/frontend/tests-e2e/index.spec.ts`
- `plugins/test/call_me/frontend/scripts/scripts_callme_boundary_e2e.mjs`
- `plugins/test/call_me/frontend/scripts/scripts_callme_concurrent_stress_fast.mjs`

建议至少覆盖：
1. 基础健康检查 (`/health`)
2. WS 握手与状态流转
3. 文本输入链路 (`input.text`)
4. 音频输入链路 (`input.audio_chunk`)
5. 打断行为 (`control.interrupt`)
6. Avatar map 绑定与删除一致性

---

最后更新：2026-02-07
