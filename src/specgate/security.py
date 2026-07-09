from __future__ import annotations

import re


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY)"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def contains_secret_like_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)
