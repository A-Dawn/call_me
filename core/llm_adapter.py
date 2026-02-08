import asyncio
from typing import AsyncGenerator, Optional, List, Dict, Any, Tuple
from src.llm_models.utils_model import LLMRequest, RequestType
from src.llm_models.payload_content.message import MessageBuilder
from src.llm_models.model_client.base_client import BaseClient
from src.plugin_system.apis import llm_api
from src.config.api_ada_configs import TaskConfig
from src.common.logger import get_logger

logger = get_logger("call_me_llm")

class LLMAdapter:
    """
    LLM 适配器，封装 LLMRequest 实现真流式输出。
    """
    
    def __init__(self):
        pass
    
    async def generate_stream(
        self, 
        prompt: str, 
        model_name: str, 
        cancel_event: asyncio.Event
    ) -> AsyncGenerator[str, None]:
        """
        生成流式回复 (True Streaming)。
        """
        
        # 1. 获取模型配置 (支持分号分隔的优先级列表)
        # model_name 可能类似 "utils.gemini;replyer;utils"
        models = llm_api.get_available_models()
        target_config = None
        
        # 将输入字符串按分号分割，去空
        candidates = [m.strip() for m in model_name.split(";") if m.strip()]
        
        # 遍历候选列表，尝试匹配
        for candidate in candidates:
            # 1. 精确匹配 key
            if candidate in models:
                target_config = models[candidate]
                break
            
            # 2. 模糊匹配 (candidate 是 key 的一部分)
            # 例如 candidate="gemini", key="utils.gemini-pro"
            for name, conf in models.items():
                if candidate in name:
                    target_config = conf
                    break
            
            if target_config:
                break
        
        # 3. Fallback logic
        if not target_config:
            # Try 'replyer' if explicitly not found yet
            if "replyer" in models:
                target_config = models["replyer"]
            elif models:
                target_config = list(models.values())[0]
            else:
                yield "【Error: No LLM model available】"
                return

        # 2. 准备 Queue 用于接收 Stream Callback 的数据
        queue = asyncio.Queue()
        has_stream_chunk = False

        from src.llm_models.model_client.base_client import APIResponse

        async def stream_handler(resp_stream, interrupt_flag):
            """
            异步流式回调 (Consumer模式)
            OpenAI Client 会把 AsyncStream 传进来，我们需要自己遍历。
            """
            nonlocal has_stream_chunk
            try:
                async for chunk in resp_stream:
                    # 提取 content
                    # 注意：chunk 是 ChatCompletionChunk
                    if not hasattr(chunk, "choices") or not chunk.choices:
                        continue
                    
                    delta = chunk.choices[0].delta
                    content = delta.content
                    
                    if content:
                        has_stream_chunk = True
                        queue.put_nowait(content)
            except Exception as e:
                logger.error(f"Stream handler error: {e}")
                # 再次抛出以便外层捕获
                raise e
            
            # 必须返回符合签名的结果 (APIResponse, Usage)
            return APIResponse(), None

        # 3. 启动后台生成任务
        logger.info(f"[LLMAdapter] Start streaming with {target_config.model_list}...")
        
        # 实例化 LLMRequest
        llm_request_obj = LLMRequest(model_set=target_config, request_type="plugin.call_me")
        
        async def run_llm():
            try:
                # 构造消息工厂
                def message_factory(client: BaseClient):
                    mb = MessageBuilder()
                    mb.add_text_content(prompt)
                    return [mb.build()]
                    
                response, _ = await llm_request_obj._execute_request(
                    request_type=RequestType.RESPONSE,
                    message_factory=message_factory,
                    stream_response_handler=stream_handler,
                )
                # 某些模型未启用 force_stream_mode，会走非流式返回路径。
                # 这种情况下 stream_handler 不会收到任何 chunk，需要兜底把完整文本送入队列。
                if not has_stream_chunk and response and response.content:
                    await queue.put(response.content)
            except Exception as e:
                logger.error(f"LLM Internal Error: {e}")
                # 将异常对象放入队列，以便在主循环中抛出
                await queue.put(e)
            finally:
                # 放入 None 表示结束
                await queue.put(None)

        task = asyncio.create_task(run_llm())
        
        # 4. 消费 Queue
        while True:
            # 检查取消
            if cancel_event.is_set():
                task.cancel()
                logger.info("[LLMAdapter] Cancelled by user.")
                break
                
            # 等待数据
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if task.done() and queue.empty():
                    break
                continue
                
            if item is None: # 结束信号
                break
            
            if isinstance(item, Exception):
                raise item
            
            # yield chunk
            yield item
            
        # 确保任务结束
        if not task.done():
            task.cancel()
