import pytest

from scripts.data_catalog import get_data_product, get_data_source, load_data_catalog
from scripts.data_contracts import CONTRACT_VERSION


def test_catalog_is_versioned_and_does_not_enable_unknown_sources():
    catalog = load_data_catalog()
    assert catalog["contract_version"] == CONTRACT_VERSION
    assert catalog["catalog_version"] == "2026-10-16.1"
    assert catalog["runtime_authorization"] is False
    for source in catalog["sources"].values():
        assert source["account_verification"] == "unknown"
        assert "api_key" not in source
    assert get_data_source("api_football")["alias_namespace"] == "apifootball"


def test_catalog_returns_copies_not_mutable_shared_policy():
    source = get_data_source("sporttery")
    source["alias_namespace"] = "modified"
    assert get_data_source("sporttery")["alias_namespace"] == "sporttery"


@pytest.mark.parametrize("source", ["not_registered", "Sporttery", "https://example.com"])
def test_unknown_namespace_does_not_silently_fallback(source):
    with pytest.raises(KeyError):
        get_data_source(source)


def test_domain_catalog_references_actual_tables_and_single_owners():
    facts = get_data_product("match_features", purpose="research")
    assert facts["tables"] == ["match_feature_snapshots"]
    assert facts["contract_owner"] == "P102"
    assert "supplemental_matches" not in str(load_data_catalog())


def test_metadata_purpose_check_does_not_expose_restricted_products():
    with pytest.raises(PermissionError):
        get_data_product("financial_ledger", purpose="research")
    with pytest.raises(PermissionError):
        get_data_product("provider_credentials", purpose="display")
    with pytest.raises(ValueError):
        get_data_product("match_features", purpose="anything")


def test_metadata_approval_is_not_source_or_production_authorization():
    source = get_data_source("api_football")
    assert source["implementation"] == "existing"
    assert source["account_verification"] == "unknown"
    assert source["coverage_verification"] == "unknown"
