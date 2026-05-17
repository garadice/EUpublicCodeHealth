"""Defensive publiccode.yml parser.

Parses raw YAML strings from the Developers Italia API ``publiccodeYml``
field into a typed, normalized dataclass.  Never raises — all errors are
captured in ``ParsedPubliccode.parse_error`` so callers can safely use the
result without wrapping in try/except.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, overload

import yaml


@dataclass
class ParsedPubliccode:
    """Result of parsing a publiccode.yml string."""

    name: str = ""
    description: str | None = None
    url: str | None = None
    landing_url: str | None = None
    development_status: str | None = None
    license: str | None = None
    software_type: str | None = None
    categories: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    is_based_on: list[str] = field(default_factory=list)
    parse_error: str | None = None


# Preferred language codes for description, in priority order.
_DESCRIPTION_LANG_PRIORITY: tuple[str, ...] = ("en", "it")


def parse_publiccode(raw_yaml: str) -> ParsedPubliccode:
    """Parse a publiccode.yml string defensively.

    Never raises — returns ParsedPubliccode with parse_error set on failure.
    """
    if not raw_yaml or not raw_yaml.strip():
        return ParsedPubliccode(parse_error="Empty or blank publiccodeYml string")

    data: Any
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        return ParsedPubliccode(parse_error=f"Invalid YAML: {exc}")

    if not isinstance(data, dict):
        return ParsedPubliccode(
            parse_error=f"Expected YAML mapping, got {type(data).__name__}",
        )

    # --- Required field ---
    name = _str_field(data, "name", default="")

    # --- Optional scalar fields ---
    url = _str_field(data, "url")
    landing_url = _str_field(data, "landingURL")
    development_status = _str_field(data, "developmentStatus")
    software_type = _str_field(data, "softwareType")

    # --- Nested: legal.license ---
    license_value: str | None = None
    legal = data.get("legal")
    if isinstance(legal, dict):
        license_value = _str_field(legal, "license")

    # --- List fields ---
    categories = _str_list_field(data, "categories")
    platforms = _str_list_field(data, "platforms")
    is_based_on = _str_list_field(data, "isBasedOn")

    # --- Description (multi-language) ---
    description = _extract_description(data.get("description"))

    return ParsedPubliccode(
        name=name,
        description=description,
        url=url,
        landing_url=landing_url,
        development_status=development_status,
        license=license_value,
        software_type=software_type,
        categories=categories,
        platforms=platforms,
        is_based_on=is_based_on,
    )


def _extract_description(description_data: Any) -> str | None:
    """Extract best available description from multi-language dict.

    Language priority: English (``en``), Italian (``it``), then first
    available language.  Within each language block, prefer
    ``shortDescription`` over ``genericName``.
    """
    if description_data is None:
        return None

    # Some publiccode.yml files set description to a plain string.
    if isinstance(description_data, str):
        text = description_data.strip()
        return text if text else None

    if not isinstance(description_data, dict):
        return None

    # Build a lowercased-key lookup so "IT" and "it" map to the same entry.
    lang_map: dict[str, dict[str, Any]] = {}
    for lang_key, lang_value in description_data.items():
        if isinstance(lang_value, dict):
            lang_map[lang_key.lower()] = lang_value

    if not lang_map:
        return None

    # Try preferred languages first, then fall back to first available.
    ordered_keys = list(_DESCRIPTION_LANG_PRIORITY)
    for key in list(lang_map.keys()):
        if key not in ordered_keys:
            ordered_keys.append(key)

    for lang_key in ordered_keys:
        block = lang_map.get(lang_key)
        if not isinstance(block, dict):
            continue

        for field_name in ("shortDescription", "genericName", "longDescription"):
            value = block.get(field_name)
            if isinstance(value, str):
                text = value.strip()
                if text:
                    if field_name == "longDescription" and len(text) > 500:
                        text = text[:497] + "..."
                    return text

    return None


@overload
def _str_field(mapping: dict[str, Any], key: str, *, default: str) -> str: ...
@overload
def _str_field(mapping: dict[str, Any], key: str, *, default: str | None = None) -> str | None: ...
def _str_field(mapping: dict[str, Any], key: str, *, default: str | None = None) -> str | None:
    """Extract a string field from a mapping, returning None for missing/empty."""
    value = mapping.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    # Coerce non-string scalars (e.g. int, float) to string.
    return str(value).strip() or default


def _str_list_field(mapping: dict[str, Any], key: str) -> list[str]:
    """Extract a list-of-strings field, filtering empties and non-strings."""
    raw = mapping.get(key)
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                result.append(text)
    return result
