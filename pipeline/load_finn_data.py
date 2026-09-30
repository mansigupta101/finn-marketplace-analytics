"""Load the FINN.no slate dataset into Snowflake.

Commands:
    download   Download the three source files into data/source/.
    extract    Sample users, flatten the arrays and write Parquet files to data/processed/.
    load       Upload the Parquet files to RAW.FINN_SLATES and check the row counts.
    all        Run download, extract and load in that order.

Source structure (from FINN's documentation):
    data.npz
        userId            [users]
        click             [users, 20]      clicked item per interaction step
        click_idx         [users, 20]      slot of the clicked item in the slate
        slate_lengths     [users, 20]      number of slots in the slate
        slate             [users, 20, 25]  items shown in each slate
        interaction_type  [users, 20]      0 undefined, 1 search, 2 recommendation
    itemattr.npz
        category          [items]          item group of each item
    ind2val.json
        category, interaction_type         names for the codes above

    Item id 0 is padding (no data). Item id 1 is the "no click" item, which is always in the
    slate because the buyer can choose not to click anything. An interaction step whose
    click is 0 did not happen (the user had fewer than 20 interactions).

The data.npz file expands to several gigabytes, so it is read in chunks of users rather
than loaded into memory at once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger("load_finn_data")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = REPO_ROOT / "data" / "source"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "processed"

PAD_ITEM_ID = 0
NO_CLICK_ITEM_ID = 1
UNKNOWN_ITEM_ID = 2  # an item was shown, but its identity is missing ("<UNK>")

# Google Drive file ids used by FINN's own package (recsys_slates_dataset.data_helper).
GDRIVE_FILE_IDS = {
    "data.npz": "1XHqyk01qi9qnvBTfWWwqgDzrdjv1eBVV",  # int32 version
    "ind2val.json": "1WOCKfuttMacCb84yQYcRjxjEtgPp6F4N",
    "itemattr.npz": "1rKKyMQZqWp8vQ-Pl1SeHrQxzc5dXldnR",
}

DATA_ARRAYS = ["userId", "click", "click_idx", "slate_lengths", "slate", "interaction_type"]

# Parquet schemas, which also define the Snowflake tables.
SCHEMAS = {
    "interactions": pa.schema(
        [
            ("user_id", pa.int64()),
            ("interaction_step", pa.int16()),
            ("interaction_type_code", pa.int16()),
            ("clicked_item_id", pa.int64()),
            ("click_slot_index", pa.int16()),
            ("slate_length", pa.int16()),
        ]
    ),
    "exposures": pa.schema(
        [
            ("user_id", pa.int64()),
            ("interaction_step", pa.int16()),
            ("slot_index", pa.int16()),
            ("item_id", pa.int64()),
        ]
    ),
    "items": pa.schema([("item_id", pa.int64()), ("item_group_code", pa.int32())]),
    "item_groups": pa.schema([("item_group_code", pa.int32()), ("item_group_name", pa.string())]),
    "interaction_types": pa.schema(
        [("interaction_type_code", pa.int16()), ("interaction_type_name", pa.string())]
    ),
}

SNOWFLAKE_TYPES = {
    pa.int16(): "NUMBER(5,0)",
    pa.int32(): "NUMBER(10,0)",
    pa.int64(): "NUMBER(19,0)",
    pa.string(): "VARCHAR",
}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download(source_dir: Path) -> None:
    import gdown

    source_dir.mkdir(parents=True, exist_ok=True)
    for filename, file_id in GDRIVE_FILE_IDS.items():
        target = source_dir / filename
        if target.exists() and target.stat().st_size > 0:
            log.info("%s already exists, skipping download", target)
            continue
        log.info("Downloading %s", filename)
        result = gdown.download(f"https://drive.google.com/uc?id={file_id}", str(target), quiet=False)
        if result is None or not target.exists():
            raise RuntimeError(
                f"Download of {filename} failed. Download it manually from "
                f"https://github.com/finn-no/recsys_slates_dataset and place it in {source_dir}."
            )


# ---------------------------------------------------------------------------
# Reading data.npz in chunks
# ---------------------------------------------------------------------------


class NpyChunkReader:
    """Reads one array inside an .npz file, a block of rows at a time."""

    def __init__(self, archive: zipfile.ZipFile, name: str):
        self.name = name
        self._file = archive.open(f"{name}.npy")
        version = np.lib.format.read_magic(self._file)
        if version == (1, 0):
            shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(self._file)
        else:
            shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(self._file)
        if fortran_order:
            raise ValueError(f"{name} is stored in Fortran order and cannot be read in chunks")
        self.shape = shape
        self.dtype = dtype
        self._row_bytes = int(np.prod(shape[1:], dtype=np.int64)) * dtype.itemsize

    def read_rows(self, n_rows: int) -> np.ndarray:
        wanted = n_rows * self._row_bytes
        parts, received = [], 0
        while received < wanted:
            block = self._file.read(wanted - received)
            if not block:
                break
            parts.append(block)
            received += len(block)
        if received != wanted:
            raise IOError(f"{self.name}: expected {wanted} bytes, got {received}")
        return np.frombuffer(b"".join(parts), dtype=self.dtype).reshape((n_rows, *self.shape[1:]))

    def close(self) -> None:
        self._file.close()


@dataclass
class ExtractStats:
    users_total: int = 0
    users_sampled: int = 0
    interactions: int = 0
    exposures: int = 0
    no_click_interactions: int = 0
    extra_recorded_slot: int = 0
    unexpected_length_differences: int = 0
    slates_with_gaps: int = 0
    slates_without_no_click_item: int = 0
    click_slot_mismatches: int = 0
    clicked_item_not_in_slate: int = 0
    slates_with_unknown_items: int = 0
    unknown_item_exposures: int = 0

# Checks that should be 0. Any other value is logged as a warning.
MUST_BE_ZERO = (
    "unexpected_length_differences",
    "slates_with_gaps",
    "slates_without_no_click_item",
    "click_slot_mismatches",
    "clicked_item_not_in_slate",
)


def flatten_chunk(
    user_ids: np.ndarray,
    click: np.ndarray,
    click_idx: np.ndarray,
    slate_lengths: np.ndarray,
    slate: np.ndarray,
    interaction_type: np.ndarray,
    stats: ExtractStats,
) -> tuple[pa.Table, pa.Table]:
    """Turns the arrays for a block of sampled users into interaction and exposure rows."""
    # Interaction steps that happened. A click of 0 means the step is padding.
    u_idx, t_idx = np.nonzero(click != PAD_ITEM_ID)

    clicked = click[u_idx, t_idx].astype(np.int64)
    slot = click_idx[u_idx, t_idx].astype(np.int64)
    length = slate_lengths[u_idx, t_idx].astype(np.int64)
    slates = slate[u_idx, t_idx, :]  # one row per interaction

    interactions = pa.table(
        {
            "user_id": user_ids[u_idx].astype(np.int64),
            "interaction_step": t_idx.astype(np.int16),
            "interaction_type_code": interaction_type[u_idx, t_idx].astype(np.int16),
            "clicked_item_id": clicked,
            "click_slot_index": slot.astype(np.int16),
            "slate_length": length.astype(np.int16),
        },
        schema=SCHEMAS["interactions"],
    )

    # Every slot that holds a real item or the no-click item. Padding slots are dropped.
    r_idx, s_idx = np.nonzero(slates != PAD_ITEM_ID)
    exposures = pa.table(
        {
            "user_id": user_ids[u_idx[r_idx]].astype(np.int64),
            "interaction_step": t_idx[r_idx].astype(np.int16),
            "slot_index": s_idx.astype(np.int16),
            "item_id": slates[r_idx, s_idx].astype(np.int64),
        },
        schema=SCHEMAS["exposures"],
    )

    # Consistency checks. They are counted, not fatal, and reported in the manifest.
    # The item list is treated as the source of truth; the recorded slate length is auxiliary.
    n_rows, n_slots = slates.shape
    filled = slates != PAD_ITEM_ID
    n_filled = filled.sum(axis=1)
    # Position after the last filled slot (0 if the slate is empty).
    last_filled = np.where(filled.any(axis=1), n_slots - np.argmax(filled[:, ::-1], axis=1), 0)
    length_minus_filled = length - n_filled

    in_range = (slot >= 0) & (slot < n_slots)
    item_at_slot = np.where(in_range, slates[np.arange(n_rows), np.clip(slot, 0, n_slots - 1)], -1)

    # Known rule: 0 or 1. A difference of 1 means the recorded length counts one position after the list ends.
    stats.extra_recorded_slot += int(np.sum(length_minus_filled == 1))
    # Should all be 0.
    stats.unexpected_length_differences += int(np.sum((length_minus_filled != 0) & (length_minus_filled != 1)))
    stats.slates_with_gaps += int(np.sum(last_filled != n_filled))
    stats.slates_without_no_click_item += int(np.sum(~np.any(slates == NO_CLICK_ITEM_ID, axis=1)))
    # Clicks: the slot index should point to the clicked item, and the item should be in the slate.
    stats.click_slot_mismatches += int(np.sum(item_at_slot != clicked))
    stats.clicked_item_not_in_slate += int(np.sum(~np.any(slates == clicked[:, None], axis=1)))
    # Informational.
    stats.slates_with_unknown_items += int(np.sum(np.any(slates == UNKNOWN_ITEM_ID, axis=1)))
    stats.unknown_item_exposures += int(np.sum(slates == UNKNOWN_ITEM_ID))
    stats.no_click_interactions += int(np.sum(clicked == NO_CLICK_ITEM_ID))
    stats.interactions += interactions.num_rows
    stats.exposures += exposures.num_rows
    return interactions, exposures


def sample_mask(n_users: int, fraction: float, seed: int) -> np.ndarray:
    """Random user sample. The same seed and fraction always select the same users."""
    return np.random.default_rng(seed).random(n_users) < fraction


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(source_dir: Path, out_dir: Path, fraction: float, seed: int, chunk_users: int) -> dict:
    if not 0 < fraction <= 1:
        raise ValueError("sample fraction must be between 0 and 1")
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = ExtractStats()

    with zipfile.ZipFile(source_dir / "data.npz") as archive:
        readers = {name: NpyChunkReader(archive, name) for name in DATA_ARRAYS}
        n_users = readers["userId"].shape[0]
        for name, reader in readers.items():
            if reader.shape[0] != n_users:
                raise ValueError(f"{name} has {reader.shape[0]} rows, userId has {n_users}")
        log.info("data.npz: %d users, slate array shape %s", n_users, readers["slate"].shape)

        keep = sample_mask(n_users, fraction, seed)
        stats.users_total = n_users
        stats.users_sampled = int(keep.sum())
        log.info("Sampling %d users (%.1f%%, seed %d)", stats.users_sampled, fraction * 100, seed)

        writers = {
            name: pq.ParquetWriter(out_dir / f"{name}.parquet", SCHEMAS[name])
            for name in ("interactions", "exposures")
        }
        try:
            for start in range(0, n_users, chunk_users):
                n = min(chunk_users, n_users - start)
                block = {name: reader.read_rows(n) for name, reader in readers.items()}
                mask = keep[start : start + n]
                if not mask.any():
                    continue
                interactions, exposures = flatten_chunk(
                    block["userId"][mask],
                    block["click"][mask],
                    block["click_idx"][mask],
                    block["slate_lengths"][mask],
                    block["slate"][mask],
                    block["interaction_type"][mask],
                    stats,
                )
                writers["interactions"].write_table(interactions)
                writers["exposures"].write_table(exposures)
                log.info("Processed users %d-%d", start, start + n - 1)
        finally:
            for writer in writers.values():
                writer.close()
            for reader in readers.values():
                reader.close()

    # Items and lookups are small and are written in full.
    with np.load(source_dir / "itemattr.npz") as itemattr:
        item_groups = itemattr["category"]
    items = pa.table(
        {
            "item_id": np.arange(len(item_groups), dtype=np.int64),
            "item_group_code": item_groups.astype(np.int32),
        },
        schema=SCHEMAS["items"],
    )
    pq.write_table(items, out_dir / "items.parquet")

    lookups = json.loads((source_dir / "ind2val.json").read_text(encoding="utf-8"))
    pq.write_table(
        pa.table(
            {
                "item_group_code": [int(k) for k in lookups["category"]],
                "item_group_name": list(lookups["category"].values()),
            },
            schema=SCHEMAS["item_groups"],
        ),
        out_dir / "item_groups.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "interaction_type_code": [int(k) for k in lookups["interaction_type"]],
                "interaction_type_name": list(lookups["interaction_type"].values()),
            },
            schema=SCHEMAS["interaction_types"],
        ),
        out_dir / "interaction_types.parquet",
    )

    row_counts = {name: pq.ParquetFile(out_dir / f"{name}.parquet").metadata.num_rows for name in SCHEMAS}
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample_fraction": fraction,
        "seed": seed,
        "source_sha256": {name: sha256_of(source_dir / name) for name in GDRIVE_FILE_IDS},
        "row_counts": row_counts,
        "checks": stats.__dict__,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info("Row counts: %s", row_counts)
    for check in MUST_BE_ZERO:
        if getattr(stats, check):
            log.warning("%s: %d interactions", check, getattr(stats, check))
    return manifest


# ---------------------------------------------------------------------------
# Load to Snowflake
# ---------------------------------------------------------------------------

TARGET_DATABASE = "RAW"
TARGET_SCHEMA = "FINN_SLATES"


def create_table_sql(name: str) -> str:
    columns = ",\n    ".join(f"{field.name.upper()} {SNOWFLAKE_TYPES[field.type]}" for field in SCHEMAS[name])
    return f"CREATE OR REPLACE TABLE {TARGET_DATABASE}.{TARGET_SCHEMA}.{name.upper()} (\n    {columns}\n)"


def load(out_dir: Path) -> None:
    import snowflake.connector
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=True)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    # Key-pair login if a private key is configured, otherwise password or access token.
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    credentials = (
        {"private_key_file": os.path.expanduser(key_path)}
        if key_path
        else {"password": os.environ["SNOWFLAKE_PASSWORD"]}
    )

    connection = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        **credentials,
        role=os.environ.get("SNOWFLAKE_ROLE", "FINN_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "FINN_WH"),
        database=TARGET_DATABASE,
        schema=TARGET_SCHEMA,
    )
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"""CREATE TABLE IF NOT EXISTS {TARGET_DATABASE}.{TARGET_SCHEMA}.LOAD_AUDIT (
                TABLE_NAME VARCHAR,
                ROW_COUNT NUMBER,
                SAMPLE_FRACTION FLOAT,
                SEED NUMBER,
                EXTRACTED_AT VARCHAR,
                LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )"""
        )
        for name in SCHEMAS:
            table = name.upper()
            path = (out_dir / f"{name}.parquet").resolve().as_posix()
            expected = manifest["row_counts"][name]
            log.info("Loading %s (%d rows)", table, expected)

            # Full reload: the table is recreated, so running the load twice gives the same result.
            cursor.execute(create_table_sql(name))
            cursor.execute(f"PUT 'file://{path}' @%{table} OVERWRITE = TRUE AUTO_COMPRESS = FALSE")
            cursor.execute(
                f"""COPY INTO {table}
                    FROM @%{table}
                    FILE_FORMAT = (TYPE = PARQUET)
                    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
                    ON_ERROR = ABORT_STATEMENT
                    PURGE = TRUE"""
            )
            loaded = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if loaded != expected:
                raise RuntimeError(f"{table}: expected {expected} rows, loaded {loaded}")
            cursor.execute(
                f"INSERT INTO LOAD_AUDIT (TABLE_NAME, ROW_COUNT, SAMPLE_FRACTION, SEED, EXTRACTED_AT) "
                f"VALUES (%s, %s, %s, %s, %s)",
                (table, loaded, manifest["sample_fraction"], manifest["seed"], manifest["created_at"]),
            )
            log.info("%s loaded and row count verified", table)
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["download", "extract", "load", "all"])
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-fraction", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--chunk-users", type=int, default=50_000)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command in ("download", "all"):
        download(args.source_dir)
    if args.command in ("extract", "all"):
        extract(args.source_dir, args.out_dir, args.sample_fraction, args.seed, args.chunk_users)
    if args.command in ("load", "all"):
        load(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
