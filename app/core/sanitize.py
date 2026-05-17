"""Error message sanitizer for safe API exposure.

Sanitizes raw Python error messages before they are exposed via the
/api/runs endpoint. Removes exception class names, URLs, hostnames,
and internal paths while keeping messages meaningful for debugging.
"""

import re

# CamelCase identifier followed by balanced parens (innermost — no nested parens)
_CAMEL_CALL_RE = re.compile(r"\b[A-Z][a-zA-Z]+\([^()]*\)")

# URL pattern
_URL_RE = re.compile(r"https?://\S+")

# host= and port= patterns
_HOST_RE = re.compile(r"host=\S+")
_PORT_RE = re.compile(r",?\s*port=\d+")

# Collapsed whitespace
_MULTI_WS_RE = re.compile(r"\s+")

# Trailing punctuation left after stripping
_TRAILING_PUNCT_RE = re.compile(r"[,;:\s]+$")

MAX_MESSAGE_LENGTH: int = 100


def sanitize_error(msg: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Sanitize a single error message for safe API exposure.

    - Replaces CamelCase function/exception calls with ``API error``
    - Removes URLs (http/https)
    - Removes ``host=`` / ``port=`` patterns
    - Truncates result to *max_length* characters

    Args:
        msg: Raw error message string.
        max_length: Maximum output length in characters.

    Returns:
        Sanitized error message string.
    """
    if not msg:
        return ""

    text = msg

    # 1. Strip URLs first (they may appear inside exception args)
    text = _URL_RE.sub("", text)

    # 2. Iteratively peel off CamelCase(...) wrappers from inside out.
    #    This correctly handles nested exceptions like:
    #    ConnectionError(MaxRetryError('...'))
    while True:
        replacement = _CAMEL_CALL_RE.sub("API error", text)
        if replacement == text:
            break
        text = replacement

    # 3. Strip residual host=/port= patterns (may survive step 2)
    text = _HOST_RE.sub("", text)
    text = _PORT_RE.sub("", text)

    # 4. Tidy whitespace and trailing punctuation
    text = _MULTI_WS_RE.sub(" ", text).strip()
    text = _TRAILING_PUNCT_RE.sub("", text)

    # 5. Truncate with ellipsis indicator
    if len(text) > max_length:
        text = text[: max_length - 3] + "..."

    return text


def build_error_summary(
    errors: list[str],
    max_errors: int = 10,
    max_message_length: int = MAX_MESSAGE_LENGTH,
) -> str | None:
    """Build a sanitized error summary from a list of raw error messages.

    Each message is individually sanitized, then joined with ``"; "``.
    If more than *max_errors* messages are provided, a trailing count
    is appended.

    Args:
        errors: List of raw error message strings.
        max_errors: Maximum number of individual errors to include.
        max_message_length: Maximum length per sanitized message.

    Returns:
        Joined sanitized summary, or ``None`` if *errors* is empty.
    """
    if not errors:
        return None

    sanitized = [sanitize_error(e, max_length=max_message_length) for e in errors[:max_errors]]
    summary = "; ".join(sanitized)

    if len(errors) > max_errors:
        summary += f"; ... and {len(errors) - max_errors} more errors"

    return summary
