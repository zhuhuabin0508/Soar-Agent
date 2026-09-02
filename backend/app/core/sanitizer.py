"""文本输入 XSS 过滤工具。

用户提交的反馈内容（标题/描述/复现步骤等）在入库前统一调用
:func:`sanitize_text` 做两层清洗：

1. 转义 HTML 特殊字符 ``< > & " '``（``html.escape`` 方式），
   防止存储型 XSS 在前端被直接渲染执行；
2. 去除不可见控制字符（保留 ``\\n`` ``\\r`` ``\\t``），
   防止日志注入与异常控制符污染数据库。
"""
import html
import re

# 不可见控制字符：\x00-\x08、\x0b、\x0c、\x0e-\x1f、\x7f（保留 \n \r \t）
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str | None) -> str:
    """清洗用户输入文本：转义 HTML 特殊字符并去除控制字符。

    Args:
        text: 原始文本，``None`` 返回空字符串。

    Returns:
        清洗后的安全文本（长度不变或略短，控制字符被移除）。
    """
    if text is None:
        return ""
    # 转义 < > & " ' 五个字符
    escaped = html.escape(text, quote=True)
    # 去除不可见控制字符（保留换行/回车/制表符）
    return _CONTROL_CHARS.sub("", escaped)
