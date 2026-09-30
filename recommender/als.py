"""ALS retrieval, trained on every buyer's first 5 clicks (all surfaces)."""

import numpy as np
import scipy.sparse as sp
from implicit.als import AlternatingLeastSquares
from threadpoolctl import threadpool_limits


def build_matrix(first5):
    """Buyer x listing matrix of click counts, plus the id lookups."""
    users = np.sort(first5["user_id"].unique())
    items = np.sort(first5["item_id"].unique())
    user_index = {u: i for i, u in enumerate(users)}
    item_index = {it: i for i, it in enumerate(items)}
    rows = first5["user_id"].map(user_index).to_numpy()
    cols = first5["item_id"].map(item_index).to_numpy()
    values = np.ones(len(rows), dtype=np.float32)
    matrix = sp.csr_matrix((values, (rows, cols)), shape=(len(users), len(items)))
    matrix.sum_duplicates()
    return matrix, users, items, user_index


def fit(matrix, factors, regularization, alpha, iterations=15, seed=42):
    model = AlternatingLeastSquares(
        factors=factors,
        regularization=regularization,
        alpha=alpha,
        iterations=iterations,
        random_state=seed,
    )
    # implicit is slower, not faster, when the maths library also uses several threads.
    with threadpool_limits(1, "blas"):
        model.fit(matrix, show_progress=False)
    return model


def recommend(model, matrix, users, items, user_index, target_users, n):
    """Top-n listings and scores per buyer. Listings the buyer already clicked are skipped.

    Buyers with no first-5 clicks are not in the matrix, so ALS returns nothing for them.
    """
    rows = np.array([user_index[u] for u in target_users if u in user_index])
    recs, scores = {}, {}
    for start in range(0, len(rows), 5000):
        batch = rows[start:start + 5000]
        ids, batch_scores = model.recommend(
            batch, matrix[batch], N=n, filter_already_liked_items=True
        )
        for row, row_ids, row_scores in zip(batch, ids, batch_scores):
            keep = row_ids >= 0
            user = users[row]
            recs[user] = items[row_ids[keep]].tolist()
            scores[user] = row_scores[keep].tolist()
    return recs, scores


def with_fallback(recs, target_users, fallback, k=10):
    """ALS list where ALS has one, popularity otherwise. Returns lists and fallback share."""
    out = {}
    used = 0
    for u in target_users:
        if u in recs:
            out[u] = recs[u][:k]
        else:
            out[u] = fallback[u]
            used += 1
    share = used / len(out) if out else 0.0
    return out, share
