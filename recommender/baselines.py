"""Baselines: popularity and category popularity, from the first 5 interactions only."""

from __future__ import annotations

from typing import Dict, Iterable, List, Set

import pandas as pd


def _ranked(items: pd.DataFrame, limit: int) -> List[int]:
    ordered = items.sort_values(["n_clicks_first5", "item_id"], ascending=[False, True])
    return ordered["item_id"].head(limit).tolist()


def _fill(pool: List[int], seen: Set[int], k: int, fallback: List[int]) -> List[int]:
    out = [i for i in pool if i not in seen][:k]
    for i in fallback:
        if len(out) >= k:
            break
        if i not in seen and i not in out:
            out.append(i)
    return out


def popularity(
    items: pd.DataFrame, users: Iterable[int], seen: Dict[int, Set[int]], k: int = 10
) -> Dict[int, List[int]]:
    """Same most-clicked listings for everyone, minus what the buyer already clicked."""
    ranked = _ranked(items, k + 50)
    return {u: _fill(ranked, seen.get(u, set()), k, []) for u in users}


def category_popularity(
    items: pd.DataFrame,
    buyers: pd.DataFrame,
    users: Iterable[int],
    seen: Dict[int, Set[int]],
    k: int = 10,
) -> Dict[int, List[int]]:
    """Most-clicked listings in the buyer's top category; global popularity fills gaps
    and covers buyers with no category (no clicks in their first 5 interactions)."""
    global_ranked = _ranked(items, k + 50)
    by_category = {
        cat: _ranked(group, k + 50) for cat, group in items.groupby("main_category")
    }
    top_category = buyers.set_index("user_id")["top_category"].to_dict()

    recs = {}
    for u in users:
        cat = top_category.get(u)
        pool = by_category.get(cat, global_ranked) if isinstance(cat, str) else global_ranked
        recs[u] = _fill(pool, seen.get(u, set()), k, global_ranked)
    return recs
