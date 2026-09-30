import numpy as np
import pandas as pd

from recommender import baselines, metrics


def test_evaluate_hit_ndcg_recall():
    recs = {1: [10, 20, 30], 2: [40, 50]}
    next_click = {1: 20, 2: 99}
    relevant = {1: {20, 30, 77, 88}, 2: {99}}
    out = metrics.evaluate(recs, next_click, relevant).set_index("user_id")
    assert out.loc[1, "hit"] == 1.0
    assert np.isclose(out.loc[1, "ndcg"], 1 / np.log2(3))
    assert out.loc[1, "recall"] == 0.5
    assert out.loc[2, "hit"] == 0.0 and out.loc[2, "recall"] == 0.0


def test_buyer_without_list_counts_as_miss():
    out = metrics.evaluate({}, {1: 5}, {1: {5}})
    assert out["hit"].iloc[0] == 0.0


def test_targets_drop_items_clicked_in_first5():
    first5 = pd.DataFrame({"user_id": [1], "item_id": [5]})
    later = pd.DataFrame(
        {"user_id": [1, 1], "split_group": ["test", "test"],
         "interaction_seq": [6, 7], "item_id": [5, 8]}
    )
    next_click, relevant = metrics.build_targets(first5, later, "test")
    assert next_click == {1: 8}
    assert relevant == {1: {8}}


def test_popularity_excludes_seen():
    items = pd.DataFrame({"item_id": [1, 2, 3], "n_clicks_first5": [9, 8, 7]})
    recs = baselines.popularity(items, [100], {100: {1}}, k=2)
    assert recs[100] == [2, 3]
