from connectors.catalog_source import _extract_records, _normalize_record


def test_extract_records_from_dict_projects():
    payload = {"projects": [{"name": "A"}, {"name": "B"}]}
    records = _extract_records(payload)
    assert len(records) == 2


def test_extract_records_from_list():
    payload = [{"name": "A"}, "x", {"name": "B"}]
    records = _extract_records(payload)
    assert len(records) == 2


def test_normalize_record_supports_license_field():
    rec = {"name": "Demo", "repository": "https://github.com/a/b", "license": "MIT"}
    out = _normalize_record(rec, "s1", "source", "https://x")
    assert out["license"] == "MIT"
    assert out["repo_url"] == "https://github.com/a/b"
