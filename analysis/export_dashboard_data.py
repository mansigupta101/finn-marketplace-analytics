"""Exports the data behind the Tableau dashboard to CSV files in dashboard/data/.

Tableau Public cannot connect to Snowflake, so the dashboard reads these files. They are small
aggregates, safe to commit.

    real_search_vs_recs.csv     REAL data: one row per slate type (mart_search_vs_recs)
    real_position_ctr.csv       REAL data: click-through by slate type, slate size and position
    real_category_ctr.csv       REAL data: click-through by slate type and main category
    sim_experiment_metrics.csv  SIMULATED: one row per experiment metric, estimate, interval,
                                true effect and coverage (from analysis/results/)

Run after `dbt build` and `python analysis/evaluate_experiment.py all`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

OUT_DIR = REPO_ROOT / "dashboard" / "data"
RESULTS = REPO_ROOT / "analysis" / "results" / "experiment_results.json"

SLATE_TYPE_LABELS = {"search": "Search", "recommendation": "Recommendations"}

METRIC_INFO = {
    "boosted_listing_ctr": ("Boosted-listing click-through", "Primary", 1),
    "recommendation_slate_click_rate": ("Slates with a click", "Guardrail", 2),
    "other_listing_ctr": ("Other listings' click-through", "Diagnostic", 3),
    "boosted_listing_contact_rate": ("Boosted-listing contact rate", "Diagnostic", 4),
}


def read_mart(name: str, database: str) -> pd.DataFrame:
    from snowflake_utils import read_query

    return read_query(f"select * from {database}.ANALYTICS_MARTS.{name}", database=database)


def real_tables(read) -> dict[str, pd.DataFrame]:
    search_vs_recs = read("MART_SEARCH_VS_RECS")
    search_vs_recs = search_vs_recs[search_vs_recs.interaction_type.isin(SLATE_TYPE_LABELS)]
    search_vs_recs.insert(1, "slate_type", search_vs_recs.interaction_type.map(SLATE_TYPE_LABELS))

    position = read("MART_POSITION_CTR")
    position = position[position.interaction_type.isin(SLATE_TYPE_LABELS)]
    position.insert(1, "slate_type", position.interaction_type.map(SLATE_TYPE_LABELS))
    position = position.sort_values(["interaction_type", "slate_size", "display_position"])

    category = read("MART_CATEGORY_CTR")
    category = category[category.interaction_type.isin(SLATE_TYPE_LABELS)]
    category.insert(1, "slate_type", category.interaction_type.map(SLATE_TYPE_LABELS))
    total_exposures = category.groupby("main_category")["exposures"].transform("sum")
    # Shown in the chart: identified categories with enough data. UNKNOWN listings are never
    # clicked in FINN's data, and very small categories are too noisy.
    category["show_in_chart"] = (category.main_category != "UNKNOWN") & (total_exposures >= 10_000)

    return {
        "real_search_vs_recs": search_vs_recs,
        "real_position_ctr": position,
        "real_category_ctr": category,
    }


def experiment_table(results: dict) -> pd.DataFrame:
    analysis = results["analysis"]
    validation = results.get("validation") or {}
    rows = []
    for metric, estimate in analysis["estimates"].items():
        label, role, order = METRIC_INFO[metric]
        row = {
            "metric": metric,
            "metric_label": label,
            "role": role,
            "sort_order": order,
            "rate_boost_off": estimate["rate_control"],
            "rate_boost_on": estimate["rate_treatment"],
            "relative_change": estimate["rel_change"],
            "ci_low": estimate["rel_ci"][0],
            "ci_high": estimate["rel_ci"][1],
            "ci_width": estimate["rel_ci"][1] - estimate["rel_ci"][0],
        }
        if validation:
            row["true_relative_change"] = validation["true_effects"][metric]["rel_change"]
            row["coverage_relative"] = validation["coverage_check"]["coverage"][metric]["relative"]
            row["interval_contains_truth"] = validation["main_run_vs_truth"][metric]["interval_contains_truth"]
        rows.append(row)
    table = pd.DataFrame(rows).sort_values("sort_order")
    table["decision"] = analysis["decision"]
    table["data"] = "Simulated"
    return table


def export(read, results_path: Path = RESULTS, out_dir: Path = OUT_DIR) -> dict[str, int]:
    tables = real_tables(read)
    tables["sim_experiment_metrics"] = experiment_table(json.loads(results_path.read_text(encoding="utf-8")))
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, frame in tables.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False)
        counts[name] = len(frame)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default=os.environ.get("FINN_DATABASE", "DEV"))
    args = parser.parse_args(argv)
    counts = export(lambda name: read_mart(name, args.database))
    for name, n in counts.items():
        print(f"dashboard/data/{name}.csv: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
