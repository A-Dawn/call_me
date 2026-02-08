# Call Me 插件 TTS 配置与部署指南（GPT-SoVITS）

本文专门讲 `plugins/call_me` 的 TTS 配置方法。  
默认场景：你使用的是 **GPT-SoVITS 一键包**，目录类似：

- `D:\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50`

注意：不同用户目录可能不同，请替换成你自己的路径。  
如果你不是一键包环境（例如 Conda/venv 自建环境），建议直接参考 GPT-SoVITS 官方项目文档。

---

## 1. 当前插件的 TTS 工作方式（先看这个）

`call_me` 当前只支持这两种 `tts.type`：

1. `sovits`：真实调用 GPT-SoVITS 的 HTTP 接口
2. `mock`：不做真实合成（测试用）

当 `type = "sovits"` 时，插件会请求：

- `GET {tts.api_url}/tts`

并携带这些参数（来自 `plugins/call_me/config.toml` 的 `[tts]`）：

- `text`
- `text_lang`
- `ref_audio_path`
- `prompt_text`
- `prompt_lang`
- `text_split_method`
- `streaming_mode`（流式时 `true`，兜底非流式时 `false`）
- `media_type=wav`

实现细节：

1. 先走流式 TTS（`tts.audio_chunk`）
2. 流式失败时会尝试兜底非流式（`tts.audio`）

补充说明：

- `voice_id` 目前在插件里已保留配置字段，但当前版本不会作为 SoVITS 请求参数发送。

---

## 2. 一键包环境启动 GPT-SoVITS（推荐做法）

在一键包环境下，**不要直接用系统 `python`**，用一键包自带解释器：

```powershell
Set-Location 'D:\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50'
.\runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

如果你在 `cmd` 下：

```bat
D:
cd \GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50
runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

启动成功后，记住地址：

- `http://127.0.0.1:9880`

---

## 3. 配置 Call Me 的 TTS

打开文件：`plugins/call_me/config.toml`

最小可用配置（按你环境替换路径）：

```toml
[tts]
type = "sovits"
api_url = "http://127.0.0.1:9880"
voice_id = "default"

connect_timeout_sec = 3.0
read_timeout_sec = 20.0
total_timeout_sec = 0.0
conn_limit = 32
stream_chunk_size = 8192

ref_audio_path = 'D:\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50\output\slicer_opt\your_ref.wav'
prompt_text = "与你的参考音频完全对应的文本"
prompt_lang = "ja"
text_lang = "zh"
text_split_method = "cut5"
```

关键点：

1. `ref_audio_path` 必须是你机器上真实存在的文件绝对路径。
2. `prompt_text` 必须和参考音频内容匹配，否则音色质量会明显下降。
3. `prompt_lang` 是参考音频语言，`text_lang` 是目标合成语言。

---

## 4. 启动顺序（避免 90% 问题）

按这个顺序来：

1. 先启动 GPT-SoVITS（第 2 节命令）
2. 再启动 MaiBot（含 call_me 插件）
3. 在聊天中执行 `/callme status`
4. 若未运行，执行 `/callme start`
5. 打开 `http://127.0.0.1:8989/` 测试通话

---

## 5. 如何确认 TTS 真在工作

最实用检查链路：

1. 前端连接成功后说一句话/发一条文本输入。
2. 进入 `设置 -> 调试诊断` 页面（`/settings/diagnostics`）。
3. 观察事件流，至少应看到：
   - `state.update -> thinking`
   - `state.update -> speaking`
   - `tts.audio_chunk`（或 `tts.audio`）

如果只有 `thinking` 没有 `speaking/tts.audio*`，基本就是 TTS 未成功。

---

## 6. 常见问题排查（按症状）

## 6.1 症状：`Connection refused` / 请求不到 `9880`

原因：SoVITS 没启动，或 `api_url` 错了。  
处理：

1. 先确认 GPT-SoVITS 控制台还在运行。
2. 检查 `tts.api_url` 是否与启动参数一致。
3. 检查端口是否冲突。

## 6.2 症状：有回复文本，但没有音频

常见原因：

1. `ref_audio_path` 不存在或无权限。
2. `prompt_text` 与参考音频不匹配导致 SoVITS 失败。
3. SoVITS 返回错误（可在 SoVITS 控制台看到详细报错）。

处理：

1. 先把 `ref_audio_path` 换成一个确定存在、短且干净的参考音频。
2. 把 `prompt_text` 改成与该音频完全一致的文本。
3. 重启 SoVITS 与 call_me 服务。

## 6.3 症状：经常超时、首包慢

可调项（`[tts]`）：

1. `read_timeout_sec`：适当加大（例如 30~60）
2. `total_timeout_sec`：设为 `0.0`（表示不限制）或更大
3. `stream_chunk_size`：保持默认 8192，通常更稳

## 6.4 症状：明明装了环境却启动失败

原因：一键包环境下用了系统 Python。  
处理：必须改用一键包解释器：

- `.\runtime\python.exe ...`

---

## 7. 给不同环境用户的建议

你如果不是一键包，而是自己搭的 Python/Conda 环境，请直接参考 GPT-SoVITS 项目文档来启动 API。  
本插件侧只需要确保：

1. `tts.api_url` 正确可访问
2. `/tts` 接口参数兼容（至少本文第 1 节列出的字段）
3. `config.toml` 中 `[tts]` 的参考音频与语言配置正确

---

## 8. 最小可用检查清单

1. [ ] SoVITS 用 `runtime\python.exe` 启动
2. [ ] SoVITS 监听在 `127.0.0.1:9880`
3. [ ] `plugins/call_me/config.toml` 的 `[tts]` 已正确填写
4. [ ] `ref_audio_path` 文件真实存在
5. [ ] `/callme status` 显示运行中
6. [ ] 前端能看到 `tts.audio_chunk` 或 `tts.audio`

做到这 6 条，TTS 基本就稳定可用。
