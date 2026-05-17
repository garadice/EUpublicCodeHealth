"""Tests for URL normalization and host classification."""

from app.core.url_normalize import HostType, normalize_repo_url


class TestNormalizeGitHubURLs:
    def test_standard_github_url(self) -> None:
        result = normalize_repo_url("https://github.com/octocat/Hello-World")
        assert result.host == HostType.GITHUB
        assert result.owner == "octocat"
        assert result.repo_name == "Hello-World"
        assert result.canonical_url == "https://github.com/octocat/Hello-World"
        assert result.is_supported is True

    def test_github_url_with_git_suffix(self) -> None:
        result = normalize_repo_url("https://github.com/org/repo.git")
        assert result.repo_name == "repo"
        assert result.canonical_url == "https://github.com/org/repo"

    def test_github_url_with_trailing_slash(self) -> None:
        result = normalize_repo_url("https://github.com/org/repo/")
        assert result.repo_name == "repo"

    def test_github_url_with_fragment(self) -> None:
        result = normalize_repo_url("https://github.com/org/repo#readme")
        assert result.repo_name == "repo"

    def test_github_url_with_query_params(self) -> None:
        result = normalize_repo_url("https://github.com/org/repo?tab=readme")
        assert result.repo_name == "repo"

    def test_http_upgraded_to_https(self) -> None:
        result = normalize_repo_url("http://github.com/org/repo")
        assert result.canonical_url.startswith("https://")

    def test_github_url_both_git_and_slash(self) -> None:
        result = normalize_repo_url("https://github.com/org/repo.git/")
        assert result.repo_name == "repo"


class TestNormalizeGitLabURLs:
    def test_gitlab_url_classified_as_gitlab(self) -> None:
        result = normalize_repo_url("https://gitlab.com/org/repo")
        assert result.host == HostType.GITLAB
        assert result.is_supported is False

    def test_self_hosted_gitlab(self) -> None:
        result = normalize_repo_url("https://gitlab.opencode.de/org/repo")
        assert result.host == HostType.GITLAB
        assert result.is_supported is False


class TestNormalizeInvalidURLs:
    def test_none_url(self) -> None:
        result = normalize_repo_url(None)
        assert result.host == HostType.INVALID
        assert result.is_supported is False

    def test_empty_string(self) -> None:
        result = normalize_repo_url("")
        assert result.host == HostType.INVALID

    def test_whitespace_only(self) -> None:
        result = normalize_repo_url("   ")
        assert result.host == HostType.INVALID

    def test_unsupported_host(self) -> None:
        result = normalize_repo_url("https://example.com/repo")
        assert result.host == HostType.UNSUPPORTED
        assert result.is_supported is False

    def test_sourceforge_url(self) -> None:
        result = normalize_repo_url("https://sourceforge.net/projects/myproject")
        assert result.host == HostType.UNSUPPORTED
