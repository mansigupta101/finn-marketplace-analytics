import pandas as pd

from recommender import features, lgbm


class FakeRanker:
    def predict(self, x):
        return x["als_score"].to_numpy()


def test_rank_candidates_with_scores_table():
    candidates = pd.DataFrame({"user_id": [1, 1, 1, 2], "item_id": [5, 6, 7, 8],
                               "als_score": [0.1, 0.9, 0.5, 0.3]})
    for name in features.FEATURES:
        if name not in candidates:
            candidates[name] = 0.0
    out = lgbm.rank_candidates_with_scores(FakeRanker(), candidates, k=2)
    assert list(out["item_id"]) == [6, 7, 8]
    assert list(out["rank"]) == [1, 2, 1]
    assert list(out["score"]) == [0.9, 0.5, 0.3]
