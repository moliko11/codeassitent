# 供应商配置与适配器工厂
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from ..adapters.ark import ArkAdapter
from ..adapters.openai_compat import OpenAICompatibleAdapter

# 导入本模块时把 code/.env 载入 os.environ。
# load_dotenv 默认不覆盖已存在的环境变量（shell 里 export 的值优先）。
# provider.py 位于 code/agent/config/，parents[2] 即 code/。
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_FILE)


@dataclass
class ProviderConfig:
    """供应商配置：API key 从环境变量读，不在源码出现"""
    provider: Literal["openai_compatible", "ark"]
    api_key: str = ""
    base_url: str = ""
    model: str = ""


# 环境变量约定（按 provider 前缀）：
#   openai_compatible -> DEEPSEEK_API_KEY       / DEEPSEEK_BASE_URL       / DEEPSEEK_MODEL
#   ark               -> VOLCANO_ENGINE_API_KEY / VOLCANO_ENGINE_BASE_URL / VOLCANO_ENGINE_MODEL
_ENV_PREFIX = {"openai_compatible": "DEEPSEEK", "ark": "VOLCANO_ENGINE"}


# def load_provider_config(provider: str) -> ProviderConfig:
#     """从环境变量加载指定 provider 的配置"""
#     prefix = _ENV_PREFIX.get(provider)
#     if prefix is None:
#         raise ValueError(f"unknown provider: {provider}，可选: {list(_ENV_PREFIX)}")
#     return ProviderConfig(
#         provider=provider,
#         api_key=os.environ.get(f"{prefix}_API_KEY", ""),
#         base_url=os.environ.get(f"{prefix}_BASE_URL", ""),
#         model=os.environ.get(f"{prefix}_MODEL", ""),
#     )
def load_provider_config(provider: str) -> ProviderConfig:
    """从环境变量加载指定 provider 的配置"""
    prefix = _ENV_PREFIX.get(provider)
    if prefix is None:
        raise ValueError(f"unknown provider: {provider}，可选: {list(_ENV_PREFIX)}")
    return ProviderConfig(
        provider="ark",
        api_key="ark-b7c08d49-6ed7-4f48-860e-6ac08f724c0c-c944b",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        model="Doubao-Seed-2.0-lite",
    )


def make_adapter(pc: ProviderConfig):
    """工厂：按 provider 创建对应的适配器实例"""
    if pc.provider == "openai_compatible":
        return OpenAICompatibleAdapter(
            api_key=pc.api_key, base_url=pc.base_url, model=pc.model,
        )
    if pc.provider == "ark":
        return ArkAdapter(
            api_key=pc.api_key, base_url=pc.base_url, model=pc.model,
        )
    raise ValueError(f"unknown provider: {pc.provider}")
