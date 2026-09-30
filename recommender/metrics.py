"""Evaluation targets and accuracy metrics (one top-10 list per buyer)."""

import numpy as np
import pandas as pd


def seen_items(first5):
    """Listings each buyer clicked in their first 5 interactions."""
    return first5.groupby("user_id")["item_id"].agg(set).to_dict()


def build_targets(
    first5, later, group
):
    """Next click and all later clicks for buyers in `group` ('validation' or 'test').

    Listings the buyer already clicked in their first 5 interactions are removed from the
    targets. Buyers with no remaining later click are not evaluated.
    """
    later = later[later["split_group"] == group]
    pairs = first5[["user_id", "item_id"]].drop_duplicates()
    merged = later.merge(pairs, on=["user_id", "item_id"], how="left", indicator=True)
    later = merged[merged["_merge"] == "left_only"].drop(columns="_merge")
    later = later.sort_values(["user_id", "interaction_seq"])

    next_click = later.groupby("user_id")["item_id"].first().to_dict()
    relevant = later.groupby("user_id")["item_id"].agg(set).to_dict()
    return next_click, relevant


def evaluate(
    recs,
    next_click,
    relevant,
    k=10,
):
    """One row per evaluated buyer: hit@k and NDCG@k (next click), recall@k (all later clicks).

    A buyer with no list counts as a miss, so every model is scored on the same buyers.
    """
    rows = []
    for user, target in next_click.items():
        top = list(recs.get(user, []))[:k]
        rank = top.index(target) + 1 if target in top else 0
        rel = relevant[user]
        rows.append(
            {
                "user_id": user,
                "hit": float(rank > 0),
                "ndcg": 1.0 / np.log2(rank + 1) if rank else 0.0,
                "recall": len(rel.intersection(top)) / len(rel),
            }
        )
    return pd.DataFrame(rows)


def summarise(per_buyer, model):
    """Mean of each metric with a 95% interval (buyers are independent)."""
    n = len(per_buyer)
    rows = []
    for metric in ["hit", "ndcg", "recall"]:
        mean = per_buyer[metric].mean()
        half = 1.96 * per_buyer[metric].std(ddof=1) / np.sqrt(n)
        rows.append(
            {"model": model, "metric": f"{metric}@10", "value": mean,
             "ci_low": mean - half, "ci_high": mean + half, "buyers": n}
        )
    return pd.DataFrame(rows)


def slate_ndcg_by_buyer(rows, score_column):
    """Mean NDCG per buyer over their real slates that contain a click.

    rows needs user_id, interaction_step, clicked, display_position and score_column (higher
    means ranked higher). Ties keep FINN's order. A slate has one clicked listing, so its NDCG
    is 1 / log2(rank + 1), where rank is where the clicked listing lands in the slate.
    """
    slate = ["user_id", "interaction_step"]
    ordered = rows.sort_values(
        slate + [score_column, "display_position"], ascending=[True, True, False, True]
    )
    ordered["rank"] = ordered.groupby(slate).cumcount() + 1
    clicked = ordered[ordered["clicked"] == 1]
    rank = clicked.groupby(slate)["rank"].min()
    per_slate = (1.0 / np.log2(rank + 1)).rename("ndcg").reset_index()
    return per_slate.groupby("user_id")["ndcg"].mean()


def paired_difference(a, b):
    """Mean of a - b across buyers with a 95% interval. a and b are per-buyer Series."""
    diff = (a - b).dropna()
    mean = diff.mean()
    half = 1.96 * diff.std(ddof=1) / np.sqrt(len(diff))
    return mean, mean - half, mean + half
