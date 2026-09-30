"""Tune ALS on VALIDATION buyers.

Run from the main folder:  python -m recommender.run_als

Steps:
1. Load the data and build the validation targets.
2. Train ALS for each of the 12 settings and score it on validation buyers.
3. Save all scores (CSV) and the best settings (JSON) to analysis/results/.
4. Check how often the next click is inside the best model's top 200 candidates.

The test set is not touched.
"""

import json
from pathlib import Path

import pandas as pd

from recommender import als, baselines, data, metrics

RESULTS = Path(__file__).resolve().parents[1] / "analysis" / "results"

FACTORS = [128, 256]
REGULARIZATIONS = [0.01]
ALPHAS = [10.0, 40.0, 100.0]


def score_top10(model, matrix, all_users, all_items, user_index,
                users, fallback, next_click, relevant):
    """Top 10 per buyer (popularity fallback if ALS has no list), then the three metrics."""
    recs, scores = als.recommend(model, matrix, all_users, all_items, user_index, users, 10)
    top10, fallback_share = als.with_fallback(recs, users, fallback)
    per_buyer = metrics.evaluate(top10, next_click, relevant)
    return {
        "fallback_share": fallback_share,
        "hit@10": per_buyer["hit"].mean(),
        "ndcg@10": per_buyer["ndcg"].mean(),
        "recall@10": per_buyer["recall"].mean(),
    }


def candidate_check(model, matrix, all_users, all_items, user_index,
                    users, next_click, relevant):
    """Share of buyers whose next click is in the top 200, and recall@200.

    This is the ceiling for the LightGBM ranker, which can only re-order these 200.
    """
    recs, scores = als.recommend(model, matrix, all_users, all_items, user_index, users, 200)
    per_buyer = metrics.evaluate(recs, next_click, relevant, k=200)
    return {
        "hit@200": per_buyer["hit"].mean(),
        "recall@200": per_buyer["recall"].mean(),
    }


def main():
    # 1. Data and validation targets
    first5 = data.first5_clicks()
    later = data.later_clicks()
    items = data.item_features()

    seen = metrics.seen_items(first5)
    next_click, relevant = metrics.build_targets(first5, later, "validation")
    users = list(next_click)
    fallback = baselines.popularity(items, users, seen)

    matrix, all_users, all_items, user_index = als.build_matrix(first5)

    # 2. Grid of settings
    rows = []
    for factors in FACTORS:
        for regularization in REGULARIZATIONS:
            for alpha in ALPHAS:
                model = als.fit(matrix, factors, regularization, alpha)
                result = score_top10(model, matrix, all_users, all_items, user_index,
                                     users, fallback, next_click, relevant)
                result["factors"] = factors
                result["regularization"] = regularization
                result["alpha"] = alpha
                print(result)
                rows.append(result)

    grid = pd.DataFrame(rows)
    grid = grid.sort_values("ndcg@10", ascending=False)

    # 3. Save the scores and the best settings
    RESULTS.mkdir(parents=True, exist_ok=True)
    grid.to_csv(RESULTS / "rec_als_tuning_validation.csv", index=False)

    best = grid.iloc[0]
    best_settings = {
        "factors": int(best["factors"]),
        "regularization": float(best["regularization"]),
        "alpha": float(best["alpha"]),
    }
    with open(RESULTS / "rec_als_best_params.json", "w") as f:
        json.dump(best_settings, f, indent=2)

    # 4. Candidate check with the best settings
    model = als.fit(matrix, best_settings["factors"],
                    best_settings["regularization"], best_settings["alpha"])
    check = candidate_check(model, matrix, all_users, all_items, user_index,
                            users, next_click, relevant)

    pd.set_option("display.width", 120)
    print("\nAll settings, best first:")
    print(grid.round(4).to_string(index=False))
    print("\nBest settings (by NDCG@10):", best_settings)
    print("Candidate check (top 200):", {k: round(float(v), 4) for k, v in check.items()})


if __name__ == "__main__":
    main()
