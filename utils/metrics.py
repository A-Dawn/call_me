import time
from typing import Dict, Any

class MetricsCollector:
    def __init__(self):
        self.reset()

    def reset(self):
        self.metrics = {
            "session_id": "",
            "ttfb_ms": 0,    # Time to First Byte (LLM)
            "ttfa_ms": 0,    # Time to First Audio (TTS)
            "u_asr_ms": [],  # User ASR latencies
            "u_tts_ms": [],  # TTS generation latencies
            "interrupt_count": 0,
            "session_duration_s": 0.0,
            "start_time": time.time()
        }
        self._action_start_times = {}

    def start_measure(self, key: str):
        self._action_start_times[key] = time.time()

    def end_measure(self, key: str, metric_name: str):
        if key in self._action_start_times:
            duration_ms = (time.time() - self._action_start_times[key]) * 1000
            if isinstance(self.metrics.get(metric_name), list):
                self.metrics[metric_name].append(int(duration_ms))
            else:
                self.metrics[metric_name] = int(duration_ms)
            del self._action_start_times[key]

    def record(self, key: str, value: Any):
        self.metrics[key] = value
    
    def increment(self, key: str):
        if key in self.metrics:
            self.metrics[key] += 1

    def finalize(self) -> Dict[str, Any]:
        self.metrics["session_duration_s"] = round(time.time() - self.metrics["start_time"], 2)
        return self.metrics
