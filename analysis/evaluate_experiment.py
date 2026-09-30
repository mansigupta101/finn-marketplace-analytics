"""Analyses the recommended-listing boost experiment, following docs/ab_test_protocol.md.

All data analysed here is SIMULATED (see the protocol). Results validate the analysis method;
they are not findings about FINN.

Commands:
    analyse    Main run: sample ratio check, estimates with delta-method intervals, bootstrap
               cross-check, decision rule and MDE sensitivity. Reads only the observed data.
    validate   Compares the main run with the ground truth, and runs the coverage check:
               the buyer assignment is repeated 500 times and each metric's 95% interval is
               checked against the true effect.
    all        Both, in that order.

Results are written to analysis/results/experiment_results.json and experiment_report.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from math import erfc, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

import simulate_boost as sim  # noqa: E402  (assignment function and design constants)

log = logging.getLogger("evaluate_experiment")

CACHE_DIR = REPO_ROOT / "data" / "simulation"
RESULTS_DIR = REPO_ROOT / "analysis" / "results"

Z = 1.959964  # 95% two-sided
N_BOOTSTRAP = 1_000
N_COVERAGE = 500
COVERAGE_PASS = 0.93
GUARDRAIL_LIMIT = -0.01  # relative change in slate click rate must stay above -1%
VALUE_HURDLE = 0.10  # reported, not a pass/fail criterion

# metric: (numerator column, denominator column), per buyer
METRICS = {
    "boosted_listing_ctr": ("boosted_clicks", "boosted_exposures"),
    "recommendation_slate_click_rate": ("slates_with_click", "slates"),
    "other_listing_ctr": ("other_clicks", "other_exposures"),
    "boosted_listing_contact_rate": ("boosted_contacts", "boosted_exposures"),
}
PRIMARY = "boosted_listing_ctr"
GUARDRAIL = "recommendation_slate_click_rate"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

BUYERS_QUERY = "select * from {db}.ANALYTICS_MARTS.MART_EXPERIMENT_BUYERS"

# Validation only: both outcomes per buyer, from the ground-truth table.
TRUTH_QUERY = """
select
    g.user_id,
    count_if(g.clicked_item_id_on is not null) as slates_with_click_on,
    count_if(g.clicked_item_id_off is not null) as slates_with_click_off,
    count_if(b_on.item_id is not null) as boosted_clicks_on,
    count_if(b_off.item_id is not null) as boosted_clicks_off,
    count_if(g.clicked_item_id_on is not null and b_on.item_id is null) as other_clicks_on,
    count_if(g.clicked_item_id_off is not null and b_off.item_id is null) as other_clicks_off,
    count_if(g.contact_on and b_on.item_id is not null) as boosted_contacts_on,
    count_if(g.contact_off and b_off.item_id is not null) as boosted_contacts_off
from RAW.SIMULATION.GROUND_TRUTH as g
left join RAW.SIMULATION.BOOSTED_LISTINGS as b_on
    on b_on.item_id = g.clicked_item_id_on
left join RAW.SIMULATION.BOOSTED_LISTINGS as b_off
    on b_off.item_id = g.clicked_item_id_off
group by 1
"""


def cached_query(name: str, sql: str, database: str, refresh: bool) -> pd.DataFrame:
    path = CACHE_DIR / f"{name}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    from snowflake_utils import read_query

    frame = read_query(sql, database=database)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def load_buyers(database: str, refresh: bool) -> pd.DataFrame:
    return cached_query("experiment_buyers", BUYERS_QUERY.format(db=database), database, refresh)


def load_truth(buyers: pd.DataFrame, database: str, refresh: bool) -> pd.DataFrame:
    """Per-buyer totals under both outcomes. Exposures and slates are the same in both groups."""
    truth = cached_query("ground_truth_buyers", TRUTH_QUERY, "RAW", refresh)
    shared = buyers[["user_id", "slates", "boosted_exposures", "other_exposures"]]
    truth = shared.merge(truth, on="user_id", how="left", validate="one_to_one")
    if truth.isna().any().any():
        raise ValueError("Ground truth is missing buyers that are in the experiment")
    return truth


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def ratio_and_variance(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """Ratio sum(y) / sum(x) over buyers, with its delta-method variance clustered by buyer."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    total_x = x.sum()
    ratio = y.sum() / total_x
    residual = y - ratio * x
    variance = n / (n - 1) * (residual ** 2).sum() / total_x ** 2
    return ratio, variance


@dataclass
class Comparison:
    rate_control: float
    rate_treatment: float
    abs_diff: float
    abs_ci: tuple[float, float]
    rel_change: float
    rel_ci: tuple[float, float]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def compare(y_t, x_t, y_c, x_c) -> Comparison:
    """Treatment (boost-on) against control (boost-off) for one ratio metric."""
    r_t, v_t = ratio_and_variance(y_t, x_t)
    r_c, v_c = ratio_and_variance(y_c, x_c)
    abs_diff = r_t - r_c
    abs_se = sqrt(v_t + v_c)
    # Relative change on the log scale: var(log r) = var(r) / r^2.
    log_diff = np.log(r_t) - np.log(r_c)
    log_se = sqrt(v_t / r_t ** 2 + v_c / r_c ** 2)
    return Comparison(
        rate_control=r_c,
        rate_treatment=r_t,
        abs_diff=abs_diff,
        abs_ci=(abs_diff - Z * abs_se, abs_diff + Z * abs_se),
        rel_change=float(np.exp(log_diff) - 1),
        rel_ci=(float(np.exp(log_diff - Z * log_se) - 1), float(np.exp(log_diff + Z * log_se) - 1)),
    )


def bootstrap_relative(y_t, x_t, y_c, x_c, n=N_BOOTSTRAP, seed=0) -> tuple[float, float]:
    """Percentile interval for the relative change, resampling buyers within each group."""
    rng = np.random.default_rng(seed)
    y_t, x_t, y_c, x_c = (np.asarray(a, dtype=float) for a in (y_t, x_t, y_c, x_c))
    draws = np.empty(n)
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(n):
            t = rng.integers(0, len(y_t), len(y_t))
            c = rng.integers(0, len(y_c), len(y_c))
            draws[i] = (y_t[t].sum() / x_t[t].sum()) / (y_c[c].sum() / x_c[c].sum()) - 1
    low, high = np.nanpercentile(draws, [2.5, 97.5])
    return float(low), float(high)


def sample_ratio_check(n_treatment: int, n_control: int) -> dict:
    """Chi-square test of the group sizes against a 50/50 split (one degree of freedom)."""
    expected = (n_treatment + n_control) / 2
    chi2 = ((n_treatment - expected) ** 2 + (n_control - expected) ** 2) / expected
    p_value = erfc(sqrt(chi2 / 2))
    return {"n_boost_on": int(n_treatment), "n_boost_off": int(n_control), "chi2": chi2,
            "p_value": p_value, "passed": p_value >= 0.001}


def decide(primary_rel_low: float, guardrail_rel_low: float) -> str:
    """Decision rule in section 7 of the protocol, applied to interval lower bounds."""
    delivers_value = primary_rel_low > 0
    costs_buyers = guardrail_rel_low <= GUARDRAIL_LIMIT
    if delivers_value and not costs_buyers:
        return "keep"
    if delivers_value:
        return "gentler placement"
    return "do not sell as is"


def mde(p: float, n_per_group: float) -> float:
    return (Z + 0.841621) * sqrt(sim.DESIGN_EFFECT * 2 * p * (1 - p) / n_per_group)


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------


def estimate_all(on: np.ndarray, columns: dict[str, np.ndarray]) -> dict[str, Comparison]:
    """Delta-method comparison for every metric, given the boost-on flag per buyer."""
    return {
        name: compare(columns[y][on], columns[x][on], columns[y][~on], columns[x][~on])
        for name, (y, x) in METRICS.items()
    }


def analyse(buyers: pd.DataFrame) -> dict:
    on = (buyers.variant == "boost_on").to_numpy()
    columns = {c: buyers[c].to_numpy(dtype=float) for c in buyers.columns if c not in ("user_id", "variant")}
    srm = sample_ratio_check(on.sum(), (~on).sum())
    estimates = estimate_all(on, columns)

    bootstrap = {
        name: bootstrap_relative(columns[y][on], columns[x][on], columns[y][~on], columns[x][~on])
        for name, (y, x) in METRICS.items()
    }
    primary, guardrail = estimates[PRIMARY], estimates[GUARDRAIL]
    decision = decide(primary.rel_ci[0], guardrail.rel_ci[0]) if srm["passed"] else "not interpreted: sample ratio check failed"

    if primary.rel_ci[0] > VALUE_HURDLE:
        hurdle = "the whole interval is above the 10% value hurdle"
    elif primary.rel_ci[1] < VALUE_HURDLE:
        hurdle = "the whole interval is below the 10% value hurdle"
    else:
        hurdle = "the interval includes the 10% value hurdle"

    n_primary = columns["boosted_exposures"][~on].sum()
    n_guardrail = columns["slates"][~on].sum()
    sensitivity = {
        "primary": {"n_control": n_primary, "baseline": primary.rate_control,
                    "mde_rel": mde(primary.rate_control, n_primary) / primary.rate_control},
        "guardrail": {"n_control": n_guardrail, "baseline": guardrail.rate_control,
                      "mde_rel": mde(guardrail.rate_control, n_guardrail) / guardrail.rate_control},
    }
    return {
        "sample_ratio_check": srm,
        "estimates": {name: c.as_dict() for name, c in estimates.items()},
        "bootstrap_rel_ci": bootstrap,
        "decision": decision,
        "value_hurdle": hurdle,
        "mde_sensitivity": sensitivity,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def true_effects(truth: pd.DataFrame) -> dict:
    """True effect in this sample: every buyer's boost-on outcome against their boost-off outcome."""
    effects = {}
    for name, (y, x) in METRICS.items():
        denominator = truth[x].sum()
        on_rate = truth[f"{y}_on"].sum() / denominator
        off_rate = truth[f"{y}_off"].sum() / denominator
        effects[name] = {"rate_off": off_rate, "rate_on": on_rate,
                         "abs_diff": on_rate - off_rate, "rel_change": on_rate / off_rate - 1}
    return effects


def true_decision(effects: dict) -> str:
    return decide(effects[PRIMARY]["rel_change"], effects[GUARDRAIL]["rel_change"])


def observed_columns(truth: pd.DataFrame, on: np.ndarray) -> dict[str, np.ndarray]:
    """What the analysis would observe under a given assignment: each buyer's own outcome."""
    columns = {c: truth[c].to_numpy(dtype=float) for c in ("slates", "boosted_exposures", "other_exposures")}
    for y, _ in METRICS.values():
        if y not in columns:
            columns[y] = np.where(on, truth[f"{y}_on"], truth[f"{y}_off"]).astype(float)
    return columns


def contains(interval: tuple[float, float], value: float) -> bool:
    return interval[0] <= value <= interval[1]


def coverage_check(truth: pd.DataFrame, effects: dict, n_reps: int = N_COVERAGE) -> dict:
    users = truth.user_id.to_numpy()
    expected_decision = true_decision(effects)
    hits_rel = {name: 0 for name in METRICS}
    hits_abs = {name: 0 for name in METRICS}
    decisions_match = 0
    for rep in range(n_reps):
        on = sim.buyer_boost_on(users, salt=f":rep{rep}")
        estimates = estimate_all(on, observed_columns(truth, on))
        for name, c in estimates.items():
            hits_rel[name] += contains(c.rel_ci, effects[name]["rel_change"])
            hits_abs[name] += contains(c.abs_ci, effects[name]["abs_diff"])
        decisions_match += decide(estimates[PRIMARY].rel_ci[0], estimates[GUARDRAIL].rel_ci[0]) == expected_decision
        if (rep + 1) % 100 == 0:
            log.info("Coverage check: %d of %d repetitions", rep + 1, n_reps)
    coverage = {
        name: {"relative": hits_rel[name] / n_reps, "absolute": hits_abs[name] / n_reps}
        for name in METRICS
    }
    passed = all(v["relative"] >= COVERAGE_PASS and v["absolute"] >= COVERAGE_PASS for v in coverage.values())
    return {"repetitions": n_reps, "coverage": coverage, "pass_threshold": COVERAGE_PASS,
            "passed": passed, "expected_decision": expected_decision,
            "decision_agreement": decisions_match / n_reps}


def validate(main: dict, truth: pd.DataFrame, n_reps: int = N_COVERAGE) -> dict:
    effects = true_effects(truth)
    main_run = {}
    for name, estimate in main["estimates"].items():
        main_run[name] = {
            "true_rel_change": effects[name]["rel_change"],
            "estimated_rel_change": estimate["rel_change"],
            "rel_ci": estimate["rel_ci"],
            "interval_contains_truth": contains(tuple(estimate["rel_ci"]), effects[name]["rel_change"]),
        }
    return {
        "true_effects": effects,
        "true_decision": true_decision(effects),
        "main_run_vs_truth": main_run,
        "main_run_decision_matches": main["decision"] == true_decision(effects),
        "coverage_check": coverage_check(truth, effects, n_reps),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

LABELS = {
    "boosted_listing_ctr": "Boosted-listing click-through (primary)",
    "recommendation_slate_click_rate": "Slates with a click (guardrail)",
    "other_listing_ctr": "Other listings' click-through",
    "boosted_listing_contact_rate": "Boosted-listing contact rate",
}


def pct(x: float, digits: int = 2) -> str:
    return f"{x:+.{digits}%}"


def report_markdown(main: dict, validation: dict | None) -> str:
    srm = main["sample_ratio_check"]
    lines = [
        "# Recommended-listing boost: results",
        "",
        "**All data here is simulated** (see `docs/ab_test_protocol.md`). The results validate the",
        "analysis method; they are not findings about FINN.",
        "",
        f"**Sample ratio check:** {srm['n_boost_on']:,} boost-on and {srm['n_boost_off']:,} boost-off "
        f"buyers, p = {srm['p_value']:.3f} ({'passed' if srm['passed'] else 'FAILED'}).",
        "",
        "| Metric | Boost-off | Boost-on | Relative change (95% CI) | Bootstrap check |",
        "|---|---|---|---|---|",
    ]
    for name, e in main["estimates"].items():
        b = main["bootstrap_rel_ci"][name]
        lines.append(
            f"| {LABELS[name]} | {e['rate_control']:.2%} | {e['rate_treatment']:.2%} | "
            f"{pct(e['rel_change'])} ({pct(e['rel_ci'][0])} to {pct(e['rel_ci'][1])}) | "
            f"{pct(b[0])} to {pct(b[1])} |"
        )
    lines += [
        "",
        f"**Decision:** {main['decision']}. Value hurdle: {main['value_hurdle']}.",
        "",
        f"**MDE sensitivity** (observed counts and control rates): primary "
        f"{main['mde_sensitivity']['primary']['mde_rel']:.1%} relative, guardrail "
        f"{main['mde_sensitivity']['guardrail']['mde_rel']:.1%} relative.",
    ]
    if validation:
        cov = validation["coverage_check"]
        lines += [
            "",
            "## Validation against the ground truth",
            "",
            "| Metric | True change | Estimated change | Interval contains truth | Coverage, relative | Coverage, absolute |",
            "|---|---|---|---|---|---|",
        ]
        for name, v in validation["main_run_vs_truth"].items():
            c = cov["coverage"][name]
            lines.append(
                f"| {LABELS[name]} | {pct(v['true_rel_change'])} | {pct(v['estimated_rel_change'])} | "
                f"{'yes' if v['interval_contains_truth'] else 'no'} | {c['relative']:.1%} | {c['absolute']:.1%} |"
            )
        lines += [
            "",
            f"**Coverage check:** {cov['repetitions']} repeated assignments; pass threshold "
            f"{cov['pass_threshold']:.0%} for every metric: **{'PASSED' if cov['passed'] else 'FAILED'}**.",
            "",
            f"**Decision:** the true effects imply \"{validation['true_decision']}\". The main run "
            f"{'reached the same decision' if validation['main_run_decision_matches'] else 'reached a different decision'}; "
            f"across the repetitions, the decision matched in {cov['decision_agreement']:.1%} of cases.",
        ]
    return "\n".join(lines) + "\n"


def write_results(main: dict, validation: dict | None) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"analysis": main, "validation": validation}
    (RESULTS_DIR / "experiment_results.json").write_text(
        json.dumps(payload, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
        encoding="utf-8",
    )
    (RESULTS_DIR / "experiment_report.md").write_text(report_markdown(main, validation), encoding="utf-8")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["analyse", "validate", "all"])
    parser.add_argument("--database", default=os.environ.get("FINN_DATABASE", "DEV"))
    parser.add_argument("--refresh", action="store_true", help="Re-read the data from Snowflake")
    parser.add_argument("--repetitions", type=int, default=N_COVERAGE)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    buyers = load_buyers(args.database, args.refresh)
    main_run = analyse(buyers)
    validation = None
    if args.command in ("validate", "all"):
        truth = load_truth(buyers, args.database, args.refresh)
        validation = validate(main_run, truth, args.repetitions)
    write_results(main_run, validation)
    print()
    print(report_markdown(main_run, validation))
    return 0


if __name__ == "__main__":
    sys.exit(main())
