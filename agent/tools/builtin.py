# 内置工具：import 本模块即向默认 registry 注册
from .registry import registry, tool

@tool(
    name="getnowtime",
    description="获取当前时间，返回 ISO 8601 格式字符串",
    input_schema={"type": "object", "properties": {}, "required": []},
)
def getnowtime():
    from datetime import datetime
    return datetime.now().isoformat()
