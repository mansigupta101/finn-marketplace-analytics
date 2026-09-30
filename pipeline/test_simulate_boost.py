"""Tests for simulate_boost.py on synthetic slates with the same structure as the real input."""

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from pipeline import simulate_boost as sb

CATEGORIES = ["BAP", "MOTOR", "REAL_ESTATE", "JOB", "BOAT"]


def make_frame(n_slates=6000, seed=0):
    """Recommendation slates: 3-12 listings, ~15% unknown, clicks falling with position."""
    rng = np.random.default_rng(seed)
    rows = []
    for slate in range(n_slates):
        user = 1000 + slate // 8
        step = slate % 8
        size = int(rng.integers(3, 13))
        items = rng.integers(1, 4000, size) + 10
        items[rng.random(size) < 0.15] = 0
        weights = 0.12 * 0.85 ** np.arange(size) * (items != 0)
        choice = rng.choice(size + 1, p=np.r_[weights, 1 - weights.sum()])
        clicked = choice + 1 if choice < size else 0
        for position in range(1, size + 1):
            rows.append((user, step, size, position, int(items[position - 1]),
                         CATEGORIES[int(rng.integers(len(CATEGORIES)))], clicked))
    return pd.DataFrame(rows, columns=["user_id", "interaction_step", "slate_size", "display_position",
                                       "item_id", "main_category", "clicked_position"])


@pytest.fixture(scope="module")
def frame():
    return make_frame()


@pytest.fixture(scope="module")
def slates(frame):
    ctr, per_size = sb.ctr_by_size_and_position(frame)
    return sb.build_slates(frame, ctr, sorted(per_size.index)), ctr


def test_ctr_table_matches_manual_count(frame):
    ctr, per_size = sb.ctr_by_size_and_position(frame)
    known = frame[(frame.item_id != 0) & (frame.slate_size == 8) & (frame.display_position == 3)]
    assert ctr[8, 3] == pytest.approx((known.clicked_position == 3).mean())
    assert per_size.sum() == frame.drop_duplicates(["user_id", "interaction_step"]).shape[0]


def test_boost_off_reproduces_real_rates(slates):
    s, ctr = slates
    # With lambda applied only when a listing moves, the boost-off world is the real click model.
    size = np.bincount(s.slate)[s.slate]  # listings per slate equals slate size here
    expected = np.where(s.identified, ctr[size, s.position], 0.0)
    assert np.allclose(s.p_off, expected)
    assert np.all(s.p_off[~s.identified] == 0) and np.all(s.p_on[~s.identified] == 0)


def test_boosted_listings_move_to_top_in_original_order(slates):
    s, _ = slates
    for slate in np.unique(s.slate[s.boosted])[:200]:
        rows = np.flatnonzero(s.slate == slate)
        boosted = s.boosted[rows]
        # Boosted listings take positions 1..k, in their original order; the rest follow.
        assert list(s.new_position[rows][boosted]) == list(range(1, boosted.sum() + 1))
        rest = s.new_position[rows][~boosted]
        assert list(rest) == sorted(rest)
    unaffected = ~np.isin(s.slate, np.unique(s.slate[s.boosted]))
    assert np.all(s.new_position[unaffected] == s.position[unaffected])


def test_probabilities_are_valid(slates):
    s, _ = slates
    for p in (s.p_off, s.p_on):
        assert np.all(p >= 0)
        assert np.all(np.bincount(s.slate, weights=p) <= 1 + 1e-12)


def test_at_most_one_click_per_slate_and_same_draw_in_both_worlds(slates):
    s, _ = slates
    outcomes = sb.draw_outcomes(s, seed=1)
    for world in ("off", "on"):
        rows = outcomes[world]["row"]
        clicked = rows >= 0
        assert np.all(s.slate[rows[clicked]] == np.flatnonzero(clicked))
    # Slates the boost does not change must have identical outcomes in both worlds.
    changed = np.zeros(s.n_slates, dtype=bool)
    changed[s.slate[s.p_on != s.p_off]] = True
    assert np.array_equal(outcomes["off"]["row"][~changed], outcomes["on"]["row"][~changed])
    assert np.array_equal(outcomes["off"]["contact"][~changed], outcomes["on"]["contact"][~changed])


def test_draws_match_expected_rates_on_average(slates):
    s, _ = slates
    expected = sb.expected_metrics(s)
    click_rates = [sb.draw_outcomes(s, seed=k)["on"]["clicked"].mean() for k in range(30)]
    assert np.mean(click_rates) == pytest.approx(expected["on"]["recommendation_slate_click_rate"], rel=0.02)


def test_boost_raises_boosted_ctr_and_lowers_others(slates):
    s, _ = slates
    rel = sb.expected_metrics(s)["relative_change"]
    assert rel["boosted_listing_ctr"] > 0.05
    assert rel["other_listing_ctr"] < 0


def test_lambda_zero_means_no_effect(frame):
    ctr, per_size = sb.ctr_by_size_and_position(frame)
    s = sb.build_slates(frame, ctr, sorted(per_size.index), lam=0.0)
    assert np.allclose(s.p_on, s.p_off)


def test_size_cutoff_removes_rare_sizes(frame, monkeypatch):
    monkeypatch.setattr(sb, "MIN_SLATES_PER_SIZE", 600)
    report = sb.expected_report(frame)
    per_size = frame.drop_duplicates(["user_id", "interaction_step"]).slate_size.value_counts()
    assert report["sizes_in_scope"] == sorted(per_size[per_size >= 600].index)
    kept = per_size[per_size >= 600].sum() / per_size.sum()
    assert report["share_removed_by_size_cutoff"] == pytest.approx(1 - kept)


def test_assignment_shares():
    buyers = np.arange(1, 40001)
    assert sb.buyer_boost_on(buyers).mean() == pytest.approx(0.5, abs=0.01)
    assert sb.boosted_items(buyers).mean() == pytest.approx(1 / 16, abs=0.005)
    assert not sb.boosted_items(np.array([0]))[0]  # unknown listings are never boosted
    # A different salt gives a different assignment.
    assert (sb.buyer_boost_on(buyers) != sb.buyer_boost_on(buyers, salt=":rep1")).mean() > 0.4


def test_expected_report_and_tables(frame, slates, tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "MIN_SLATES_PER_SIZE", 100)  # the synthetic data is small
    report = sb.expected_report(frame)
    assert report["share_removed_by_size_cutoff"] == 0
    text = sb.format_expected(report)
    assert "Primary" in text and "Guardrail" in text
    assert report["power"]["primary"]["mde_abs"] > 0

    monkeypatch.setattr(sb, "OUT_DIR", tmp_path)
    s, _ = slates
    outcomes = sb.draw_outcomes(s)
    counts = sb.write_and_load(s, outcomes, "DEV", load=False)
    clicks = pq.read_table(tmp_path / "simulated_clicks.parquet").to_pandas()
    contacts = pq.read_table(tmp_path / "simulated_contacts.parquet").to_pandas()
    truth = pq.read_table(tmp_path / "ground_truth.parquet").to_pandas()
    assert counts["simulated_clicks"] == s.n_slates == len(truth)
    assert len(contacts) <= clicks.clicked_item_id.notna().sum()
    # Observed clicks equal the ground truth for the buyer's own group.
    own = np.where(clicks.variant == "boost_on", truth.clicked_item_id_on, truth.clicked_item_id_off)
    assert np.array_equal(pd.Series(own).fillna(-1).to_numpy(), clicks.clicked_item_id.fillna(-1).to_numpy())
    # Boost-on buyers see boosted clicked listings at the top.
    boosted = set(pq.read_table(tmp_path / "boosted_listings.parquet").to_pandas().item_id)
    on_boosted = clicks[(clicks.variant == "boost_on") & clicks.clicked_item_id.isin(boosted)]
    assert (on_boosted.clicked_position <= 2).mean() > 0.9
