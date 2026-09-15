from langchain_openai import ChatOpenAI
from app.engine.config.config import lm_config
#key:模型名
#value:模型对象
_llm_client_cache={}
def get_llm_client(model:str|None=None,json_mode:bool=False)->ChatOpenAI:
    #1.获取模型名称，如果参数没有指定就使用默认模型
    m=model or lm_config.llm_model
    #2.定义缓存key
    key=(m,json_mode)

    #3.获取全局唯一的模型对象
    if key in _llm_client_cache:
        return _llm_client_cache[key]

    #4.关闭思考模式（DashScope qwen 专用参数；DeepSeek 等不识别该字段，
    #   对非 DashScope 端点不发送，避免 400）
    extra_body = (
        {"enable_thinking": False}
        if "dashscope" in lm_config.base_url.lower() else {}
    )

    #5.配置响应数据类型是否是json

    model_kwargs:dict={}
    if json_mode:
        model_kwargs['response_format']={'type':'json_object'}

    #6.创建模型对象
    #   timeout/max_retries 必须显式设置：默认无限等待，LLM 服务端挂起时
    #   （如 DeepSeek 只发 keep-alive 不出内容）整个查询图会卡死无响应
    llm=ChatOpenAI(
        model=m,
        api_key=lm_config.api_key,
        base_url=lm_config.base_url,
        temperature=lm_config.llm_temperature,
        extra_body=extra_body,
        model_kwargs=model_kwargs,
        timeout=90,
        max_retries=1,
    )
    #7.缓存模型对象
    _llm_client_cache[key]=llm
    return llm