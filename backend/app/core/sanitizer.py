"""Sanitizer utility for safe error reporting in jobs and SSE events."""
import re
from typing import Any

SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(?:key|token|secret|password|bearer|auth)[\s:=]+([\'"]?[a-zA-Z0-9_\-\.]{8,}[\'"]?)'),
    re.compile(r'AIza[0-9A-Za-z-_]{35}'),
    re.compile(r'gsk_[0-9A-Za-z]{32,}'),
]


def sanitize_error_message(error: Any) -> str:
    """Strip API keys, tokens, secrets, tracebacks and system paths from errors."""
    if not error:
        return "Unknown error"
    msg = str(error).strip()
    # Take first line if exception message is multiline
    first_line = msg.split("\n")[0].strip()
    sanitized = first_line
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    # Redact local system file paths
    sanitized = re.sub(r'/[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)+', '[PATH]', sanitized)
    return sanitized[:300]
