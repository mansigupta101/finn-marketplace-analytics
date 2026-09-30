"""Evaluate the two baselines on VALIDATION buyers.

Run from the main folder:  python -m recommender.run_baselines
The test set is not touched here; it is used once at the end for all models together.
"""

from pathlib import Path

import pandas as pd

from recommender import baselines, data, metrics

RESULTS = Path(__file__).resolve().parents[1] / "analysis" / "results"


def main():
    first5 = data.first5_clicks()
    later = data.later_clicks()
    buyers = data.buyer_features()
    items = data.item_features()

    seen = metrics.seen_items(first5)
    next_click, relevant = metrics.build_targets(first5, later, "validation")
    users = list(next_click)

    summaries = []
    for name, recs in [
        ("popularity", baselines.popularity(items, users, seen)),
        ("category_popularity", baselines.category_popularity(items, buyers, users, seen)),
    ]:
        summaries.append(metrics.summarise(metrics.evaluate(recs, next_click, relevant), name))

    result = pd.concat(summaries, ignore_index=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    result.to_csv(RESULTS / "rec_baselines_validation.csv", index=False)
    pd.set_option("display.width", 120)
    print(result.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
