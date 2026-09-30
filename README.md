# FINN Marketplace Analytics

How buyers on FINN move from seeing an item to contacting the seller, and how a change to that
journey can be measured reliably.

The project uses two kinds of data, kept strictly apart:

- **Real data.** The FINN.no slate dataset: which items buyers were shown in search results and
  recommendations, and which item they clicked, if any. Findings from this data are findings about FINN.
- **Simulated data.** Contacts, deals and a "Message the seller" prompt experiment, generated on top
  of the real clicks. Results from this data validate the analysis method. They are not findings about FINN.

> Work in progress. Done so far: repository setup, Snowflake setup, and loading the real data.

## Setup

1. Create a Snowflake trial account and run `snowflake/setup.sql` in a worksheet. This creates the
   warehouse `FINN_WH` and the databases `RAW`, `DEV` and `PROD`.
2. Install the Python packages:
   ```
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   source .venv/bin/activate       # macOS / Linux
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your Snowflake details.
4. Copy `dbt_project/profiles.yml.example` to `dbt_project/profiles.yml`.

## Load the real data

```
python pipeline/load_finn_data.py download
python pipeline/load_finn_data.py extract --sample-fraction 0.05 --seed 42
python pipeline/load_finn_data.py load
```

`extract` takes a random 5% of users, keeps the same users for the same seed, and writes flat
tables to `data/processed/` together with `manifest.json`, which records the sample settings,
row counts, file checksums and the results of consistency checks. `load` recreates the tables in
`RAW.FINN_SLATES`, checks that each table has the expected number of rows, and records the load
in `RAW.FINN_SLATES.LOAD_AUDIT`.

| Table | One row per |
|---|---|
| `INTERACTIONS` | Interaction step: one slate shown and the buyer's response |
| `EXPOSURES` | Slot shown in a slate |
| `ITEMS` | Item, with its item group |
| `ITEM_GROUPS` | Item group, for example `BAP,antiques,Trøndelag` |
| `INTERACTION_TYPES` | Search, recommendation or undefined |

## Tests

```
python -m pytest pipeline
```

The tests build small files with the same structure as the FINN data and check that the
extract step keeps every real row, drops padding, matches the source values and samples
reproducibly.

## Data source

Eide et al., *FINN.no Slates Dataset*, RecSys 2021. https://github.com/finn-no/recsys_slates_dataset
