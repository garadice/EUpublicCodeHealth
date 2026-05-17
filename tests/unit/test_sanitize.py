"""Tests for error message sanitization."""

from app.core.sanitize import build_error_summary, sanitize_error


class TestSanitizeError:
    """Tests for sanitize_error (single-message sanitizer)."""

    # -- Normal short messages pass through unchanged --

    def test_plain_text_passes_through(self) -> None:
        assert sanitize_error("rate limit exceeded") == "rate limit exceeded"

    def test_project_prefix_passes_through(self) -> None:
        assert sanitize_error("italia/18app: not found") == "italia/18app: not found"

    def test_short_meaningful_message(self) -> None:
        msg = "repo/fail: API returned 404"
        assert sanitize_error(msg) == msg

    # -- Exception class name stripping --

    def test_nested_exceptions_replaced(self) -> None:
        msg = "italia/18app: ConnectionError(MaxRetryError('HTTPSConnectionPool(host=api.github.com, port=443)'))"
        result = sanitize_error(msg)
        assert result == "italia/18app: API error"

    def test_single_exception_replaced(self) -> None:
        assert sanitize_error("ValueError('bad input')") == "API error"

    def test_exception_with_prefix(self) -> None:
        assert sanitize_error("repo/name: TimeoutError('deadline exceeded')") == "repo/name: API error"

    def test_multiple_exceptions_in_one_message(self) -> None:
        msg = "foo/bar: ConnectionError('timeout') then RetryError('gave up')"
        result = sanitize_error(msg)
        assert "ConnectionError" not in result
        assert "RetryError" not in result
        assert "API error" in result

    # -- URL stripping --

    def test_https_url_removed(self) -> None:
        msg = "failed to connect to https://api.github.com/repos/foo"
        result = sanitize_error(msg)
        assert "https://" not in result
        assert "api.github.com" not in result

    def test_http_url_removed(self) -> None:
        msg = "error fetching http://internal-host:8080/api/data"
        result = sanitize_error(msg)
        assert "http://" not in result
        assert "internal-host" not in result

    def test_url_inside_exception(self) -> None:
        msg = "RequestException(GET https://api.github.com/repos - 403)"
        result = sanitize_error(msg)
        assert "https://" not in result
        assert "api.github.com" not in result

    # -- Hostname / port stripping --

    def test_host_equals_pattern_removed(self) -> None:
        msg = "connection failed host=db.internal.corp port=5432"
        result = sanitize_error(msg)
        assert "host=" not in result
        assert "db.internal.corp" not in result
        assert "port=" not in result

    # -- Truncation --

    def test_long_message_truncated(self) -> None:
        msg = "x" * 200
        result = sanitize_error(msg)
        assert len(result) == 100
        assert result.endswith("...")
        assert result == "x" * 97 + "..."

    def test_custom_max_length(self) -> None:
        msg = "a" * 50
        result = sanitize_error(msg, max_length=20)
        assert len(result) == 20
        assert result.endswith("...")

    def test_exactly_at_max_length_not_truncated(self) -> None:
        msg = "a" * 100
        result = sanitize_error(msg, max_length=100)
        assert len(result) == 100
        assert not result.endswith("...")

    # -- Empty / edge-case handling --

    def test_empty_string(self) -> None:
        assert sanitize_error("") == ""

    def test_whitespace_only(self) -> None:
        assert sanitize_error("   ") == ""

    def test_exception_with_no_args(self) -> None:
        assert sanitize_error("RuntimeError()") == "API error"

    def test_trailing_punctuation_cleaned(self) -> None:
        result = sanitize_error("error: host=example.com;")
        # Trailing semicolons/colons should be stripped
        assert not result.endswith(";")
        assert not result.endswith(":")


class TestBuildErrorSummary:
    """Tests for build_error_summary (list → joined summary)."""

    def test_empty_list_returns_none(self) -> None:
        assert build_error_summary([]) is None

    def test_single_error(self) -> None:
        result = build_error_summary(["something went wrong"])
        assert result == "something went wrong"

    def test_multiple_errors_joined(self) -> None:
        errors = ["error one", "error two", "error three"]
        result = build_error_summary(errors)
        assert result == "error one; error two; error three"

    def test_errors_are_sanitized(self) -> None:
        errors = [
            "repo/a: ConnectionError(MaxRetryError('host=api.github.com, port=443'))",
            "repo/b: ValueError('bad')",
        ]
        result = build_error_summary(errors)
        assert "ConnectionError" not in result
        assert "MaxRetryError" not in result
        assert "ValueError" not in result
        assert "API error" in result

    def test_truncation_applied_per_message(self) -> None:
        errors = ["x" * 200, "short"]
        result = build_error_summary(errors)
        parts = result.split("; ")
        # First message should be truncated to 100 chars
        assert len(parts[0]) == 100
        assert parts[1] == "short"

    def test_max_errors_limits_count(self) -> None:
        errors = [f"error {i}" for i in range(15)]
        result = build_error_summary(errors, max_errors=5)
        assert result is not None
        assert "... and 10 more errors" in result
        assert "error 0" in result
        assert "error 4" in result
        # error 5 should NOT appear (only first 5 included)
        assert "error 5" not in result

    def test_exactly_max_errors_no_suffix(self) -> None:
        errors = ["a", "b", "c"]
        result = build_error_summary(errors, max_errors=3)
        assert "... and" not in result
        assert result == "a; b; c"

    def test_custom_max_message_length(self) -> None:
        errors = ["a" * 50]
        result = build_error_summary(errors, max_message_length=20)
        assert len(result.split("; ")[0]) == 20
