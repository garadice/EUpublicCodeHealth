"""Tests for publiccode.yml defensive parser."""

import textwrap

from app.core.publiccode_parser import ParsedPubliccode, parse_publiccode

COMPLETE_YAML = textwrap.dedent("""\
    publiccodeYmlVersion: "0.2"
    name: Test Software
    url: https://github.com/test/repo
    releaseDate: "2024-01-01"
    platforms:
      - linux
      - web
    categories:
      - workflow-management
    developmentStatus: stable
    softwareType: standalone/web
    description:
      en:
        genericName: Test App
        shortDescription: A test application
      it:
        genericName: App Test
        shortDescription: Una app di test
    legal:
      license: Apache-2.0
""")


def test_parse_valid_complete_yaml() -> None:
    result = parse_publiccode(COMPLETE_YAML)
    assert isinstance(result, ParsedPubliccode)
    assert result.parse_error is None
    assert result.name == "Test Software"
    assert result.url == "https://github.com/test/repo"
    assert result.description == "A test application"
    assert result.landing_url is None
    assert result.development_status == "stable"
    assert result.license == "Apache-2.0"
    assert result.software_type == "standalone/web"
    assert result.categories == ["workflow-management"]
    assert result.platforms == ["linux", "web"]
    assert result.is_based_on == []


def test_parse_valid_minimal_yaml() -> None:
    yaml_text = textwrap.dedent("""\
        name: Minimal
        url: https://example.com/repo
    """)
    result = parse_publiccode(yaml_text)
    assert result.parse_error is None
    assert result.name == "Minimal"
    assert result.url == "https://example.com/repo"
    assert result.description is None
    assert result.landing_url is None
    assert result.development_status is None
    assert result.license is None
    assert result.software_type is None
    assert result.categories == []
    assert result.platforms == []
    assert result.is_based_on == []


def test_parse_empty_string_returns_parse_error() -> None:
    result = parse_publiccode("")
    assert result.parse_error is not None
    assert "Empty" in result.parse_error


def test_parse_blank_whitespace_returns_parse_error() -> None:
    result = parse_publiccode("   \n\t  \n  ")
    assert result.parse_error is not None
    assert "Empty" in result.parse_error


def test_parse_invalid_yaml_syntax_returns_parse_error() -> None:
    result = parse_publiccode("{{invalid: [yaml")
    assert result.parse_error is not None
    assert "Invalid YAML" in result.parse_error


def test_parse_yaml_list_returns_parse_error() -> None:
    result = parse_publiccode("[1, 2, 3]")
    assert result.parse_error is not None
    assert "list" in result.parse_error.lower()


def test_parse_yaml_scalar_returns_parse_error() -> None:
    result = parse_publiccode("just a string")
    assert result.parse_error is not None
    assert "str" in result.parse_error.lower()


def test_parse_missing_name_returns_empty_string() -> None:
    yaml_text = "url: https://example.com\n"
    result = parse_publiccode(yaml_text)
    assert result.parse_error is None
    assert result.name == ""


def test_parse_missing_url_returns_none() -> None:
    yaml_text = "name: No URL\n"
    result = parse_publiccode(yaml_text)
    assert result.parse_error is None
    assert result.url is None


def test_parse_missing_description_returns_none() -> None:
    yaml_text = "name: X\nurl: https://x.com\n"
    result = parse_publiccode(yaml_text)
    assert result.description is None


def test_parse_description_prefers_english() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        description:
          it:
            shortDescription: Descrizione italiana
          en:
            shortDescription: English description
    """)
    result = parse_publiccode(yaml_text)
    assert result.description == "English description"


def test_parse_description_italian_only() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        description:
          it:
            shortDescription: Solo italiano
    """)
    result = parse_publiccode(yaml_text)
    assert result.description == "Solo italiano"


def test_parse_description_empty_short_falls_back_to_generic_name() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        description:
          en:
            genericName: Fallback Name
            shortDescription: ""
    """)
    result = parse_publiccode(yaml_text)
    assert result.description == "Fallback Name"


def test_parse_description_as_plain_string() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        description: plain text description
    """)
    result = parse_publiccode(yaml_text)
    assert result.description == "plain text description"


def test_parse_missing_legal_section_returns_none_license() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
    """)
    result = parse_publiccode(yaml_text)
    assert result.license is None


def test_parse_legal_present_but_no_license_key() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        legal:
          authorsFile: AUTHORS
    """)
    result = parse_publiccode(yaml_text)
    assert result.license is None


def test_parse_empty_categories_returns_empty_list() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        categories: []
    """)
    result = parse_publiccode(yaml_text)
    assert result.categories == []


def test_parse_categories_filters_empty_strings() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        categories:
          - valid-cat
          - ""
          - "   "
          - another-cat
    """)
    result = parse_publiccode(yaml_text)
    assert result.categories == ["valid-cat", "another-cat"]


def test_parse_platforms_filters_non_strings() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        platforms:
          - linux
          - 42
          - web
          - null
    """)
    result = parse_publiccode(yaml_text)
    assert result.platforms == ["linux", "web"]


def test_parse_is_based_on_absent_returns_empty_list() -> None:
    result = parse_publiccode(COMPLETE_YAML)
    assert result.is_based_on == []


def test_parse_development_status_present() -> None:
    result = parse_publiccode(COMPLETE_YAML)
    assert result.development_status == "stable"


def test_parse_software_type_present() -> None:
    result = parse_publiccode(COMPLETE_YAML)
    assert result.software_type == "standalone/web"


def test_parse_landing_url_present() -> None:
    yaml_text = textwrap.dedent("""\
        name: X
        url: https://x.com
        landingURL: https://x.com/landing
    """)
    result = parse_publiccode(yaml_text)
    assert result.landing_url == "https://x.com/landing"


def test_parse_numeric_name_coerced_to_string() -> None:
    yaml_text = "name: 123\nurl: https://x.com\n"
    result = parse_publiccode(yaml_text)
    assert result.parse_error is None
    assert result.name == "123"
    assert isinstance(result.name, str)
