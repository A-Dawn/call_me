import json
import re
from typing import Optional, Tuple


EMOTION_TYPES = ("neutral", "happy", "sad", "angry", "shy", "surprised")

_EMOTION_ALIASES = {
    "neutral": "neutral",
    "calm": "neutral",
    "normal": "neutral",
    "平静": "neutral",
    "中性": "neutral",
    "普通": "neutral",
    "happy": "happy",
    "joy": "happy",
    "开心": "happy",
    "高兴": "happy",
    "愉快": "happy",
    "兴奋": "happy",
    "sad": "sad",
    "伤心": "sad",
    "难过": "sad",
    "失落": "sad",
    "沮丧": "sad",
    "angry": "angry",
    "mad": "angry",
    "生气": "angry",
    "愤怒": "angry",
    "恼火": "angry",
    "shy": "shy",
    "害羞": "shy",
    "脸红": "shy",
    "不好意思": "shy",
    "surprised": "surprised",
    "surprise": "surprised",
    "惊讶": "surprised",
    "震惊": "surprised",
    "吃惊": "surprised",
}

_EMO_TAG_RE = re.compile(
    r"^\s*(?:"
    r"\[(?:emotion|emo)\s*[:=]\s*([a-zA-Z_\u4e00-\u9fa5]+)\s*\]"
    r"|<(?:emotion|emo)\s*[:=]\s*([a-zA-Z_\u4e00-\u9fa5]+)\s*>"
    r"|【(?:情绪|emotion)\s*[:：]\s*([a-zA-Z_\u4e00-\u9fa5]+)\s*】"
    r")\s*",
    re.IGNORECASE,
)


def normalize_emotion(value: Optional[str], default: str = "neutral") -> str:
    if not value:
        return default
    key = str(value).strip().lower()
    if not key:
        return default
    if key in _EMOTION_ALIASES:
        return _EMOTION_ALIASES[key]
    for k, v in _EMOTION_ALIASES.items():
        if k in key:
            return v
    return default


def strip_leading_emotion_tag(text: str) -> Tuple[Optional[str], str]:
    """Extract and remove a leading emotion tag from text.

    Supported examples:
    - [emotion:happy] 你好
    - <emo:sad> 你好
    - 【情绪:开心】 你好
    """
    if not text:
        return None, ""
    m = _EMO_TAG_RE.match(text)
    if not m:
        return None, text
    raw = m.group(1) or m.group(2) or m.group(3)
    emotion = normalize_emotion(raw, default="neutral")
    cleaned = text[m.end() :]
    return emotion, cleaned


def infer_emotion(text: str, default: str = "neutral") -> str:
    if not text:
        return default
    t = text.lower()
    score = {
        "happy": 0,
        "sad": 0,
        "angry": 0,
        "shy": 0,
        "surprised": 0,
    }

    def add(e: str, w: int):
        score[e] += w

    for kw in ("开心", "高兴", "喜欢", "太棒", "哈哈", "嘿嘿", "喵~", "耶", "爱你"):
        if kw in text:
            add("happy", 2)
    for kw in ("难过", "伤心", "呜", "哭", "失落", "抱抱", "委屈", "遗憾"):
        if kw in text:
            add("sad", 2)
    for kw in ("生气", "气死", "愤怒", "烦死", "讨厌", "火大", "别烦"):
        if kw in text:
            add("angry", 2)
    for kw in ("害羞", "脸红", "不好意思", "羞", "///", "*>_<*"):
        if kw in text:
            add("shy", 2)
    for kw in ("哇", "诶", "居然", "真的吗", "不会吧", "惊", "震惊"):
        if kw in text:
            add("surprised", 2)

    # punctuation hints
    add("surprised", text.count("？") + text.count("?"))
    add("happy", text.count("~"))
    add("happy", text.count("！") // 2 + text.count("!") // 2)

    best = max(score, key=lambda k: score[k])
    if score[best] <= 0:
        return default
    return best


def extract_emotion_from_tags_json(tags_json: str) -> Optional[str]:
    """Best-effort parse emotion from tags_json used by assets table."""
    if not tags_json:
        return None
    try:
        data = json.loads(tags_json)
    except Exception:
        return None

    if isinstance(data, dict):
        if "emotion" in data:
            return normalize_emotion(str(data.get("emotion")), default="neutral")
        return None

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                s = item.strip()
                if s.lower().startswith("emotion:"):
                    return normalize_emotion(s.split(":", 1)[1], default="neutral")
                if s.lower().startswith("emo:"):
                    return normalize_emotion(s.split(":", 1)[1], default="neutral")
            if isinstance(item, dict) and "emotion" in item:
                return normalize_emotion(str(item.get("emotion")), default="neutral")
    return None
