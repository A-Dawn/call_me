from src.config.config import global_config
import random

def build_system_prompt() -> str:
    """
    Build the system prompt based on the global configuration (Personalty, Bot Name, etc.)
    """
    from src.common.logger import get_logger
    logger = get_logger("prompt_builder")
    logger.info("[PromptBuilder] Accessing global_config.bot...")
    bot_config = global_config.bot
    logger.info("[PromptBuilder] Accessing global_config.personality...")
    personality_config = global_config.personality

    bot_name = bot_config.nickname
    
    # 基础人设
    personality = personality_config.personality

    # 处理状态 (States) - 随机替换 personality
    if (
        personality_config.states
        and personality_config.state_probability > 0
        and random.random() < personality_config.state_probability
    ):
        personality = random.choice(personality_config.states)

    # 构建 Prompt
    system_prompt = f"你的名字是{bot_name}。"
    
    if bot_config.alias_names:
        aliases = ",".join(bot_config.alias_names)
        system_prompt += f"也有人叫你{aliases}。"
    
    system_prompt += f"\n你{personality}"
    
    # 回复风格 (Reply Style)
    reply_style = personality_config.reply_style
    # 处理多种回复风格 (Multiple Reply Styles)
    if (
        personality_config.multiple_reply_style
        and personality_config.multiple_probability > 0
        and random.random() < personality_config.multiple_probability
    ):
        reply_style = random.choice(personality_config.multiple_reply_style)
        
    if reply_style:
        system_prompt += f"\n你的说话风格是：{reply_style}"

    # 说话规则/行为风格 (Plan Style)
    if personality_config.plan_style:
         system_prompt += f"\n行为准则：{personality_config.plan_style}"
         
    system_prompt += "\n请用简短的口语回答，适合语音合成。"
    system_prompt += "\n【输出格式硬性要求】"
    system_prompt += (
        "\n1. 每条回复必须以情绪标签开头，格式严格为<emo:neutral|happy|sad|angry|shy|surprised>。"
        "\n2. 标签后只能输出“可直接朗读的台词正文”，不能输出任何动作、神态、旁白、舞台说明、心理描写。"
        "\n3. 严禁出现如：'(微笑)'、'[叹气]'、'*沉默*'、'（看向你）'、'她说/我想' 这类描述性文本。"
        "\n4. 若无法判断情绪，统一使用<emo:neutral>。"
        "\n5. 只输出“情绪标签 + 台词正文”，不要输出额外解释、注释、Markdown、代码块。"
    )

    return system_prompt
