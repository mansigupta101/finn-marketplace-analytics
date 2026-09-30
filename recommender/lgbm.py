"""LightGBM ranker: train it, then use it to re-order ALS candidates."""

import lightgbm as lgb

from recommender.features import FEATURES


def train_ranker(rows, group_columns, num_leaves, n_estimators, learning_rate=0.05, seed=42):
    """Train on `rows`, which needs the FEATURES, a 'clicked' label (0/1) and group columns.

    A group is one list that was ranked together: one slate for option A, one buyer's
    candidates for option B. The ranker learns to put the clicked listing above the others
    in the same group.
    """
    rows = rows.sort_values(group_columns)
    group_sizes = rows.groupby(group_columns, sort=False).size().to_numpy()
    model = lgb.LGBMRanker(
        objective="lambdarank",
        num_leaves=num_leaves,
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        random_state=seed,
        verbose=-1,
    )
    model.fit(rows[FEATURES], rows["clicked"].astype(int), group=group_sizes)
    return model


def rank_candidates(model, candidates, k=10):
    """Re-order each buyer's candidates by the ranker's score. Returns {buyer: top-k listings}."""
    scored = candidates.copy()
    scored["score"] = model.predict(scored[FEATURES])
    scored = scored.sort_values(["user_id", "score"], ascending=[True, False])
    top = scored.groupby("user_id").head(k)
    return top.groupby("user_id")["item_id"].agg(list).to_dict()


def rank_candidates_with_scores(model, candidates, k=10):
    """Like rank_candidates, but returns a table: user_id, item_id, score, rank (best = 1)."""
    scored = candidates.copy()
    scored["score"] = model.predict(scored[FEATURES])
    scored = scored.sort_values(["user_id", "score"], ascending=[True, False])
    top = scored.groupby("user_id").head(k).copy()
    top["rank"] = top.groupby("user_id").cumcount() + 1
    return top[["user_id", "item_id", "score", "rank"]]
