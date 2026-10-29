import pytest

from scripts.data_catalog import (
    get_data_product,
    get_data_source,
    get_field_resolution_policy,
    load_data_catalog,
)
from scripts.data_contracts import CONTRACT_VERSION


def test_catalog_is_versioned_and_does_not_enable_unknown_sources():
    catalog = load_data_catalog()
    assert catalog["contract_version"] == CONTRACT_VERSION
    assert catalog["catalog_version"] == "2026-10-29.3"
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


def test_observation_product_reuses_the_single_catalog_and_preserves_purpose_boundary():
    product = get_data_product("source_observations", purpose="research")
    assert product["contract_owner"] == "P104"
    assert product["writer"] == "observation_storage"
    assert product["tables"] == [
        "observation_streams",
        "observation_revisions",
        "observation_checks",
        "observation_cutoffs",
    ]
    assert product["availability"] == "requires_captured_cutoff_and_source_permission"
    with pytest.raises(PermissionError):
        get_data_product("source_observations", purpose="settlement")


def test_complete_batch_product_uses_the_common_store_and_restricts_settlement():
    product = get_data_product("complete_feature_batches", purpose="prediction")
    assert product["tables"] == ["feature_batches"]
    assert product["writer"] == "feature_batch_storage"
    with pytest.raises(PermissionError):
        get_data_product("complete_feature_batches", purpose="settlement")


@pytest.mark.parametrize(
    "field,source,domain,age",
    [
        ("weather.temperature_2m", "open_meteo", "weather", 21600),
        ("lineup.starters", "api_football", "lineup", 1800),
        ("injuries.complete_report", "api_football", "injuries", 1800),
    ],
)
def test_field_resolution_policy_is_explicit_metadata_not_a_source_grant(
    field, source, domain, age
):
    rule = get_field_resolution_policy(field)
    assert rule["version"] == "observation-fields/v1" and rule["field"] == field
    assert rule["sources"] == {source: 10} and rule["domain"] == domain
    assert rule["max_age_seconds"] == age
    rule["sources"][source] = 99
    assert get_field_resolution_policy(field)["sources"] == {source: 10}
    assert get_data_source(source)["coverage_verification"] == "unknown"
    assert load_data_catalog()["runtime_authorization"] is False


def test_unsupported_field_does_not_guess_a_global_source_order():
    with pytest.raises(KeyError):
        get_field_resolution_policy("player.eligibility")


def test_league_reference_product_shares_postgres_but_cannot_be_used_as_official_input():
    import importlib.util

    source = get_data_source("titan007")
    assert source["runtime_scheduled"] is False
    assert importlib.util.find_spec(source["refresh_entrypoint"]) is not None
    product = get_data_product("league_references", purpose="display")
    assert product["writer"] == "titan007_import"
    assert "league_reference_fixtures" in product["tables"]
    for purpose in ("settlement", "prediction"):
        with pytest.raises(PermissionError):
            get_data_product("league_references", purpose=purpose)
