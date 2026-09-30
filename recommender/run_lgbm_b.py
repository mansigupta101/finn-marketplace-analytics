"""LightGBM option B, tuned on VALIDATION buyers.

Run from the main folder:  python -m recommender.run_lgbm_b

Option B trains on the same kind of rows the ranker will later score: ALS's top 200
candidates for each train buyer, labelled 1 if the buyer clicked that listing in their later
interactions (any surface) and 0 otherwise.

Steps:
1. Load the data and the best ALS settings, and train ALS.
2. Build the training rows: 200 candidates per train buyer, in chunks of buyers.
   Buyers whose later clicks are not among their 200 candidates are dropped. They contain
   only zeros, so the ranker cannot learn anything from them.
3. Build the validation candidates (same as option A).
4. Try each LightGBM setting, re-order the candidates, keep the top 10 and score it.
5. Save the scores (CSV), the best settings (JSON) and print the feature importance.

The test set is not touched.
"""

import json
from pathlib import Path

import pandas as pd

from recommender import als, baselines, data, features, lgbm, metrics

RESULTS = Path(__file__).resolve().parents[1] / "analysis" / "results"

NUM_LEAVES = [15, 63]
N_ESTIMATORS = [100, 300]
CHUNK_BUYERS = 5000


def summary_row(lists, next_click, relevant):
    per_buyer = metrics.evaluate(lists, next_click, relevant)
    return {
        "hit@10": float(per_buyer["hit"].mean()),
        "ndcg@10": float(per_buyer["ndcg"].mean()),
        "recall@10": float(per_buyer["recall"].mean()),
    }


def main():
    # 1. Data, best ALS settings, ALS
    first5 = data.first5_clicks()
    later = data.later_clicks()
    items = data.item_features()
    buyers = data.buyer_features()
    attributes = data.item_attributes()

    with open(RESULTS / "rec_als_best_params.json") as f:
        best_als = json.load(f)

    matrix, all_users, all_items, user_index = als.build_matrix(first5)
    als_model = als.fit(matrix, best_als["factors"], best_als["regularization"], best_als["alpha"])

    # 2. Training rows: ALS candidates for train buyers, labelled by their later clicks
    train_later = later[later["split_group"] == "train"][["user_id", "item_id"]]
    train_later = train_later.drop_duplicates()
    train_later["clicked"] = 1
    train_users = sorted(train_later["user_id"].unique())

    pieces = []
    for start in range(0, len(train_users), CHUNK_BUYERS):
        chunk = train_users[start:start + CHUNK_BUYERS]
        recs, scores = als.recommend(als_model, matrix, all_users, all_items,
                                     user_index, chunk, 200)
        frame = features.candidate_frame(recs, scores)
        frame = frame.merge(train_later, on=["user_id", "item_id"], how="left")
        frame["clicked"] = frame["clicked"].fillna(0).astype(int)
        has_positive = frame.groupby("user_id")["clicked"].transform("max") == 1
        pieces.append(frame[has_positive])
        print("train buyers processed:", min(start + CHUNK_BUYERS, len(train_users)))

    train_rows = pd.concat(pieces, ignore_index=True)
    train_rows = features.add_features(train_rows, items, buyers, attributes)
    print("Train buyers with a later click:", len(train_users),
          "  kept (a later click is in their 200):", train_rows["user_id"].nunique())
    print("Training rows:", len(train_rows), "  clicked:", int(train_rows["clicked"].sum()))

    # 3. Validation candidates
    next_click, relevant = metrics.build_targets(first5, later, "validation")
    users = list(next_click)
    seen = metrics.seen_items(first5)
    fallback = baselines.popularity(items, users, seen)

    recs200, scores200 = als.recommend(als_model, matrix, all_users, all_items,
                                       user_index, users, 200)
    candidates = features.candidate_frame(recs200, scores200)
    candidates = features.add_features(candidates, items, buyers, attributes)

    als_lists, _ = als.with_fallback(recs200, users, fallback)
    reference = summary_row(als_lists, next_click, relevant)
    print("ALS alone, no ranker:", {k: round(v, 4) for k, v in reference.items()})

    # 4. Grid of LightGBM settings
    rows = []
    best_model = None
    best_ndcg = -1
    for num_leaves in NUM_LEAVES:
        for n_estimators in N_ESTIMATORS:
            ranker = lgbm.train_ranker(train_rows, ["user_id"], num_leaves, n_estimators)
            top10 = lgbm.rank_candidates(ranker, candidates)
            lists, fallback_share = als.with_fallback(top10, users, fallback)
            result = summary_row(lists, next_click, relevant)
            result["fallback_share"] = fallback_share
            result["num_leaves"] = num_leaves
            result["n_estimators"] = n_estimators
            print(result)
            rows.append(result)
            if result["ndcg@10"] > best_ndcg:
                best_ndcg = result["ndcg@10"]
                best_model = ranker

    grid = pd.DataFrame(rows)
    grid = grid.sort_values("ndcg@10", ascending=False)

    # 5. Save and report
    RESULTS.mkdir(parents=True, exist_ok=True)
    grid.to_csv(RESULTS / "rec_lgbm_b_tuning_validation.csv", index=False)
    best = grid.iloc[0]
    best_settings = {
        "num_leaves": int(best["num_leaves"]),
        "n_estimators": int(best["n_estimators"]),
    }
    with open(RESULTS / "rec_lgbm_b_best_params.json", "w") as f:
        json.dump(best_settings, f, indent=2)

    gain = best_model.booster_.feature_importance(importance_type="gain")
    importance = pd.DataFrame({"feature": features.FEATURES, "share_of_gain": gain / gain.sum()})
    importance = importance.sort_values("share_of_gain", ascending=False)

    pd.set_option("display.width", 120)
    print("\nAll settings, best first:")
    print(grid.round(4).to_string(index=False))
    print("\nBest settings (by NDCG@10):", best_settings)
    print("\nFeature importance, best model:")
    print(importance.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
