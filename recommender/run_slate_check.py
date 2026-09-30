"""Within-slate check for LightGBM option A, on VALIDATION buyers.

Run from the main folder:  python -m recommender.run_slate_check

Question: inside the slates FINN really showed, does our model put the clicked listing higher
than FINN's own order does? Option A is trained on exactly this kind of data, so this is its
fair test, and its settings are tuned on this same test (validation buyers only).

Steps:
1. Load the data and the best ALS settings.
2. Train ALS, then build option A's training rows (same rows as run_lgbm_a).
3. Take the group's real recommendation slates that contain a click, and add the features.
4. Order each slate by: FINN's order, a random order, popularity, ALS score only, and each
   option A setting.
5. Score each ordering with NDCG per buyer, and compare with FINN's order (paired difference).
6. Save the table and the best option A setting.

The test set is not touched while GROUP is 'validation'.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from recommender import als, data, features, lgbm, metrics

RESULTS = Path(__file__).resolve().parents[1] / "analysis" / "results"

GROUP = "validation"
NUM_LEAVES = [7, 31]
N_ESTIMATORS = [50, 150, 300]


def main():
    # 1. Data and ALS settings
    first5 = data.first5_clicks()
    items = data.item_features()
    buyers = data.buyer_features()
    attributes = data.item_attributes()
    impressions = data.train_impressions()
    slates = data.slate_rows(GROUP)

    with open(RESULTS / "rec_als_best_params.json") as f:
        best_als = json.load(f)

    # 2. ALS, then option A's training rows
    matrix, all_users, all_items, user_index = als.build_matrix(first5)
    item_index = {int(item): i for i, item in enumerate(all_items)}
    als_model = als.fit(matrix, best_als["factors"], best_als["regularization"], best_als["alpha"])

    train_rows = impressions.copy()
    train_rows["als_score"] = features.als_pair_scores(
        als_model, user_index, item_index, train_rows["user_id"], train_rows["item_id"]
    )
    train_rows = features.add_features(train_rows, items, buyers, attributes)

    # 3. The group's real slates that contain a click, with the same features
    has_click = slates.groupby(["user_id", "interaction_step"])["clicked"].transform("max") == 1
    slates = slates[has_click].copy()
    slates["als_score"] = features.als_pair_scores(
        als_model, user_index, item_index, slates["user_id"], slates["item_id"]
    )
    slates = features.add_features(slates, items, buyers, attributes)
    print("Slates with a click:", slates[["user_id", "interaction_step"]].drop_duplicates().shape[0],
          "  buyers:", slates["user_id"].nunique())

    # 4. Orderings (higher score = ranked higher)
    slates["finn_order"] = -slates["display_position"]
    slates["random_order"] = np.random.default_rng(42).random(len(slates))
    methods = {
        "finn_order": "finn_order",
        "random_order": "random_order",
        "popularity": "popularity",
        "als_score_only": "als_score",
    }

    settings = {}
    for num_leaves in NUM_LEAVES:
        for n_estimators in N_ESTIMATORS:
            name = f"lgbm_a_{num_leaves}leaves_{n_estimators}trees"
            ranker = lgbm.train_ranker(train_rows, ["user_id", "interaction_step"],
                                       num_leaves, n_estimators)
            slates[name] = ranker.predict(slates[features.FEATURES])
            methods[name] = name
            settings[name] = {"num_leaves": num_leaves, "n_estimators": n_estimators}
            print("trained", name)

    # 5. NDCG per buyer, and the paired difference from FINN's order
    per_buyer = {}
    for name, column in methods.items():
        per_buyer[name] = metrics.slate_ndcg_by_buyer(slates, column)

    rows = []
    for name in methods:
        values = per_buyer[name]
        mean = values.mean()
        half = 1.96 * values.std(ddof=1) / len(values) ** 0.5
        diff, diff_low, diff_high = metrics.paired_difference(values, per_buyer["finn_order"])
        rows.append({
            "model": name, "ndcg": mean, "ci_low": mean - half, "ci_high": mean + half,
            "diff_vs_finn": diff, "diff_low": diff_low, "diff_high": diff_high,
            "buyers": len(values),
        })

    result = pd.DataFrame(rows)

    # 6. Save the table and the best option A setting
    RESULTS.mkdir(parents=True, exist_ok=True)
    result.to_csv(RESULTS / f"rec_slate_check_{GROUP}.csv", index=False)
    option_a = result[result["model"].isin(settings)]
    best_name = option_a.sort_values("ndcg", ascending=False).iloc[0]["model"]
    with open(RESULTS / "rec_lgbm_a_best_params.json", "w") as f:
        json.dump(settings[best_name], f, indent=2)

    pd.set_option("display.width", 140)
    print(f"\nNDCG within real recommendation slates, {GROUP} buyers:")
    print(result.round(4).to_string(index=False))
    print("\nBest option A setting:", best_name)


if __name__ == "__main__":
    main()
