"""Final evaluation of every model on one group of buyers.

Run from the main folder:  python -m recommender.run_final

GROUP is 'validation' for a dry run. Change it to 'test' for the real run, and run that once.

Models: popularity, category_popularity, als (ALS alone), als_lgbm_a, als_lgbm_b.
All use the best settings already chosen on validation buyers.

Steps:
1. Load the data and the saved settings, and train ALS.
2. Train LightGBM option B (ALS candidates of train buyers) and option A (FINN's slates).
3. Build the group's top-10 lists for every model, all on the same buyers.
4. Score the lists (hit, NDCG, recall at 10) and compare models with paired differences.
5. Within real recommendation slates: FINN's order, random, popularity, ALS score, option A.
6. Save everything in analysis/results/.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from recommender import als, baselines, data, features, lgbm, metrics

RESULTS = Path(__file__).resolve().parents[1] / "analysis" / "results"

GROUP = "test"
CHUNK_BUYERS = 5000


def load_json(name):
    with open(RESULTS / name) as f:
        return json.load(f)


def main():
    print("GROUP:", GROUP)

    # 1. Data, settings, ALS
    first5 = data.first5_clicks()
    later = data.later_clicks()
    items = data.item_features()
    buyers = data.buyer_features()
    attributes = data.item_attributes()
    impressions = data.train_impressions()

    best_als = load_json("rec_als_best_params.json")
    best_b = load_json("rec_lgbm_b_best_params.json")
    best_a = load_json("rec_lgbm_a_best_params.json")

    matrix, all_users, all_items, user_index = als.build_matrix(first5)
    item_index = {int(item): i for i, item in enumerate(all_items)}
    als_model = als.fit(matrix, best_als["factors"], best_als["regularization"], best_als["alpha"])

    # 2a. Option B: ALS candidates of train buyers, labelled by their later clicks
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
    b_rows = features.add_features(pd.concat(pieces, ignore_index=True), items, buyers, attributes)
    ranker_b = lgbm.train_ranker(b_rows, ["user_id"], best_b["num_leaves"], best_b["n_estimators"])
    print("trained option B on", len(b_rows), "rows")
    del b_rows, pieces

    # 2b. Option A: listings FINN showed to train buyers, clicked or not
    a_rows = impressions.copy()
    a_rows["als_score"] = features.als_pair_scores(
        als_model, user_index, item_index, a_rows["user_id"], a_rows["item_id"]
    )
    a_rows = features.add_features(a_rows, items, buyers, attributes)
    ranker_a = lgbm.train_ranker(a_rows, ["user_id", "interaction_step"],
                                 best_a["num_leaves"], best_a["n_estimators"])
    print("trained option A on", len(a_rows), "rows")
    del a_rows

    # 3. Top-10 lists for every model, on the same buyers
    next_click, relevant = metrics.build_targets(first5, later, GROUP)
    users = list(next_click)
    seen = metrics.seen_items(first5)
    popularity_lists = baselines.popularity(items, users, seen)
    category_lists = baselines.category_popularity(items, buyers, users, seen)

    recs200, scores200 = als.recommend(als_model, matrix, all_users, all_items,
                                       user_index, users, 200)
    candidates = features.candidate_frame(recs200, scores200)
    candidates = features.add_features(candidates, items, buyers, attributes)

    lists = {"popularity": popularity_lists, "category_popularity": category_lists}
    score_lookup = {}

    # Buyers who got a popularity list instead of a personal one, per model.
    # popularity is the same list for everyone, so it has no fallback buyers.
    top_category = buyers.set_index("user_id")["top_category"].to_dict()
    fallback_users = {
        "popularity": set(),
        "category_popularity": {u for u in users if not isinstance(top_category.get(u), str)},
    }

    lists["als"], fallback_share = als.with_fallback(recs200, users, popularity_lists)
    fallback_users["als"] = {u for u in users if u not in recs200}
    score_lookup["als"] = {
        (u, item): score
        for u in users if u in recs200
        for item, score in zip(recs200[u][:10], scores200[u][:10])
    }
    print("Buyers without an ALS list (popularity fallback):", round(fallback_share, 4))

    for name, ranker in [("als_lgbm_a", ranker_a), ("als_lgbm_b", ranker_b)]:
        top = lgbm.rank_candidates_with_scores(ranker, candidates)
        top_lists = top.groupby("user_id")["item_id"].agg(list).to_dict()
        lists[name], _ = als.with_fallback(top_lists, users, popularity_lists)
        fallback_users[name] = {u for u in users if u not in top_lists}
        score_lookup[name] = dict(zip(zip(top["user_id"], top["item_id"]), top["score"]))

    # 4. Score the lists, then paired differences
    per_buyer = {}
    summaries = []
    for name, model_lists in lists.items():
        result = metrics.evaluate(model_lists, next_click, relevant)
        per_buyer[name] = result.set_index("user_id")
        summaries.append(metrics.summarise(result, name))
    summary = pd.concat(summaries, ignore_index=True)

    comparisons = [
        ("als", "category_popularity"),
        ("als_lgbm_b", "als"),
        ("als_lgbm_a", "als"),
        ("als_lgbm_b", "als_lgbm_a"),
    ]
    rows = []
    for first, second in comparisons:
        for metric in ["hit", "ndcg", "recall"]:
            diff, low, high = metrics.paired_difference(
                per_buyer[first][metric], per_buyer[second][metric]
            )
            rows.append({"comparison": f"{first} minus {second}", "metric": f"{metric}@10",
                         "difference": diff, "ci_low": low, "ci_high": high})
    differences = pd.DataFrame(rows)

    # 5. Within real recommendation slates that contain a click
    slates = data.slate_rows(GROUP)
    has_click = slates.groupby(["user_id", "interaction_step"])["clicked"].transform("max") == 1
    slates = slates[has_click].copy()
    slates["als_score"] = features.als_pair_scores(
        als_model, user_index, item_index, slates["user_id"], slates["item_id"]
    )
    slates = features.add_features(slates, items, buyers, attributes)
    slates["finn_order"] = -slates["display_position"]
    slates["random_order"] = np.random.default_rng(42).random(len(slates))
    slates["lgbm_a"] = ranker_a.predict(slates[features.FEATURES])
    methods = {
        "finn_order": "finn_order",
        "random_order": "random_order",
        "popularity": "popularity",
        "als_score_only": "als_score",
        "lgbm_a": "lgbm_a",
    }
    slate_ndcg = {name: metrics.slate_ndcg_by_buyer(slates, column)
                  for name, column in methods.items()}
    slate_rows = []
    for name in methods:
        values = slate_ndcg[name]
        mean = values.mean()
        half = 1.96 * values.std(ddof=1) / len(values) ** 0.5
        diff, low, high = metrics.paired_difference(values, slate_ndcg["finn_order"])
        slate_rows.append({"model": name, "ndcg": mean, "ci_low": mean - half,
                           "ci_high": mean + half, "diff_vs_finn": diff,
                           "diff_low": low, "diff_high": high, "buyers": len(values)})
    slate_table = pd.DataFrame(slate_rows)

    # 6. Save
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary.to_csv(RESULTS / f"rec_eval_{GROUP}_top10.csv", index=False)
    differences.to_csv(RESULTS / f"rec_eval_{GROUP}_differences.csv", index=False)
    slate_table.to_csv(RESULTS / f"rec_eval_{GROUP}_slates.csv", index=False)

    list_rows = []
    for name, model_lists in lists.items():
        lookup = score_lookup.get(name, {})
        for user, top in model_lists.items():
            is_fallback = user in fallback_users[name]
            for rank, item in enumerate(top, 1):
                list_rows.append((name, user, item, rank, lookup.get((user, item)), is_fallback))
    lists_table = pd.DataFrame(
        list_rows, columns=["model", "user_id", "item_id", "rank", "score", "is_fallback"]
    )
    lists_table.to_csv(RESULTS / f"rec_eval_{GROUP}_lists.csv", index=False)

    pd.set_option("display.width", 140)
    print(f"\nTop-10 lists, {GROUP} buyers ({len(users)} buyers):")
    print(summary.round(4).to_string(index=False))
    print("\nPaired differences (first model minus second):")
    print(differences.round(4).to_string(index=False))
    print(f"\nNDCG within real recommendation slates, {GROUP} buyers:")
    print(slate_table.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
