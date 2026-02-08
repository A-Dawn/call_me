import re

_MEANINGFUL_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3]")
_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_LINE_PREFIX_RE = re.compile(r"^\s*[-*•\d\.\)\(]+\s*")


def build_prethink_prompt(recent_history: list[dict]) -> str:
    history_lines: list[str] = []
    for msg in recent_history:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        history_lines.append(f"{role}: {content}")

    history_text = "\n".join(history_lines) if history_lines else "（无）"
    return (
        "你是对话预判助手。请基于最近对话，预测“用户下一轮最可能说什么”。\n"
        "输出要求：\n"
        "1. 仅输出 1-3 条预测，不要解释过程。\n"
        "2. 每条一行，简洁中文，不要超过 40 字。\n"
        "3. 不要编造新事实；若信息不足可给宽泛预测。\n"
        "4. 不要输出 Markdown、代码块、标签或多余前缀。\n\n"
        "最近对话：\n"
        f"{history_text}\n\n"
        "请输出预测："
    )


def sanitize_prethink_result(raw_text: str, max_chars: int) -> str:
    if not raw_text:
        return ""
    max_chars = max(60, int(max_chars))

    text = _FENCE_RE.sub("", str(raw_text)).replace("\r", "\n").strip()
    if not text:
        return ""

    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        line = _LINE_PREFIX_RE.sub("", line.strip())
        if not line:
            continue
        if not _MEANINGFUL_RE.search(line):
            continue
        cleaned_lines.append(line)
        if len(cleaned_lines) >= 3:
            break

    cleaned = "\n".join(cleaned_lines).strip()
    if not cleaned:
        return ""
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
    return cleaned


def build_prethink_injection_block(hint_text: str) -> str:
    hint = str(hint_text or "").strip()
    if not hint:
        return ""
    return (
        "【内部参考-下一轮用户可能意图（可能不准确）】\n"
        f"{hint}\n"
        "仅供内部推理，不得向用户复述；若与当前用户输入冲突，以当前输入为准。"
    )
