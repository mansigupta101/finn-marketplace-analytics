"""Simulates the recommended-listing boost experiment (docs/ab_test_protocol.md).

Commands:
    expected   Computes the expected effects and the power numbers from the real data and the
               fixed parameters, without drawing any random outcomes. Run this before committing
               the protocol, and paste its output into sections 4 and 5.
    simulate   Draws the outcomes, writes them to data/simulation/ and loads them into
               RAW.SIMULATION. Run this only after the protocol is committed.

Input: real recommendation slates from the dbt models (stg_exposures, int_slates, stg_items),
cached in data/simulation/rec_slates.parquet after the first read.

Everything this script produces is SIMULATED. Only the click-through rates by position that
calibrate the click model come from real FINN data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for snowflake_utils

log = logging.getLogger("simulate_boost")

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "simulation"

# ---------------------------------------------------------------------------
# Parameters fixed in docs/ab_test_protocol.md
# ---------------------------------------------------------------------------

EXPERIMENT_ID = "recommended_listing_boost_v1"
LAMBDA = 0.5  # share of the position effect due to position itself
BOOSTED_HEX_DIGITS = {"0"}  # 1 of 16 first hex digits: 6.25% of identified listings
BOOST_ON_HEX_DIGITS = set("89abcdef")  # 8 of 16: 50% of buyers
MIN_SLATES_PER_SIZE = 1_000
SEED = 20261001
CONTACT_BASE = {"BAP": 0.05, "JOB": 0.06, "MOTOR": 0.03, "BOAT": 0.03, "REAL_ESTATE": 0.02}
CONTACT_BASE_OTHER = 0.03
DESIGN_EFFECT = 1.5
Z_ALPHA, Z_POWER = 1.959964, 0.841621  # two-sided 0.05, power 0.80

UNKNOWN_ITEM_ID = 0  # listings with a missing identity are stored as 0 in the input


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

SLATES_QUERY = """
select
    e.user_id,
    e.interaction_step,
    s.n_listings_shown as slate_size,
    e.display_position,
    iff(e.is_unknown_item, 0, e.item_id) as item_id,
    coalesce(i.main_category, 'UNKNOWN') as main_category,
    coalesce(s.clicked_display_position, 0) as clicked_position
from {db}.ANALYTICS_STAGING.STG_EXPOSURES as e
inner join {db}.ANALYTICS_INTERMEDIATE.INT_SLATES as s
    on s.user_id = e.user_id
    and s.interaction_step = e.interaction_step
left join {db}.ANALYTICS_STAGING.STG_ITEMS as i
    on i.item_id = e.item_id
where s.interaction_type = 'recommendation'
    and not s.has_removed_item
"""


def load_slates(database: str, refresh: bool) -> pd.DataFrame:
    """Real recommendation slates in scope, one row per listing shown, cached locally."""
    cache = OUT_DIR / "rec_slates.parquet"
    if cache.exists() and not refresh:
        log.info("Reading cached slates from %s", cache)
        return pd.read_parquet(cache)

    from snowflake_utils import read_query

    log.info("Reading recommendation slates from %s", database)
    frame = read_query(SLATES_QUERY.format(db=database), database=database)
    frame = frame.astype({
        "user_id": "int64", "interaction_step": "int16", "slate_size": "int16",
        "display_position": "int16", "item_id": "int64", "clicked_position": "int16",
    })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache, index=False)
    log.info("Cached %d rows to %s", len(frame), cache)
    return frame


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def first_hex_digit(key: str) -> str:
    return hashlib.md5(key.encode("utf-8")).hexdigest()[0]


def boosted_items(item_ids: np.ndarray) -> np.ndarray:
    """True for identified listings that are boosted (fixed by hash, not random draws)."""
    unique = np.unique(item_ids)
    flags = np.array([
        item != UNKNOWN_ITEM_ID
        and first_hex_digit(f"{EXPERIMENT_ID}:listing:{item}") in BOOSTED_HEX_DIGITS
        for item in unique
    ], dtype=bool)
    return flags[np.searchsorted(unique, item_ids)]


def buyer_boost_on(user_ids: np.ndarray, salt: str = "") -> np.ndarray:
    """True for buyers in the boost-on group. A salt gives a new assignment (coverage check)."""
    unique = np.unique(user_ids)
    flags = np.array([
        first_hex_digit(f"{EXPERIMENT_ID}{salt}:buyer:{user}") in BOOST_ON_HEX_DIGITS
        for user in unique
    ], dtype=bool)
    return flags[np.searchsorted(unique, user_ids)]


# ---------------------------------------------------------------------------
# Click model
# ---------------------------------------------------------------------------


def ctr_by_size_and_position(frame: pd.DataFrame) -> tuple[np.ndarray, pd.Series]:
    """Real click-through rate at each position for each slate size, over identified listings.

    Returns a table indexed [slate_size, display_position] and the number of slates per size.
    """
    max_size = int(frame.slate_size.max())
    identified = frame[frame.item_id != UNKNOWN_ITEM_ID]
    exposures = np.zeros((max_size + 1, max_size + 1))
    clicks = np.zeros((max_size + 1, max_size + 1))
    np.add.at(exposures, (identified.slate_size.to_numpy(), identified.display_position.to_numpy()), 1)
    clicked = identified[identified.clicked_position == identified.display_position]
    np.add.at(clicks, (clicked.slate_size.to_numpy(), clicked.display_position.to_numpy()), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        ctr = np.where(exposures > 0, clicks / exposures, 0.0)
    slates_per_size = (
        frame.drop_duplicates(["user_id", "interaction_step"])["slate_size"].value_counts().sort_index()
    )
    return ctr, slates_per_size


@dataclass
class Slates:
    """Recommendation slates in scope, one entry per listing shown, sorted by slate and position."""

    slate: np.ndarray  # slate index, 0..n_slates-1
    user_id: np.ndarray
    interaction_step: np.ndarray
    item_id: np.ndarray
    position: np.ndarray  # original display position
    new_position: np.ndarray  # display position when boosts are applied
    identified: np.ndarray
    boosted: np.ndarray
    contact_base: np.ndarray
    p_off: np.ndarray  # click probability, boost-off world
    p_on: np.ndarray  # click probability, boost-on world
    slate_user_id: np.ndarray
    slate_step: np.ndarray

    @property
    def n_slates(self) -> int:
        return len(self.slate_user_id)


def build_slates(frame: pd.DataFrame, ctr: np.ndarray, sizes: list[int], lam: float = LAMBDA) -> Slates:
    frame = frame[frame.slate_size.isin(sizes)].sort_values(
        ["user_id", "interaction_step", "display_position"], kind="stable"
    )
    user = frame.user_id.to_numpy()
    step = frame.interaction_step.to_numpy()
    new_slate = np.r_[True, (user[1:] != user[:-1]) | (step[1:] != step[:-1])]
    slate = np.cumsum(new_slate) - 1
    item = frame.item_id.to_numpy()
    position = frame.display_position.to_numpy()
    size = frame.slate_size.to_numpy()
    identified = item != UNKNOWN_ITEM_ID
    boosted = boosted_items(item)

    # Boost-on order: boosted listings first (in their original order), then the rest.
    order = np.lexsort((position, ~boosted, slate))
    new_position = np.empty_like(position)
    slate_sorted = slate[order]
    starts = np.r_[0, np.flatnonzero(slate_sorted[1:] != slate_sorted[:-1]) + 1]
    rank = np.arange(len(order)) - np.repeat(starts, np.diff(np.r_[starts, len(order)]))
    new_position[order] = rank + 1

    base_ctr = ctr[size, position]
    p_off = np.where(identified, base_ctr, 0.0)
    p_on = np.where(identified, ctr[size, new_position] ** lam * base_ctr ** (1 - lam), 0.0)

    # Keep each slate's total click probability at most 1, with one factor per slate for both
    # worlds. Among identified listings, reordering cannot raise the total (Hölder's inequality),
    # but a boosted listing moved above an unknown listing can, so both totals are checked.
    total_off = np.bincount(slate, weights=p_off)
    total_on = np.bincount(slate, weights=p_on)
    scale = np.maximum(np.maximum(total_off, total_on), 1.0)[slate]
    p_off, p_on = p_off / scale, p_on / scale

    categories = frame.main_category.to_numpy()
    contact_base = np.array([CONTACT_BASE.get(c, CONTACT_BASE_OTHER) for c in categories])

    return Slates(
        slate=slate, user_id=user, interaction_step=step, item_id=item, position=position,
        new_position=new_position, identified=identified, boosted=boosted,
        contact_base=contact_base, p_off=p_off, p_on=p_on,
        slate_user_id=user[new_slate], slate_step=step[new_slate],
    )


# ---------------------------------------------------------------------------
# Expected effects and power (no random draws)
# ---------------------------------------------------------------------------


def expected_metrics(s: Slates) -> dict:
    boosted = s.boosted
    other = s.identified & ~s.boosted
    result = {}
    for world, p in (("off", s.p_off), ("on", s.p_on)):
        result[world] = {
            "boosted_listing_ctr": p[boosted].sum() / boosted.sum(),
            "recommendation_slate_click_rate": p.sum() / s.n_slates,
            "other_listing_ctr": p[other].sum() / other.sum(),
            "boosted_listing_contact_rate": (p * s.contact_base)[boosted].sum() / boosted.sum(),
        }
    result["relative_change"] = {m: result["on"][m] / result["off"][m] - 1 for m in result["off"]}
    result["counts"] = {
        "slates": int(s.n_slates),
        "buyers": int(len(np.unique(s.slate_user_id))),
        "boosted_exposures": int(boosted.sum()),
        "other_identified_exposures": int(other.sum()),
        "boosted_listings": int(len(np.unique(s.item_id[boosted]))),
    }
    return result


def mde(p: float, n_per_group: float) -> float:
    return (Z_ALPHA + Z_POWER) * sqrt(DESIGN_EFFECT * 2 * p * (1 - p) / n_per_group)


def expected_report(frame: pd.DataFrame) -> dict:
    ctr, slates_per_size = ctr_by_size_and_position(frame)
    sizes = sorted(int(size) for size, n in slates_per_size.items() if n >= MIN_SLATES_PER_SIZE)
    if not sizes:
        raise ValueError(f"No slate size has at least {MIN_SLATES_PER_SIZE:,} slates")
    total_slates = int(slates_per_size.sum())
    s = build_slates(frame, ctr, sizes)
    metrics = expected_metrics(s)

    primary_p = metrics["off"]["boosted_listing_ctr"]
    guardrail_p = metrics["off"]["recommendation_slate_click_rate"]
    n_primary = metrics["counts"]["boosted_exposures"] / 2
    n_guardrail = metrics["counts"]["slates"] / 2
    power = {
        "primary": {"n_per_group": n_primary, "baseline": primary_p, "mde_abs": mde(primary_p, n_primary)},
        "guardrail": {"n_per_group": n_guardrail, "baseline": guardrail_p,
                      "mde_abs": mde(guardrail_p, n_guardrail)},
    }
    for entry in power.values():
        entry["mde_rel"] = entry["mde_abs"] / entry["baseline"]

    return {
        "sizes_in_scope": sizes,
        "slates_before_size_cutoff": total_slates,
        "share_removed_by_size_cutoff": 1 - metrics["counts"]["slates"] / total_slates,
        "metrics": metrics,
        "power": power,
    }


def format_expected(report: dict) -> str:
    m, p, c = report["metrics"], report["power"], report["metrics"]["counts"]
    rel = m["relative_change"]
    lines = [
        "Paste into section 4, 'Expected effects':",
        "",
        f"- Primary: boosted-listing click-through from {m['off']['boosted_listing_ctr']:.2%} to "
        f"{m['on']['boosted_listing_ctr']:.2%} ({rel['boosted_listing_ctr']:+.1%} relative).",
        f"- Guardrail: share of recommendation slates with a click from "
        f"{m['off']['recommendation_slate_click_rate']:.2%} to "
        f"{m['on']['recommendation_slate_click_rate']:.2%} "
        f"({rel['recommendation_slate_click_rate']:+.2%} relative).",
        f"- Other listings' click-through: {rel['other_listing_ctr']:+.2%} relative.",
        f"- Boosted-listing contact rate: {rel['boosted_listing_contact_rate']:+.1%} relative.",
        "",
        "Paste into section 5, power table:",
        "",
        "| Metric | `n` per group | Baseline `p` | MDE |",
        "|---|---|---|---|",
        f"| Primary | {p['primary']['n_per_group']:,.0f} boosted-listing exposures | "
        f"{p['primary']['baseline']:.2%} | {p['primary']['mde_abs'] * 100:.2f} percentage points "
        f"({p['primary']['mde_rel']:.1%} relative) |",
        f"| Guardrail | {p['guardrail']['n_per_group']:,.0f} slates | "
        f"{p['guardrail']['baseline']:.2%} | {p['guardrail']['mde_abs'] * 100:.2f} percentage points "
        f"({p['guardrail']['mde_rel']:.1%} relative) |",
        "",
        f"Scope: {c['slates']:,} recommendation slates from {c['buyers']:,} buyers; "
        f"{c['boosted_listings']:,} boosted listings. Slate sizes in scope: "
        f"{report['sizes_in_scope'][0]} to {report['sizes_in_scope'][-1]}"
        + (f" (all sizes with at least {MIN_SLATES_PER_SIZE:,} slates)" if report["sizes_in_scope"] else "")
        + f"; the size cut-off removes {report['share_removed_by_size_cutoff']:.2%} of slates.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Simulation (random draws)
# ---------------------------------------------------------------------------


def chosen_rows(s: Slates, p: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Row index of the clicked listing per slate, or -1 for no click.

    Each slate's listings, in their original order, get consecutive intervals of length p on
    [0, 1); the listing whose interval contains the slate's random number u is clicked. Using the
    same u and the same order in both worlds keeps the two outcomes as close as the model allows.
    """
    cumulative = np.cumsum(p)
    slate_start = np.r_[0.0, np.bincount(s.slate, weights=p).cumsum()[:-1]]
    upper = cumulative - slate_start[s.slate]
    lower = upper - p
    u_row = u[s.slate]
    hit = (p > 0) & (lower <= u_row) & (u_row < upper)
    clicked = np.full(s.n_slates, -1)
    rows = np.flatnonzero(hit)
    clicked[s.slate[rows]] = rows
    return clicked


def draw_outcomes(s: Slates, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    u = rng.random(s.n_slates)  # which listing is clicked
    v = rng.random(s.n_slates)  # whether the click becomes a contact
    outcomes = {}
    for world, p in (("off", s.p_off), ("on", s.p_on)):
        rows = chosen_rows(s, p, u)
        clicked = rows >= 0
        contact = np.zeros(s.n_slates, dtype=bool)
        contact[clicked] = v[clicked] < s.contact_base[rows[clicked]]
        outcomes[world] = {"row": rows, "clicked": clicked, "contact": contact}
    return outcomes


def nullable(values: np.ndarray, valid: np.ndarray, arrow_type) -> pa.Array:
    return pa.array(values, type=arrow_type, mask=~valid)


def write_and_load(s: Slates, outcomes: dict, database: str, load: bool) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slate_on = buyer_boost_on(s.slate_user_id)
    variant = np.where(slate_on, "boost_on", "boost_off")

    # Observed outcome: the one for the buyer's group.
    observed_row = np.where(slate_on, outcomes["on"]["row"], outcomes["off"]["row"])
    observed_clicked = observed_row >= 0
    observed_contact = np.where(slate_on, outcomes["on"]["contact"], outcomes["off"]["contact"])
    safe_row = np.where(observed_clicked, observed_row, 0)
    shown_position = np.where(slate_on, s.new_position[safe_row], s.position[safe_row])

    buyers, first = np.unique(s.slate_user_id, return_index=True)
    tables = {
        "experiment_assignments": pa.table({
            "user_id": pa.array(buyers, pa.int64()),
            "experiment_id": pa.array([EXPERIMENT_ID] * len(buyers), pa.string()),
            "variant": pa.array(variant[first], pa.string()),
        }),
        "boosted_listings": pa.table({
            "item_id": pa.array(np.unique(s.item_id[s.boosted]), pa.int64()),
        }),
        "simulated_clicks": pa.table({
            "user_id": pa.array(s.slate_user_id, pa.int64()),
            "interaction_step": pa.array(s.slate_step, pa.int16()),
            "variant": pa.array(variant, pa.string()),
            "clicked_item_id": nullable(s.item_id[safe_row], observed_clicked, pa.int64()),
            "clicked_position": nullable(shown_position, observed_clicked, pa.int16()),
        }),
        "simulated_contacts": pa.table({
            "user_id": pa.array(s.slate_user_id[observed_contact], pa.int64()),
            "interaction_step": pa.array(s.slate_step[observed_contact], pa.int16()),
            "item_id": pa.array(s.item_id[safe_row][observed_contact], pa.int64()),
        }),
    }
    truth = {}
    for world in ("off", "on"):
        rows = outcomes[world]["row"]
        clicked = rows >= 0
        truth[f"clicked_item_id_{world}"] = nullable(s.item_id[np.where(clicked, rows, 0)], clicked, pa.int64())
        truth[f"contact_{world}"] = pa.array(outcomes[world]["contact"], pa.bool_())
    tables["ground_truth"] = pa.table({
        "user_id": pa.array(s.slate_user_id, pa.int64()),
        "interaction_step": pa.array(s.slate_step, pa.int16()),
        **truth,
    })

    row_counts = {}
    for name, table in tables.items():
        pq.write_table(table, OUT_DIR / f"{name}.parquet")
        row_counts[name] = table.num_rows
    log.info("Wrote %s", row_counts)

    if load:
        from snowflake_utils import connect, load_parquet

        connection = connect(database="RAW")
        try:
            cursor = connection.cursor()
            cursor.execute("CREATE SCHEMA IF NOT EXISTS RAW.SIMULATION")
            cursor.execute("USE SCHEMA RAW.SIMULATION")
            for name, table in tables.items():
                load_parquet(cursor, "RAW", "SIMULATION", name, OUT_DIR / f"{name}.parquet",
                             table.schema, table.num_rows)
                log.info("Loaded RAW.SIMULATION.%s (%d rows)", name.upper(), table.num_rows)
        finally:
            connection.close()
    return row_counts


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["expected", "simulate"])
    parser.add_argument("--database", default=os.environ.get("FINN_DATABASE", "DEV"),
                        help="Database with the dbt models (default DEV)")
    parser.add_argument("--refresh", action="store_true", help="Re-read the slates from Snowflake")
    parser.add_argument("--no-load", action="store_true", help="Write Parquet files only, skip Snowflake")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    frame = load_slates(args.database, args.refresh)
    report = expected_report(frame)

    if args.command == "expected":
        print()
        print(format_expected(report))
        return 0

    ctr, _ = ctr_by_size_and_position(frame)
    s = build_slates(frame, ctr, report["sizes_in_scope"])
    outcomes = draw_outcomes(s)
    row_counts = write_and_load(s, outcomes, args.database, load=not args.no_load)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "experiment_id": EXPERIMENT_ID,
        "parameters": {
            "lambda": LAMBDA, "boosted_share": len(BOOSTED_HEX_DIGITS) / 16, "seed": SEED,
            "contact_base": CONTACT_BASE, "contact_base_other": CONTACT_BASE_OTHER,
            "min_slates_per_size": MIN_SLATES_PER_SIZE,
        },
        "expected": report,
        "row_counts": row_counts,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
