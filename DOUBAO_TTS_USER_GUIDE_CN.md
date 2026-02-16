# Call Me 插件豆包 TTS 配置指南（双向流式）

本文说明如何在 `plugins/call_me` 中配置豆包双向流式 TTS（`tts.type = "doubao_ws"`）。

## 1. 官方入口

- 帮助文档（双向流式 TTS）：  
  `https://www.volcengine.com/docs/6561/1329505?lang=zh`
- 语音合成 1.0 控制台：  
  `https://console.volcengine.com/speech/service/10007`
- 语音合成 2.0 控制台：  
  `https://console.volcengine.com/speech/service/10035`
- 声音复刻 2.0 控制台：  
  `https://console.volcengine.com/speech/service/10036`

你可以在控制台获取：

- `doubao_app_key`
- `doubao_access_key`
- `doubao_voice_type`

## 2. 配置字段对应关系

`plugins/call_me/config.toml` 中 `[tts]` 的豆包字段与协议字段关系如下：

- `doubao_app_key` -> 请求头 `X-Api-App-Key`
- `doubao_access_key` -> 请求头 `X-Api-Access-Key`
- `doubao_resource_id` -> 请求头 `X-Api-Resource-Id`
- `doubao_voice_type` -> 请求体 `req_params.speaker`

注意：

- `voice_id` 是历史兼容字段，豆包模式下不用于选音色。
- `doubao_audio_format` 当前实现只支持 `pcm`。

## 3. 可直接使用的配置模板

```toml
[tts]
type = "doubao_ws"
api_url = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

# 控制台获取
doubao_app_key = "你的AppKey"
doubao_access_key = "你的AccessKey"
doubao_resource_id = "seed-tts-2.0"
doubao_voice_type = "S_0hGlbMIP1"

# 建议保持默认
doubao_namespace = "BidirectionalTTS"
doubao_audio_format = "pcm"
doubao_sample_rate = 24000
doubao_enable_timestamp = false
doubao_disable_markdown_filter = false
```

## 4. 模型类型/资源类型填写说明

你在帮助页看到的以下类型：

- 豆包语音合成模型 1.0：`seed-tts-1.0`、`seed-tts-1.0-concurr`
- 豆包语音合成模型 2.0：`seed-tts-2.0`
- 声音复刻：`seed-icl-1.0`、`seed-icl-1.0-concurr`、`seed-icl-2.0`

建议填写到 `doubao_resource_id`。

`doubao_voice_type` 需要填写具体音色（speaker）ID，例如 `S_0hGlbMIP1`。  
如果 `resource_id` 与 `doubao_voice_type` 不属于同一资源体系，会报错：

- `resource ID is mismatched with speaker related resource`

## 5. 常见报错排查

- `401 request and grant appid mismatch`
  - `doubao_app_key` 与 `doubao_access_key` 不匹配（不是同一个应用授权链路）。
- `403 requested resource not granted`
  - 当前应用没有该 `doubao_resource_id` 的授权。
- 握手通过但合成失败且提示资源不匹配
  - `doubao_resource_id` 与 `doubao_voice_type` 组合错误。

## 6. 生效方式

修改 `plugins/call_me/config.toml` 后，重启 Call Me 服务：

1. `/callme stop`
2. `/callme start`

