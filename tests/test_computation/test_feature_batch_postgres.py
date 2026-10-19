"""Atomic complete batches on explicit, disposable P104 fixtures only."""

from contextlib import closing
from datetime import UTC, datetime

import psycopg2
import pytest

from scripts.data_contracts import FactStatus
from scripts.feature_batch_storage import (
    load_feature_batch,
    load_latest_feature_batch,
    store_feature_batch,
)
from scripts.feature_schema import FEATURE_SCHEMA_VERSION
from scripts.observation_storage import capture_observation_cutoff, load_observation_as_of
from tests.test_computation import test_observation_postgres as observations

connect = observations.connect
match_id = observations.match_id
pg = observations.pg
write = observations.write

FIELDS = ("temperature_2m", "precipitation")


def freeze(pg, match_id):
    cutoff = capture_observation_cutoff(
        pg,
        streams=[
            dict(
                match_id=match_id, source_id="open_meteo", domain="weather", subject_key="forecast"
            )
        ],
    )
    pg.commit()
    return cutoff


def values(**overrides):
    fields = {f: dict(fact_status="value", value=0, observation_indexes=[0]) for f in FIELDS}
    fields.update(overrides)
    return fields


def store(pg, match_id, cutoff, **overrides):
    args = dict(
        match_id=match_id,
        cutoff=cutoff,
        builder_version="fixed-weather/v1",
        required_fields=FIELDS,
        features=values(),
    )
    args.update(overrides)
    return store_feature_batch(pg, **args)


def latest(pg, match_id, **overrides):
    args = dict(match_id=match_id, builder_version="fixed-weather/v1", required_fields=FIELDS)
    args.update(overrides)
    return load_latest_feature_batch(pg, **args)


def test_complete_header_and_values_become_visible_together(pg, connect, match_id):
    ref = write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    batch = store(pg, match_id, cutoff)
    with closing(connect()) as other:
        assert latest(other, match_id)["batch"] is None
        pg.commit()
        selected = latest(other, match_id)
        assert selected["selection_reason"] == "latest_complete"
        loaded = selected["batch"]
        assert loaded["id"] == batch
        assert loaded["feature_schema_version"] == FEATURE_SCHEMA_VERSION
        assert loaded["features"]["temperature_2m"]["value"] == 0
        assert loaded["observations"][0]["revision_id"] == ref["revision_id"]
        assert loaded["cutoff"] == cutoff


def test_rolled_back_batch_is_not_visible(pg, connect, match_id):
    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    batch = store(pg, match_id, cutoff)
    pg.rollback()
    with closing(connect()) as other:
        assert load_feature_batch(other, batch) is None
        assert latest(other, match_id)["selection_reason"] == "no_complete_batch"


@pytest.mark.parametrize("status", ["running", "partial"])
def test_incomplete_attempt_explains_previous_complete_fallback(pg, match_id, status):
    write(pg, match_id)
    pg.commit()
    old_cutoff = freeze(pg, match_id)
    complete = store(pg, match_id, old_cutoff)
    pg.commit()
    new_cutoff = freeze(pg, match_id)
    attempt = store(pg, match_id, new_cutoff, status=status, features={})
    pg.commit()
    loaded = latest(pg, match_id)
    assert loaded["batch"]["id"] == complete
    assert loaded["newest_attempt_id"] == attempt
    assert loaded["newest_attempt_status"] == status
    assert loaded["selection_reason"] == "previous_complete"
    assert load_feature_batch(pg, attempt) is None


def test_all_missing_can_be_complete_without_fabricating_zero(pg, match_id):
    cutoff = freeze(pg, match_id)
    fields = {f: dict(fact_status="unknown", value=None, observation_indexes=[0]) for f in FIELDS}
    batch = store(pg, match_id, cutoff, features=fields)
    pg.commit()
    loaded = load_feature_batch(pg, batch)
    assert loaded["status"] == "complete"
    assert loaded["observations"] == [None]
    assert all(f["value"] is None for f in loaded["features"].values())
    assert loaded["usable_value_fields"] == []


@pytest.mark.parametrize(
    "bad",
    [
        {"features": {"temperature_2m": values()["temperature_2m"]}},
        {"required_fields": ("temperature_2m", "temperature_2m")},
        {"required_fields": ("unknown_feature",)},
        {
            "features": values(
                temperature_2m=dict(fact_status="unknown", value=0, observation_indexes=[0])
            )
        },
        {
            "features": values(
                temperature_2m=dict(
                    fact_status="value", value=float("nan"), observation_indexes=[0]
                )
            )
        },
        {
            "features": values(
                temperature_2m=dict(fact_status="value", value=1, observation_indexes=[])
            )
        },
        {
            "features": values(
                temperature_2m=dict(fact_status="value", value=1, observation_indexes=[1])
            )
        },
        {
            "features": values(
                temperature_2m=dict(fact_status="value", value=1, observation_indexes=[True])
            )
        },
        {"status": "ready"},
        {"builder_version": ""},
        {"feature_schema_version": "legacy-enriched/v1"},
    ],
)
def test_invalid_complete_payload_never_publishes(pg, match_id, bad):
    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    with pytest.raises(ValueError):
        store(pg, match_id, cutoff, **bad)
    pg.rollback()
    assert latest(pg, match_id)["batch"] is None


@pytest.mark.parametrize("source_status", ["unknown", "confirmed_absent", "conflict", "stale"])
def test_nonvalue_sources_do_not_prove_a_value_field(pg, match_id, source_status):
    write(
        pg,
        match_id,
        fact_status=FactStatus(source_status),
        value=None,
        evidence={"coverage_complete": True} if source_status == "confirmed_absent" else {},
    )
    pg.commit()
    cutoff = freeze(pg, match_id)
    with pytest.raises(ValueError, match="evidence"):
        store(pg, match_id, cutoff)
    pg.rollback()


def test_other_match_citations_and_research_cutoff_are_rejected(pg, match_id):
    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    with pytest.raises(ValueError, match="match"):
        store(pg, match_id + 1, cutoff)
    research = capture_observation_cutoff(
        pg,
        streams=[
            dict(
                match_id=match_id, source_id="open_meteo", domain="weather", subject_key="forecast"
            )
        ],
        include_reconstruction=True,
    )
    pg.commit()
    with pytest.raises(ValueError, match="research"):
        store(pg, match_id, research)


def test_late_publication_never_overtakes_newer_cutoff(pg, match_id):
    write(pg, match_id, value="old")
    pg.commit()
    older = freeze(pg, match_id)
    write(pg, match_id, value="new")
    pg.commit()
    newer = freeze(pg, match_id)
    new_id = store(pg, match_id, newer)
    pg.commit()
    old_id = store(pg, match_id, older)
    pg.commit()
    assert old_id > new_id
    assert latest(pg, match_id)["batch"]["id"] == new_id
    assert latest(pg, match_id)["batch"]["observations"][0]["value"] == "new"


def test_builder_and_fields_never_mix_in_fallback(pg, match_id):
    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    store(pg, match_id, cutoff)
    pg.commit()
    assert latest(pg, match_id, builder_version="another/v1")["batch"] is None
    assert latest(pg, match_id, required_fields=("temperature_2m",))["batch"] is None


@pytest.mark.parametrize("table", ["observation_cutoffs", "feature_batches"])
@pytest.mark.parametrize(
    "operation", ["UPDATE {table} SET id=id", "DELETE FROM {table}", "TRUNCATE {table} CASCADE"]
)
def test_cutoffs_and_batches_are_immutable_even_to_owner(pg, match_id, table, operation):
    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    store(pg, match_id, cutoff)
    pg.commit()
    with pytest.raises(psycopg2.Error, match="append-only"):
        with pg.cursor() as cur:
            cur.execute(operation.format(table=table))
    pg.rollback()
    assert latest(pg, match_id)["batch"] is not None


def test_cutoff_has_fixed_ids_and_refuses_forged_time(pg, match_id):
    from dataclasses import replace

    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    write(pg, match_id, value=99)
    pg.commit()
    loaded = load_observation_as_of(
        pg,
        match_id=match_id,
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        cutoff=cutoff,
    )
    assert loaded["value"]["temperature"] == 0
    with pytest.raises(ValueError, match="cutoff"):
        load_observation_as_of(
            pg,
            match_id=match_id,
            source_id="open_meteo",
            domain="weather",
            subject_key="forecast",
            cutoff=replace(cutoff, as_of=datetime(2099, 1, 1, tzinfo=UTC)),
        )


def test_large_finite_float_and_false_roundtrip_without_jsonb_numeric_rewrite(pg, match_id):
    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    fields = values(
        temperature_2m=dict(fact_status="value", value=1e20, observation_indexes=[0]),
        precipitation=dict(fact_status="value", value=False, observation_indexes=[0]),
    )
    batch = store(pg, match_id, cutoff, features=fields)
    pg.commit()
    loaded = load_feature_batch(pg, batch)
    assert loaded["features"] == fields


def test_declared_missing_stream_stays_missing_after_new_data_commits(pg, match_id):
    cutoff = freeze(pg, match_id)
    write(pg, match_id)
    pg.commit()
    assert (
        load_observation_as_of(
            pg,
            match_id=match_id,
            source_id="open_meteo",
            domain="weather",
            subject_key="forecast",
            cutoff=cutoff,
        )
        is None
    )
    with pytest.raises(ValueError, match="declared"):
        load_observation_as_of(
            pg,
            match_id=match_id,
            source_id="open_meteo",
            domain="weather",
            subject_key="other",
            cutoff=cutoff,
        )


def test_unknown_cutoff_is_not_replaced_with_current_state(pg):
    from uuid import uuid4

    from scripts.observation_storage import load_observation_cutoff

    with pytest.raises(ValueError, match="absent"):
        load_observation_cutoff(pg, str(uuid4()))


def test_cutoff_declaration_order_is_the_evidence_index_order(pg, match_id):
    from scripts.observation_storage import load_observation_selection

    cutoff = capture_observation_cutoff(
        pg,
        streams=[
            dict(match_id=match_id, source_id="open_meteo", domain="weather", subject_key=key)
            for key in ("z", "a")
        ],
    )
    pg.commit()
    assert [item["subject_key"] for item in load_observation_selection(pg, cutoff)] == ["z", "a"]


@pytest.mark.parametrize("damage", ["hash", "dangling", "future", "wrong_receipt"])
def test_corrupt_or_inconsistent_cutoff_references_fail_closed(pg, match_id, damage):
    import hashlib
    from dataclasses import replace
    from datetime import timedelta
    from uuid import uuid4

    from scripts.observation_storage import _canonical, load_observation_selection

    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    selections = load_observation_selection(pg, cutoff)
    at = cutoff.as_of
    if damage == "dangling":
        selections[0]["revision_id"] = 9223372036854775807
    if damage == "wrong_receipt":
        selections[0]["freshness_check_id"] = 9223372036854775807
    if damage == "future":
        at -= timedelta(days=1)
    serialized = _canonical(selections, 131072)
    checksum = "0" * 64 if damage == "hash" else hashlib.sha256(serialized.encode()).hexdigest()
    token = str(uuid4())
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO observation_cutoffs(id,as_of,include_reconstruction,selections,content_hash) "
            "VALUES (%s,%s,false,%s::jsonb,%s)",
            (token, at, serialized, checksum),
        )
    pg.commit()
    with pytest.raises(ValueError, match="cutoff"):
        load_observation_as_of(
            pg,
            match_id=match_id,
            source_id="open_meteo",
            domain="weather",
            subject_key="forecast",
            cutoff=replace(cutoff, id=token, as_of=at),
        )


@pytest.mark.parametrize("status", ["running", "partial"])
def test_only_incomplete_attempts_never_return_features(pg, match_id, status):
    cutoff = freeze(pg, match_id)
    attempt = store(pg, match_id, cutoff, status=status, features={})
    pg.commit()
    result = latest(pg, match_id)
    assert result["newest_attempt_id"] == attempt
    assert result["selection_reason"] == "no_complete_batch"
    assert result["batch"] is None


def test_batch_roles_need_only_insert_select_and_sequence_usage(pg, connect, match_id):
    with pg.cursor() as cur:
        cur.execute("SET ROLE fqp_observation_writer")
    write(pg, match_id)
    pg.commit()
    cutoff = freeze(pg, match_id)
    batch = store(pg, match_id, cutoff)
    pg.commit()
    with closing(connect()) as other:
        with other.cursor() as cur:
            cur.execute("SET ROLE fqp_observation_reader")
        assert load_feature_batch(other, batch)["id"] == batch
        with pytest.raises(psycopg2.Error, match="permission denied"):
            store(other, match_id, cutoff)
