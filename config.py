from src.plugin_system import ConfigField

# 默认 VAD 参数
DEFAULT_VAD_CONFIG = {
    "speech_start_ms": 150,
    "speech_end_ms": 400,
    "short_pause_ms": 300,
    "min_utterance_ms": 50,
    "max_utterance_ms": 15000,
    "pre_roll_ms": 420,
    "pre_start_silence_tolerance_ms": 80,
    "mode": "webrtc",
    "energy_threshold": 500,
    "webrtc_aggressiveness": 2,
}

# 插件配置 Schema定义
PLUGIN_CONFIG_SCHEMA = {
    "plugin": {
        "enabled": ConfigField(type=bool, default=False, description="是否启用 Call Me 插件"),
        "config_version": ConfigField(type=str, default="0.1.0", description="配置文件版本")
    },
    "server": {
        "host": ConfigField(type=str, default="127.0.0.1", description="FastAPI 服务监听地址"),
        "port": ConfigField(type=int, default=8989, description="FastAPI 服务监听端口"),
        "cors_origins": ConfigField(type=list, default=["*"], description="CORS 允许的源")
    },
    "vad": {
        "speech_start_ms": ConfigField(type=int, default=150, description="判定开始说话的阈值(ms)"),
        "speech_end_ms": ConfigField(type=int, default=400, description="判定说话结束的阈值(ms)"),
        "short_pause_ms": ConfigField(type=int, default=300, description="句内停顿阈值(ms)"),
        "min_utterance_ms": ConfigField(type=int, default=50, description="最小语音长度(ms)"),
        "max_utterance_ms": ConfigField(type=int, default=15000, description="最大语音长度(ms)"),
        "pre_roll_ms": ConfigField(type=int, default=420, description="ASR预缓冲时长(ms)，用于避免句首被截断"),
        "pre_start_silence_tolerance_ms": ConfigField(type=int, default=80, description="VAD启动前短静默容忍(ms)，减少首音节丢失"),
        "mode": ConfigField(type=str, default="webrtc", description="VAD 模式: 'webrtc'、'silero' 或 'energy'"),
        "energy_threshold": ConfigField(type=int, default=500, description="能量 VAD 阈值 (RMS)"),
        "sample_rate": ConfigField(type=int, default=16000, description="输入音频采样率(Hz)，WebRTC VAD 帧长计算使用"),
        "webrtc_aggressiveness": ConfigField(type=int, default=2, description="WebRTC VAD 灵敏度(0-3)")
    },
    "audio": {
        "sample_rate": ConfigField(type=int, default=24000, description="输出音频采样率"),
        "channels": ConfigField(type=int, default=1, description="输出音频通道数"),
        "playback_startup_buffer_ms": ConfigField(type=int, default=120, description="前端音频首播缓冲时长(ms)，用于降低流式卡顿"),
        "playback_startup_max_wait_ms": ConfigField(type=int, default=120, description="前端音频首播最大等待(ms)，超时后强制开播"),
        "playback_schedule_lead_ms": ConfigField(type=int, default=30, description="前端音频调度提前量(ms)，用于平滑片段衔接")
    },
    "tts": {
        "type": ConfigField(type=str, default="sovits", description="TTS 类型: 'sovits', 'doubao_ws' 或 'mock'"),
        "api_url": ConfigField(type=str, default="http://127.0.0.1:9880", description="TTS 地址: sovits 为 HTTP 地址, doubao_ws 为 WebSocket 地址"),
        "voice_id": ConfigField(type=str, default="default", description="默认音色ID"),
        "connect_timeout_sec": ConfigField(type=float, default=3.0, description="TTS 连接超时(秒)"),
        "read_timeout_sec": ConfigField(type=float, default=20.0, description="TTS 读取超时(秒)"),
        "total_timeout_sec": ConfigField(type=float, default=0.0, description="TTS 总超时(秒)，<=0 表示不限制"),
        "conn_limit": ConfigField(type=int, default=32, description="TTS HTTP 连接池上限"),
        "stream_chunk_size": ConfigField(type=int, default=8192, description="TTS 流式读取块大小(字节)"),
        # 豆包双向流式 TTS 参数 (type=doubao_ws 时生效)
        "doubao_app_key": ConfigField(type=str, default="", description="豆包鉴权 App Key (X-Api-App-Key)"),
        "doubao_access_key": ConfigField(type=str, default="", description="豆包鉴权 Access Key (X-Api-Access-Key)"),
        "doubao_resource_id": ConfigField(type=str, default="", description="豆包资源ID (X-Api-Resource-Id)"),
        "doubao_voice_type": ConfigField(type=str, default="", description="豆包音色ID/voice_type (独立于 voice_id)"),
        "doubao_namespace": ConfigField(type=str, default="BidirectionalTTS", description="豆包双向流式命名空间"),
        "doubao_audio_format": ConfigField(type=str, default="pcm", description="豆包音频格式，当前仅支持 pcm"),
        "doubao_sample_rate": ConfigField(type=int, default=24000, description="豆包输出采样率"),
        "doubao_enable_timestamp": ConfigField(type=bool, default=False, description="豆包是否启用时间戳"),
        "doubao_disable_markdown_filter": ConfigField(type=bool, default=False, description="豆包是否禁用 markdown 过滤"),
        # SoVITS 必须参数
        "ref_audio_path": ConfigField(type=str, default="archive_jingyuan_1.wav", description="参考音频路径"),
        "prompt_text": ConfigField(type=str, default="我是「罗浮」云骑将军景元。不必拘谨，「将军」只是一时的身份，你称呼我景元便可", description="参考音频对应的文本"),
        "prompt_lang": ConfigField(type=str, default="zh", description="参考音频语言"),
        "text_lang": ConfigField(type=str, default="zh", description="目标合成语言"),
        "text_split_method": ConfigField(type=str, default="cut5", description="文本切分方法")
    },
    "asr": {
        "type": ConfigField(type=str, default="sherpa", description="ASR 类型: 'sherpa'(推荐), 'funasr', 'openai', 'mock'"),
        "api_url": ConfigField(type=str, default="http://127.0.0.1:10095", description="HTTP ASR API 地址 (仅 funasr/openai 等非 sherpa 模式生效)"),
        "final_delay_ms": ConfigField(type=int, default=80, description="VAD结束后到ASR取最终结果的等待时间(ms)，用于减少尾字吞字")
    },
    "sherpa": {
        "model_kind": ConfigField(type=str, default="zipformer2_ctc", description="模型类型: 'zipformer2_ctc'(推荐, 更低延迟) 或 'transducer'"),
        "tokens_path": ConfigField(type=str, default="", description="Sherpa tokens.txt 绝对路径 (建议与模型文件位于同一模型目录)"),
        "model_path": ConfigField(type=str, default="", description="zipformer2_ctc 模型文件路径 (如 model.int8.onnx)"),
        "encoder_path": ConfigField(type=str, default="", description="transducer 模式下的 encoder.onnx 路径"),
        "decoder_path": ConfigField(type=str, default="", description="transducer 模式下的 decoder.onnx 路径"),
        "joiner_path": ConfigField(type=str, default="", description="transducer 模式下的 joiner.onnx 路径"),
        "num_threads": ConfigField(type=int, default=1, description="计算线程数"),
        "provider": ConfigField(type=str, default="cpu", description="计算设备 (cpu/cuda/coreml)")
    },
    "llm": {
        "model_name": ConfigField(type=str, default="replyer", description="使用的 LLM 模型名称 (支持分号分隔的优先级列表，如 'utils.gemini-3-flash;utils')"),
        "history_window_messages": ConfigField(type=int, default=12, description="主回复构建时注入的历史消息窗口长度(按消息条数)")
    },
    "prethink": {
        "enabled": ConfigField(type=bool, default=False, description="是否启用预思考(异步预测下一轮用户意图)"),
        "model_name": ConfigField(type=str, default="", description="预思考模型名称，留空则复用 llm.model_name"),
        "timeout_ms": ConfigField(type=int, default=600, description="单次预思考超时(ms)"),
        "max_history_messages": ConfigField(type=int, default=10, description="预思考使用的历史消息数量上限"),
        "max_output_chars": ConfigField(type=int, default=220, description="预思考结果最大字符数"),
        "min_user_text_chars": ConfigField(type=int, default=2, description="触发预思考的最小用户输入长度")
    }
}
