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


def load_provider_config(provider: str | None = None) -> ProviderConfig:
    """加载指定 provider 的配置（provider 缺省走 YAML default/AGENT_PROVIDER env）。

    参数来源（优先级 YAML > env 回落）：
    - api_key 只从 api_key_env 指定的环境变量读(code/.env)，绝不放 YAML。
    - base_url/model 从 provider.yaml 读；为空则回落读 env ${prefix}_BASE_URL / _MODEL（保持 .env 可用）。
    """
    from .loader import get_section, default_provider
    prov = provider or default_provider()
    entry = (get_section("provider").get("providers") or {}).get(prov) or {}
    prefix = entry.get("env_prefix") or _ENV_PREFIX.get(prov)
    if prefix is None:
        raise ValueError(f"unknown provider: {prov}，可选: {list(_ENV_PREFIX)}")
    api_key_env = entry.get("api_key_env") or f"{prefix}_API_KEY"
    base_url = entry.get("base_url") or os.environ.get(f"{prefix}_BASE_URL", "")
    model = entry.get("model") or os.environ.get(f"{prefix}_MODEL", "")
    return ProviderConfig(
        provider=prov,
        api_key=os.environ.get(api_key_env, "").strip(),
        base_url=str(base_url).strip(),
        model=str(model).strip(),
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
