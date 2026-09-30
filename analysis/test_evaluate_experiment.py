"""Tests for evaluate_experiment.py: the statistics on data with a known answer, and the full
analysis on a small simulated experiment built with the same code as the real one."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evaluate_experiment as ev  # noqa: E402
from pipeline import simulate_boost as sb  # noqa: E402
from pipeline.test_simulate_boost import make_frame  # noqa: E402


def clustered_group(rng, n_buyers, p_mean):
    """Buyers with different numbers of slates and different click propensities."""
    slates = rng.poisson(6, n_buyers) + 1
    propensity = rng.beta(2, 2 * (1 - p_mean) / p_mean, n_buyers)
    clicks = rng.binomial(slates, propensity)
    return clicks, slates


def test_delta_method_interval_has_95_percent_coverage():
    rng = np.random.default_rng(0)
    hits_rel = hits_abs = 0
    reps = 400
    for _ in range(reps):
        y_t, x_t = clustered_group(rng, 2000, 0.3)
        y_c, x_c = clustered_group(rng, 2000, 0.3)
        c = ev.compare(y_t, x_t, y_c, x_c)
        hits_rel += ev.contains(c.rel_ci, 0.0)  # no true difference
        hits_abs += ev.contains(c.abs_ci, 0.0)
    assert 0.92 <= hits_rel / reps <= 0.98
    assert 0.92 <= hits_abs / reps <= 0.98


def test_ignoring_clustering_would_undercover():
    """Treating slates as independent gives intervals that are too narrow on clustered data."""
    rng = np.random.default_rng(1)
    hits = 0
    reps = 300
    for _ in range(reps):
        y_t, x_t = clustered_group(rng, 2000, 0.3)
        y_c, x_c = clustered_group(rng, 2000, 0.3)
        p_t, p_c = y_t.sum() / x_t.sum(), y_c.sum() / x_c.sum()
        se = np.sqrt(p_t * (1 - p_t) / x_t.sum() + p_c * (1 - p_c) / x_c.sum())
        hits += abs(p_t - p_c) <= 1.96 * se
    assert hits / reps < 0.90


def test_ratio_and_variance_on_known_values():
    ratio, variance = ev.ratio_and_variance(np.array([1, 2, 3]), np.array([2, 2, 2]))
    assert ratio == pytest.approx(1.0)
    # residuals -1, 0, 1 -> 3/2 * 2 / 36
    assert variance == pytest.approx(3 / 2 * 2 / 36)


def test_sample_ratio_check():
    assert ev.sample_ratio_check(50_000, 50_000)["p_value"] == pytest.approx(1.0)
    unbalanced = ev.sample_ratio_check(50_500, 49_500)  # chi-square 10
    assert unbalanced["p_value"] == pytest.approx(0.00157, rel=0.01)
    assert unbalanced["passed"]  # above the 0.001 threshold
    assert not ev.sample_ratio_check(51_000, 49_000)["passed"]


def test_decision_rule():
    assert ev.decide(0.05, -0.005) == "keep"
    assert ev.decide(0.05, -0.02) == "gentler placement"
    assert ev.decide(-0.01, 0.0) == "do not sell as is"
    assert ev.decide(0.0, 0.0) == "do not sell as is"  # the lower bound must be above 0


# ---------------------------------------------------------------------------
# Full analysis on a small simulated experiment
# ---------------------------------------------------------------------------


def buyer_tables(s, outcomes):
    """Python equivalent of mart_experiment_buyers and the validation truth query."""
    on_slate = sb.buyer_boost_on(s.slate_user_id)
    rows = []
    for world in ("off", "on"):
        r = outcomes[world]["row"]
        clicked = r >= 0
        boosted_click = clicked & s.boosted[np.where(clicked, r, 0)]
        rows.append(pd.DataFrame({
            "user_id": s.slate_user_id,
            f"slates_with_click_{world}": clicked,
            f"boosted_clicks_{world}": boosted_click,
            f"other_clicks_{world}": clicked & ~boosted_click,
            f"boosted_contacts_{world}": outcomes[world]["contact"] & boosted_click,
        }).groupby("user_id").sum())
    truth = pd.concat(rows, axis=1)
    exposures = pd.DataFrame({
        "user_id": s.user_id,
        "boosted_exposures": s.boosted,
        "other_exposures": s.identified & ~s.boosted,
    }).groupby("user_id").sum()
    slates = pd.Series(s.slate_user_id).value_counts().rename("slates")
    truth = truth.join(exposures).join(slates).reset_index().rename(columns={"index": "user_id"})

    variant = pd.Series(on_slate, index=s.slate_user_id).groupby(level=0).first()
    on = variant.reindex(truth.user_id).to_numpy()
    buyers = truth[["user_id", "slates", "boosted_exposures", "other_exposures"]].copy()
    buyers["variant"] = np.where(on, "boost_on", "boost_off")
    for y, _ in ev.METRICS.values():
        if y in ("slates",):
            continue
        buyers[y] = np.where(on, truth[f"{y}_on"], truth[f"{y}_off"])
    return buyers, truth


@pytest.fixture(scope="module")
def experiment():
    frame = make_frame(n_slates=16000, seed=3)
    ctr, per_size = sb.ctr_by_size_and_position(frame)
    s = sb.build_slates(frame, ctr, sorted(per_size.index))
    outcomes = sb.draw_outcomes(s, seed=4)
    return buyer_tables(s, outcomes)


def test_analysis_and_validation_run_end_to_end(experiment, tmp_path, monkeypatch):
    buyers, truth = experiment
    main = ev.analyse(buyers)
    assert main["sample_ratio_check"]["passed"]
    assert set(main["estimates"]) == set(ev.METRICS)

    validation = ev.validate(main, truth, n_reps=100)
    effects = validation["true_effects"]
    assert effects["boosted_listing_ctr"]["rel_change"] > 0
    assert effects["other_listing_ctr"]["rel_change"] < 0
    for metric, cov in validation["coverage_check"]["coverage"].items():
        assert 0.85 <= cov["relative"] <= 1.0, metric
        assert 0.85 <= cov["absolute"] <= 1.0, metric

    monkeypatch.setattr(ev, "RESULTS_DIR", tmp_path)
    ev.write_results(main, validation)
    report = (tmp_path / "experiment_report.md").read_text()
    assert "simulated" in report and "Coverage check" in report


def test_observed_columns_follow_the_assignment(experiment):
    _, truth = experiment
    on = np.zeros(len(truth), dtype=bool)
    columns = ev.observed_columns(truth, on)
    assert np.array_equal(columns["boosted_clicks"], truth.boosted_clicks_off.to_numpy(dtype=float))
    columns = ev.observed_columns(truth, ~on)
    assert np.array_equal(columns["boosted_clicks"], truth.boosted_clicks_on.to_numpy(dtype=float))
