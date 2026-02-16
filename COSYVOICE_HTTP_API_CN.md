# Call Me 插件 CosyVoice HTTP 对接文档

本文档说明 `plugins/call_me` 在 `tts.type = "cosyvoice_http"` 时，如何请求外部 CosyVoice FastAPI 服务，以及插件内部如何处理返回音频。

## 1. 适用范围

- 插件：`plugins/call_me`
- TTS Provider：`cosyvoice_http`
- 对接协议：CosyVoice 官方 `runtime/python/fastapi/server.py` 风格接口
- 请求方式：`HTTP POST + multipart/form-data`

不包含：
- MLX OpenAI `/v1/audio/speech` 协议
- WebSocket TTS 协议

## 2. 配置项定义（`config.toml`）

位于 `[tts]`：

```toml
[tts]
type = "cosyvoice_http"
api_url = "http://127.0.0.1:50000"

cosyvoice_mode = "cross_lingual" # "cross_lingual" / "zero_shot"
cosyvoice_ref_audio_path = "D:\\CosyVoice\\asset\\zero_shot_prompt.wav"
cosyvoice_ref_text = ""           # zero_shot 模式必填
cosyvoice_sample_rate = 22050

stream_chunk_size = 8192
connect_timeout_sec = 3.0
read_timeout_sec = 20.0
total_timeout_sec = 0.0
conn_limit = 32
```

字段含义：

- `api_url`：CosyVoice 服务根地址
- `cosyvoice_mode`：请求模式
- `cosyvoice_ref_audio_path`：参考音频本地路径，作为 `prompt_wav` 上传
- `cosyvoice_ref_text`：仅 `zero_shot` 时上传为 `prompt_text`
- `cosyvoice_sample_rate`：服务端返回原始 PCM 时，插件封装 WAV 所用采样率

## 3. 外部接口映射

`cosyvoice_mode` 与目标端点映射如下：

- `cross_lingual` -> `POST {api_url}/inference_cross_lingual`
- `zero_shot` -> `POST {api_url}/inference_zero_shot`

请求体类型统一为 `multipart/form-data`。

## 4. 请求体字段

公共字段：

- `tts_text`：待合成文本
- `prompt_wav`：参考音频文件（二进制上传）

附加字段：

- `prompt_text`：仅 `zero_shot` 模式发送

插件字段到表单字段映射：

- 文本参数：`text` -> `tts_text`
- 参考音频路径：`cosyvoice_ref_audio_path` -> 读取文件后上传到 `prompt_wav`
- 参考文本：`cosyvoice_ref_text` -> `prompt_text`（仅 zero_shot）

## 5. 请求流程（插件侧）

1. 读取 `[tts]` 配置并校验模式、必填项和文件存在性。
2. 根据模式拼接 endpoint。
3. 构造 `aiohttp.FormData()`，填入 `tts_text/prompt_wav/(prompt_text)`。
4. 执行 `session.post(endpoint, data=form)`。
5. 按分块读取响应体，产出音频 bytes。

## 6. 流式与非流式行为

### 6.1 主路径：流式读取

`synthesize_stream()` 会走 CosyVoice 分支并持续读取：

- `resp.content.iter_chunked(stream_chunk_size)`
- 每个非空 chunk 立即向上层产出

该路径用于实时通话主链路（优先低首包延迟）。

### 6.2 兜底路径：整包读取

`synthesize()` 会：

- 用同样 endpoint + form 请求
- `await resp.read()` 一次性读取完整响应
- 若返回不是 WAV，则按 `cosyvoice_sample_rate` 封装成 WAV

该路径用于流式无音频时的兜底。

## 7. 响应数据处理

CosyVoice FastAPI 常见返回是原始 PCM16 字节流。插件在发送给前端前会：

1. 聚合一定字节数（首包较小，后续更大）
2. 判断是否已是 WAV
3. 若是 PCM，则封装成可独立播放的 WAV chunk
4. 通过 WebSocket 下发：
   - `type = "tts.audio_chunk"`
   - `data.chunk = base64(wav_chunk)`
   - `data.sample_rate = stream_sample_rate`

当 `tts.type == "cosyvoice_http"` 且 chunk 不是 WAV 时，默认优先用 `tts.cosyvoice_sample_rate` 作为采样率。

## 8. 错误语义

配置错误（请求前）：

- `cosyvoice_mode` 非法
- 缺少 `api_url`
- 缺少 `cosyvoice_ref_audio_path`
- `zero_shot` 缺少 `cosyvoice_ref_text`
- 参考音频路径不存在

请求错误（请求中）：

- HTTP 状态码非 200：记录 warning，流式路径返回空
- 网络异常/超时：记录 warning，流式路径返回空
- 兜底请求失败：返回 `None`

## 9. 连通性探测（配置向导）

配置向导的 `test-connectivity` 会根据模式探测：

- `cross_lingual`：`GET/HTTP probe {api_url}/inference_cross_lingual`
- `zero_shot`：`GET/HTTP probe {api_url}/inference_zero_shot`

用于快速判断服务地址可达性（不是完整合成自检）。

## 10. curl 示例

### 10.1 cross_lingual

```bash
curl -X POST "http://127.0.0.1:50000/inference_cross_lingual" \
  -F "tts_text=你好，这是一个测试" \
  -F "prompt_wav=@D:/CosyVoice/asset/zero_shot_prompt.wav;type=application/octet-stream" \
  --output out_cross_lingual.pcm
```

### 10.2 zero_shot

```bash
curl -X POST "http://127.0.0.1:50000/inference_zero_shot" \
  -F "tts_text=你好，这是一个测试" \
  -F "prompt_text=这是参考音频对应文本" \
  -F "prompt_wav=@D:/CosyVoice/asset/zero_shot_prompt.wav;type=application/octet-stream" \
  --output out_zero_shot.pcm
```

## 11. 关键代码定位

- TTS 配置解析与校验：`plugins/call_me/core/tts_manager.py`
- CosyVoice endpoint 选择：`plugins/call_me/core/tts_manager.py`
- FormData 构建：`plugins/call_me/core/tts_manager.py`
- 流式请求：`plugins/call_me/core/tts_manager.py`
- 非流式兜底：`plugins/call_me/core/tts_manager.py`
- 配置向导校验与连通性：`plugins/call_me/core/config_manager.py`
- 前端快速配置入口：`plugins/call_me/frontend/src/routes/routes.settings.voice-setup.tsx`

