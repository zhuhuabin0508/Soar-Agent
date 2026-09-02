"""LLM Provider 模板与元信息。

集中管理各 Provider 的：
- 官方 Base URL（创建配置时自动填充）
- 常用模型列表（Model Name 下拉可选）
- 是否需要 Organization ID / Project ID
- 图标标识（前端展示用 emoji 或首字母）

新增 Provider 时只需在此文件添加条目，前端与后端均可引用。
"""
from typing import Any


# Provider 元信息：key = provider code（与 LLMConfig.provider 对应）
# 字段说明：
#   label:    显示名
#   base_url: 官方默认 Base URL（用户可覆盖）
#   models:   常用模型列表（按类型分组：chat / embedding / vision / rerank）
#   need_org: 是否需要 Organization ID
#   need_project: 是否需要 Project ID
#   icon:     图标 emoji（前端展示）
#   docs:     官方文档链接
PROVIDER_TEMPLATES: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com",
        "models": {
            "chat": [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ],
            "vision": [
                "claude-3-5-sonnet-20241022",
                "claude-3-opus-20240229",
            ],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🅰️",
        "docs": "https://docs.anthropic.com/",
    },
    "openai": {
        "label": "OpenAI (GPT)",
        "base_url": "https://api.openai.com/v1",
        "models": {
            "chat": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            "embedding": ["text-embedding-ada-002", "text-embedding-3-small", "text-embedding-3-large"],
            "vision": ["gpt-4o", "gpt-4-turbo"],
        },
        "need_org": True,
        "need_project": False,
        "icon": "🟢",
        "docs": "https://platform.openai.com/docs",
    },
    "azure": {
        "label": "Azure OpenAI",
        "base_url": "",
        "models": {
            "chat": ["gpt-4o", "gpt-4", "gpt-35-turbo"],
            "embedding": ["text-embedding-ada-002", "text-embedding-3-large"],
        },
        "need_org": False,
        "need_project": True,
        "icon": "🔷",
        "docs": "https://learn.microsoft.com/azure/ai-services/openai/",
    },
    "google": {
        "label": "Google (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1",
        "models": {
            "chat": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"],
            "vision": ["gemini-1.5-pro", "gemini-1.5-flash"],
            "embedding": ["text-embedding-004"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🔵",
        "docs": "https://ai.google.dev/",
    },
    "deepseek": {
        "label": "DeepSeek (深度求索)",
        "base_url": "https://api.deepseek.com/v1",
        "models": {
            "chat": ["deepseek-chat", "deepseek-reasoner"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🐳",
        "docs": "https://platform.deepseek.com/",
    },
    "moonshot": {
        "label": "Moonshot (月之暗面/Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "models": {
            "chat": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
            "vision": ["moonshot-v1-8k-vision-preview", "moonshot-v1-32k-vision-preview"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🌙",
        "docs": "https://platform.moonshot.cn/",
    },
    "zhipu": {
        "label": "智谱 AI (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": {
            "chat": ["glm-4-plus", "glm-4", "glm-4-air", "glm-4-flash", "glm-4-long"],
            "vision": ["glm-4v", "glm-4v-plus"],
            "embedding": ["embedding-3", "embedding-2"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🌟",
        "docs": "https://open.bigmodel.cn/",
    },
    "volcengine": {
        "label": "火山引擎 (豆包)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": {
            "chat": ["doubao-pro-32k", "doubao-pro-128k", "doubao-lite-32k"],
            "vision": ["doubao-vision-pro-32k"],
            "embedding": ["doubao-embedding-text-240715"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🌋",
        "docs": "https://www.volcengine.com/docs/82379",
    },
    "baidu": {
        "label": "百度 (文心一言)",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": {
            "chat": ["ernie-4.0-8k-latest", "ernie-3.5-8k", "ernie-speed-128k"],
            "embedding": ["bge-large-zh", "bge-large-en"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🔴",
        "docs": "https://cloud.baidu.com/product/wenxinworkshop/",
    },
    "alibaba": {
        "label": "阿里 (通义千问)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": {
            "chat": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"],
            "vision": ["qwen-vl-max", "qwen-vl-plus"],
            "embedding": ["text-embedding-v2", "text-embedding-v1"],
            "rerank": ["gte-rerank"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🟠",
        "docs": "https://help.aliyun.com/zh/dashscope/",
    },
    "tencent": {
        "label": "腾讯 (混元)",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "models": {
            "chat": ["hunyuan-pro", "hunyuan-standard", "hunyuan-lite"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🐧",
        "docs": "https://cloud.tencent.com/product/hunyuan",
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "models": {
            "chat": ["abab6.5s-chat", "abab6.5-chat", "abab5.5s-chat"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🔵",
        "docs": "https://platform.minimaxi.com/",
    },
    "siliconflow": {
        "label": "硅基流动 (SiliconFlow)",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": {
            "chat": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3", "meta-llama/Meta-Llama-3.1-405B-Instruct"],
            "embedding": ["BAAI/bge-m3", "BAAI/bge-large-zh-v1.5"],
            "rerank": ["BAAI/bge-reranker-v2-m3"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "💎",
        "docs": "https://siliconflow.cn/",
    },
    "ollama": {
        "label": "Ollama (本地部署)",
        "base_url": "http://localhost:11434/v1",
        "models": {
            "chat": ["llama3.2", "qwen2.5", "mistral", "phi3"],
            "embedding": ["nomic-embed-text", "mxbai-embed-large"],
        },
        "need_org": False,
        "need_project": False,
        "icon": "🦙",
        "docs": "https://ollama.com/",
    },
    "other": {
        "label": "其他 (OpenAI 兼容)",
        "base_url": "",
        "models": {},
        "need_org": False,
        "need_project": False,
        "icon": "⚙️",
        "docs": "",
    },
}


def get_provider_template(provider: str) -> dict[str, Any]:
    """获取指定 Provider 的模板信息。未知 Provider 返回 other 模板。"""
    return PROVIDER_TEMPLATES.get(provider, PROVIDER_TEMPLATES["other"])


def get_provider_models(provider: str, model_type: str = "chat") -> list[str]:
    """获取指定 Provider 指定类型的常用模型列表。"""
    tpl = get_provider_template(provider)
    return tpl.get("models", {}).get(model_type, [])
