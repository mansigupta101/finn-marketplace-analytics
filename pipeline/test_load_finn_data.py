"""Tests for load_finn_data.py on small files with the same structure as the FINN data."""

import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from pipeline import load_finn_data as lfd

N_USERS = 200
N_STEPS = 20
N_SLOTS = 25
N_ITEMS = 500


def make_source(source_dir: Path, compressed: bool, seed: int = 0) -> dict:
    """Writes data.npz, itemattr.npz and ind2val.json following FINN's documented format."""
    rng = np.random.default_rng(seed)
    user_id = np.arange(N_USERS, dtype=np.int32) + 1000
    click = np.zeros((N_USERS, N_STEPS), np.int32)
    click_idx = np.zeros((N_USERS, N_STEPS), np.int32)
    slate_lengths = np.zeros((N_USERS, N_STEPS), np.int32)
    slate = np.zeros((N_USERS, N_STEPS, N_SLOTS), np.int32)
    interaction_type = np.zeros((N_USERS, N_STEPS), np.int32)

    for u in range(N_USERS):
        for t in range(rng.integers(1, N_STEPS + 1)):  # users have 1 to 20 interactions
            length = int(rng.integers(2, N_SLOTS + 1))  # no-click item plus at least one item
            items = rng.choice(np.arange(2, N_ITEMS), size=length - 1, replace=False)
            slate[u, t, 0] = lfd.NO_CLICK_ITEM_ID
            slate[u, t, 1:length] = items
            slot = int(rng.integers(0, length))
            click[u, t] = slate[u, t, slot]
            click_idx[u, t] = slot
            slate_lengths[u, t] = length
            interaction_type[u, t] = rng.integers(1, 3)

    arrays = dict(
        userId=user_id,
        click=click,
        click_idx=click_idx,
        slate_lengths=slate_lengths,
        slate=slate,
        interaction_type=interaction_type,
    )
    source_dir.mkdir(parents=True, exist_ok=True)
    (np.savez_compressed if compressed else np.savez)(source_dir / "data.npz", **arrays)
    np.savez(source_dir / "itemattr.npz", category=(np.arange(N_ITEMS) % 5).astype(float))
    (source_dir / "ind2val.json").write_text(
        json.dumps(
            {
                "category": {"0": "PAD", "1": "noClick", "2": "<UNK>", "3": "BAP,antiques,Trøndelag", "4": "MOTOR,,Oslo"},
                "interaction_type": {"0": "<UNK>", "1": "search", "2": "rec"},
            }
        ),
        encoding="utf-8",
    )
    return arrays


@pytest.mark.parametrize("compressed", [False, True])
def test_full_sample_matches_source(tmp_path, compressed):
    arrays = make_source(tmp_path / "src", compressed)
    manifest = lfd.extract(tmp_path / "src", tmp_path / "out", fraction=1.0, seed=1, chunk_users=37)

    real_steps = int((arrays["click"] != 0).sum())
    real_slots = int((arrays["slate"] != 0).sum())
    assert manifest["row_counts"]["interactions"] == real_steps
    assert manifest["row_counts"]["exposures"] == real_slots
    assert manifest["row_counts"]["items"] == N_ITEMS
    for check in lfd.MUST_BE_ZERO:
        assert manifest["checks"][check] == 0, check
    assert manifest["checks"]["extra_recorded_slot"] == 0

    exposures = pq.read_table(tmp_path / "out" / "exposures.parquet").to_pandas()
    assert (exposures["item_id"] != lfd.PAD_ITEM_ID).all()

    interactions = pq.read_table(tmp_path / "out" / "interactions.parquet").to_pandas()
    assert (interactions["clicked_item_id"] != lfd.PAD_ITEM_ID).all()
    assert interactions["interaction_step"].between(0, N_STEPS - 1).all()


def test_rows_match_source_values(tmp_path):
    arrays = make_source(tmp_path / "src", compressed=True)
    lfd.extract(tmp_path / "src", tmp_path / "out", fraction=1.0, seed=1, chunk_users=50)
    interactions = pq.read_table(tmp_path / "out" / "interactions.parquet").to_pandas()

    row = interactions.iloc[123]
    u = int(row["user_id"]) - 1000
    t = int(row["interaction_step"])
    assert row["clicked_item_id"] == arrays["click"][u, t]
    assert row["click_slot_index"] == arrays["click_idx"][u, t]
    assert row["slate_length"] == arrays["slate_lengths"][u, t]
    assert row["interaction_type_code"] == arrays["interaction_type"][u, t]


def test_sample_is_reproducible_and_near_fraction(tmp_path):
    make_source(tmp_path / "src", compressed=False)
    first = lfd.extract(tmp_path / "src", tmp_path / "a", fraction=0.3, seed=7, chunk_users=64)
    second = lfd.extract(tmp_path / "src", tmp_path / "b", fraction=0.3, seed=7, chunk_users=11)

    assert first["row_counts"] == second["row_counts"]
    users_a = set(pq.read_table(tmp_path / "a" / "interactions.parquet")["user_id"].to_pylist())
    users_b = set(pq.read_table(tmp_path / "b" / "interactions.parquet")["user_id"].to_pylist())
    assert users_a == users_b
    assert 0.2 < len(users_a) / N_USERS < 0.4


def test_lookups(tmp_path):
    make_source(tmp_path / "src", compressed=False)
    lfd.extract(tmp_path / "src", tmp_path / "out", fraction=0.5, seed=1, chunk_users=100)
    groups = pq.read_table(tmp_path / "out" / "item_groups.parquet").to_pandas()
    types = pq.read_table(tmp_path / "out" / "interaction_types.parquet").to_pandas()
    assert groups.set_index("item_group_code").loc[3, "item_group_name"] == "BAP,antiques,Trøndelag"
    assert set(types["interaction_type_name"]) == {"<UNK>", "search", "rec"}


def test_create_table_sql():
    sql = lfd.create_table_sql("exposures")
    assert "RAW.FINN_SLATES.EXPOSURES" in sql
    assert "ITEM_ID NUMBER(19,0)" in sql


def run_checks(slate_row, length, click, click_idx):
    """Runs flatten_chunk on a single interaction and returns the check counts."""
    stats = lfd.ExtractStats()
    slate = np.zeros((1, 1, N_SLOTS), np.int32)
    slate[0, 0, : len(slate_row)] = slate_row
    lfd.flatten_chunk(
        np.array([7]),
        np.array([[click]]),
        np.array([[click_idx]]),
        np.array([[length]]),
        slate,
        np.array([[1]]),
        stats,
    )
    return stats


def test_extra_recorded_slot_is_counted_but_not_an_error():
    # Recorded length is one more than the item list: the known FINN rule.
    stats = run_checks([1, 10, 11, 12], length=5, click=11, click_idx=2)
    assert stats.extra_recorded_slot == 1
    assert stats.unexpected_length_differences == 0


def test_unexpected_length_and_gaps_are_errors():
    stats = run_checks([1, 10, 0, 12], length=7, click=12, click_idx=3)
    assert stats.slates_with_gaps == 1
    assert stats.unexpected_length_differences == 1


def test_click_checks_and_unknown_items():
    stats = run_checks([1, 2, 11, 2], length=4, click=11, click_idx=3)
    assert stats.click_slot_mismatches == 1  # slot 3 holds item 2, not 11
    assert stats.clicked_item_not_in_slate == 0  # but item 11 is in the slate
    assert stats.slates_with_unknown_items == 1
    assert stats.unknown_item_exposures == 2
