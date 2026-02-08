# Call Me 插件 ASR 配置指南（推荐 Sherpa）

本文是 `plugins/call_me` 的 ASR 用户文档，目标是让你稳定跑通本地语音识别。  
结论先说：**推荐优先使用 Sherpa + Zipformer-CTC**（性能更高、延迟更低）。

---

## 1. 当前插件支持哪些 ASR

`plugins/call_me/config.toml` 里 `[asr].type` 支持：

1. `sherpa`（推荐，本地流式）
2. `mock`（测试用）
3. 其他值（按 HTTP ASR 处理，如 FunASR/OpenAI 风格接口）

当前建议：

- 日常使用：`sherpa`
- 自动化测试：`mock`

---

## 2. Sherpa 模型获取（推荐 Zipformer-CTC）

模型索引页（官方）：

- https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html

## 2.1 Zipformer-CTC（推荐）

说明：更高性能、延迟更低；精度与模型体积相关。  
推荐下载：

1. 大模型（更准，内存常驻约 400M~600M）  
   https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30.tar.bz2
2. small 模型（次之，内存常驻约 200M）  
   https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01.tar.bz2

## 2.2 Zipformer-Transducer（备选）

说明：通常准确度更高，但延迟略高。  
下载：

- https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30.tar.bz2

---

## 3. 安装运行依赖（在 MaiBot 的 Python 环境中）

在运行 MaiBot 的 Python 环境安装：

```powershell
python -m pip install -U sherpa-onnx numpy
```

注意：

1. 这里是 **MaiBot 环境**，不是 GPT-SoVITS 的运行时环境。
2. 若你有多个 Python，请用实际启动 MaiBot 的那个解释器执行安装命令。

---

## 4. 下载与解压模型（Windows 示例）

建议模型目录放在插件内，便于管理，例如：

- `D:\Dev\hotfix\MaiBot\plugins\call_me\asr\`

示例（PowerShell）：

```powershell
Set-Location 'D:\Dev\hotfix\MaiBot\plugins\call_me\asr'
Invoke-WebRequest -Uri 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30.tar.bz2' -OutFile 'sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30.tar.bz2'
tar -xjf '.\sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30.tar.bz2'
```

解压后确认以下文件存在（CTC 模式）：

1. `tokens.txt`
2. `model.int8.onnx`（或模型包中对应的 CTC 模型文件名）

---

## 5. 配置方式（重点）

打开：`plugins/call_me/config.toml`

## 5.1 推荐配置：Zipformer-CTC

```toml
[asr]
type = "sherpa"
final_delay_ms = 80

[sherpa]
model_kind = "zipformer2_ctc"
tokens_path = 'D:\Dev\hotfix\MaiBot\plugins\call_me\asr\sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30\tokens.txt'
model_path = 'D:\Dev\hotfix\MaiBot\plugins\call_me\asr\sherpa-onnx-streaming-zipformer-ctc-zh-int8-2025-06-30\model.int8.onnx'
num_threads = 1
provider = "cpu"
```

说明：

1. CTC 模式只需要 `tokens_path + model_path`。
2. `encoder_path/decoder_path/joiner_path` 在 CTC 模式下不会使用。
3. `tokens_path` 与 `model_path` 建议来自同一模型目录。

## 5.2 备选配置：Transducer

```toml
[asr]
type = "sherpa"
final_delay_ms = 80

[sherpa]
model_kind = "transducer"
tokens_path = 'D:\Dev\hotfix\MaiBot\plugins\call_me\asr\sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30\tokens.txt'
encoder_path = 'D:\Dev\hotfix\MaiBot\plugins\call_me\asr\sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30\encoder-*.onnx'
decoder_path = 'D:\Dev\hotfix\MaiBot\plugins\call_me\asr\sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30\decoder-*.onnx'
joiner_path = 'D:\Dev\hotfix\MaiBot\plugins\call_me\asr\sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30\joiner-*.onnx'
num_threads = 1
provider = "cpu"
```

说明：

1. Transducer 模式需要 `tokens + encoder + decoder + joiner` 四个路径。
2. `model_path` 在 Transducer 模式下不会使用。

---

## 6. 启动与验证

1. 保存 `config.toml`。
2. 重启 MaiBot，或执行：
   - `/callme stop`
   - `/callme start`
3. 连接前端页面进行语音输入测试。

建议同时看日志，确认 Sherpa 真实加载成功：

- 成功常见日志：`[SherpaASR] Loading zipformer2_ctc model ...`
- 若失败会回退到 Mock：`falling back to MockASR`

如果出现回退，说明 Sherpa 没真正生效。

---

## 7. 性能调优建议

1. 低延迟优先：继续使用 `zipformer2_ctc`。
2. 尾字偶发吞字：适当提高 `[asr].final_delay_ms`（如 `80 -> 120`）。
3. CPU 紧张：尝试 small CTC 模型，或减少 `num_threads`。
4. 准确率优先：可尝试 Transducer（接受更高延迟）。

---

## 8. 常见问题排查

## 8.1 配置了 sherpa 但实际没生效

检查：

1. 日志是否出现 `falling back to MockASR`
2. `sherpa-onnx` / `numpy` 是否装在 MaiBot 的 Python 环境
3. 模型路径是否拼错（绝对路径最稳）

## 8.2 模型路径都填了仍失败

检查：

1. `model_kind` 与路径组合是否匹配  
   - CTC: `tokens + model_path`
   - Transducer: `tokens + encoder + decoder + joiner`
2. 文件是否真实存在、是否有读取权限
3. `tokens_path` 与模型文件是否来自同一个模型包

## 8.3 延迟偏高

优先动作：

1. 改用 Zipformer-CTC
2. 使用 small CTC 模型
3. 调小 `final_delay_ms`（不要过小，避免尾字丢失）

---

## 9. 推荐落地方案

1. 先上 `zipformer2_ctc` 大模型（2025-06-30）。
2. 若内存紧张再切 small CTC（2025-04-01）。
3. 只有在你明确需要更高精度时，再切 Transducer。

这样通常能在“速度、稳定、精度”之间取得最好的日常体验。
