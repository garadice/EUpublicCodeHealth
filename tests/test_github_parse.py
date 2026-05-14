from connectors.github_client import parse_github


def test_parse_github_url():
    owner, repo = parse_github("https://github.com/octocat/Hello-World")
    assert owner == "octocat"
    assert repo == "Hello-World"
