"""Developers Italia connector placeholder.

MVP note: this connector intentionally provides a stable interface but uses the same
publiccode.yml fetch model until API contract is finalized.
"""

from connectors.catalog_source import fetch_catalog_projects


def fetch_projects():
    return fetch_catalog_projects()
