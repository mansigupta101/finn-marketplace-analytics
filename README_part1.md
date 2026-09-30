# FINN Marketplace Analytics

How buyers on FINN move from seeing a listing to clicking it, and how a change to that journey
can be measured reliably.

The project uses two kinds of data, kept strictly apart:

- **Real data.** The FINN.no slate dataset: which listings buyers were shown in search results and
  recommendations, and which listing they clicked, if any. Findings from this data are findings
  about FINN.
- **Simulated data** (Part 2, in progress). Seller contacts, deals and a "Message the seller"
  prompt experiment, generated on top of the real clicks. Results from this data validate the
  analysis method. They are not findings about FINN.

## Status

| Part | Content | Status |
|---|---|---|
| 1 | Real data: loading, data quality, dbt models, findings | Done |
| 2 | Simulated A/B test of a "Message the seller" prompt | In progress |
| 3 | Recommender model, evaluated on real clicks | Planned |

## Findings from the real data

Based on a random 5% sample of users: 113,404 buyers and 1,862,954 slates (search result pages
and recommendation blocks). Confidence intervals are 95% and computed by resampling buyers,
because each buyer has many slates. Details are in
[`analysis/real_data_findings.ipynb`](analysis/real_data_findings.ipynb).

**1. Buyers click far more often in search than in recommendations.** A listing is clicked in
80.7% of search slates (80.6–80.8%) and 63.8% of recommendation slates (63.6–64.0%), a gap of
16.9 percentage points (16.7–17.1). A search expresses what the buyer wants, while a
recommendation has to guess.

![Share of slates with a click](analysis/figures/search_vs_recs_click_rate.png)

**2. Position barely matters in search, but clearly matters in recommendations.** In search
results, a listing is clicked about equally often at every position: about 17% in slates with 5
listings, 9% with 10 and 4.5% with 20. In 6-listing search slates, the first listing gets 1.02
times the clicks of the fifth (1.00–1.04). In recommendations, the rate falls with position: from
11.4% at position 1 to 6.1% at position 10 in 10-listing slates. Position and the recommender's
ranking are mixed in these numbers, since the listings expected to perform best are placed first.

![Click-through rate by position](analysis/figures/position_ctr.png)

**3. Search gets more clicks per listing in every category.** The gap is largest for real estate
(11.6% in search against 6.0% in recommendations) and smallest for boats (10.2% against 7.3%).
Jobs have the lowest rate in both (8.4% and 4.8%).

![Click-through rate by category](analysis/figures/category_ctr.png)

## Data quality

The loader and the dbt tests check the data against FINN's documented structure. The sample
matches FINN's published statistics: 30.3% of slates are recommendations (FINN: 30.3%), 24.4%
of slates have no click (FINN: 24%), and there are 11.14 slots per slate once removed items are
counted (FINN: 11.14).

What the checks found, and how it is handled:

- **One item removed from 11.8% of slates.** In 220,325 slates, the recorded slate length is one
  more than the item list. The list has no gaps, so one item was removed and the items after it
  moved up one position. These slates are flagged (`has_removed_item`) and left out of the
  position analysis. It happens more often in recommendation slates (17.2%) than in search
  slates (9.5%).
- **Clicks on a removed item.** In 6,792 slates (0.4%), the clicked listing is missing from the
  list. All of them are slates with a removed item: the removed item was the one clicked.
- **Listings with a missing identity.** About 15–17% of listings shown are recorded as `<UNK>`
  (item id 2). They have no category and never have a recorded click, most likely because of how
  FINN prepared the dataset. They are spread evenly across positions (14.9–15.6% at every
  position), so they lower all click-through rates by about the same share without changing the
  comparisons between positions.

These rules are enforced as dbt tests, so the build fails if the data ever breaks them.

## Limitations

**Data source**
- The FINN slate dataset is a fixed historical snapshot covering 30 days. No new data arrives,
  so the pipeline is a one-time batch load; incremental models and scheduled runs do not apply.
- The dataset records the order of each user's interactions, not timestamps, so sessions and
  time-based analysis are not possible.
- Listings are identified only by an anonymous id and an item group (main category,
  subcategory and county). There is no price, text, image or seller information.
- There are no user attributes.
- The dataset ends at the click. Contacts, messages and deals are not recorded.
- FINN capped slates at 25 listings and removed interactions with a click beyond that point.

**Analysis**
- 11.8% of slates are missing one recorded item and are excluded from the position analysis,
  which therefore keeps relatively fewer recommendation slates.
- 15–17% of listings shown have a missing identity and are never clicked in the data. They are
  excluded from the category comparison.
- Position effects are mixed with ranking effects, and the recorded order may not always match
  the exact on-screen layout.
- The 5% sample leaves small categories (for example TRAVEL, about 1,000 listings shown) too small
  to analyse.

**Infrastructure**
- Snowflake runs on a 30-day free trial. The environment is not permanent.
- Single developer: access control and service-level agreements are out of scope. The data is
  anonymised, so no personal data handling is required.

## Project structure

```
finn-marketplace-analytics/
├── pipeline/            Loading the FINN data into Snowflake, and its tests
├── snowflake/           One-time Snowflake setup (warehouse, databases, role)
├── dbt_project/         dbt models and data tests
│   ├── models/staging/        Cleaned raw tables: stg_interactions, stg_exposures, stg_items
│   ├── models/intermediate/   int_slates: one row per slate, with click position and data flags
│   ├── models/marts/          Tables for analysis: position, search vs recommendations, categories
│   └── tests/                 Data rules found during loading
├── analysis/            Findings notebook, Snowflake helper, saved charts
├── docs/                Tracking plan and A/B test protocol (Part 2)
└── dashboard/           Power BI dashboard (Part 2)
```

## Setup

Terminal commands run from the main project folder unless stated otherwise. SQL runs in a
Snowsight worksheet: in Snowflake's web interface, open **Projects → Worksheets** (called
**Workspaces** in newer versions), create a new SQL worksheet, paste the SQL and run it with
**Run All** (Cmd+Shift+Enter on a Mac, Ctrl+Shift+Enter on Windows).

### 1. Create the Snowflake objects

Create a Snowflake trial account, then run `snowflake/setup.sql` in a worksheet. It creates the
warehouse `FINN_WH` (X-Small, suspends after 60 seconds idle), the databases `RAW`, `DEV` and
`PROD`, and the role `FINN_ROLE`, which has access only to this project.

### 2. Create an access token for scripts

The loader, dbt and the notebook log in with a programmatic access token. This is required if
you signed up with Microsoft or Google, since those accounts have no Snowflake password. Run:

```sql
USE ROLE ACCOUNTADMIN;

-- Allow token logins without a network policy (any network policy that exists is still enforced).
CREATE AUTHENTICATION POLICY IF NOT EXISTS RAW.PUBLIC.FINN_PAT_POLICY
  PAT_POLICY = (NETWORK_POLICY_EVALUATION = ENFORCED_NOT_REQUIRED);

SET my_user = '"' || CURRENT_USER() || '"';
ALTER USER IDENTIFIER($my_user) SET AUTHENTICATION POLICY RAW.PUBLIC.FINN_PAT_POLICY;

ALTER USER ADD PROGRAMMATIC ACCESS TOKEN finn_project
  ROLE_RESTRICTION = 'FINN_ROLE'
  DAYS_TO_EXPIRY = 30;
```

Copy the `token_secret` value straight away; it is shown only once. Check afterwards with
`SHOW USER PROGRAMMATIC ACCESS TOKENS;` that `expires_at` is 30 days after `created_on`.

### 3. Install the Python packages

```
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install uv
uv pip install -r requirements.txt
```

Run `source .venv/bin/activate` again in every new terminal window.

### 4. Add your Snowflake login details

`.env.example` is a template. Copy it to `.env` in the same folder and fill in your values in
`.env`; leave `.env.example` unchanged. `.env` is excluded from Git.

```
cp .env.example .env
```

| Setting | Where to find it |
|---|---|
| `SNOWFLAKE_ACCOUNT` | Run `SELECT CURRENT_ORGANIZATION_NAME() \|\| '-' \|\| CURRENT_ACCOUNT_NAME();` |
| `SNOWFLAKE_USER` | The `LOGIN_NAME` value from `DESC USER` |
| `SNOWFLAKE_PASSWORD` | The token from step 2 |
| `SNOWFLAKE_ROLE` | `FINN_ROLE` |
| `SNOWFLAKE_WAREHOUSE` | `FINN_WH` |

Key-pair login is also supported: set `SNOWFLAKE_PRIVATE_KEY_PATH` instead of
`SNOWFLAKE_PASSWORD`.

### 5. Set up the dbt connection

```
cp dbt_project/profiles.yml.example dbt_project/profiles.yml
```

dbt does not read `.env` itself. Before running dbt in a new terminal window, load it:

```
set -a; source .env; set +a
```

## Running the project

**1. Load the real data**

```
python pipeline/load_finn_data.py download
python pipeline/load_finn_data.py extract
python pipeline/load_finn_data.py load
```

- `download` saves the three FINN files (about 1.3 GB) to `data/source/`. If the Google Drive
  download fails, get `data.npz`, `itemattr.npz` and `ind2val.json` from the `data/` folder of
  https://github.com/finn-no/recsys_slates_dataset.
- `extract` takes a random 5% of users (seed 42) and writes flat tables and `manifest.json`
  (sample settings, row counts, file checksums, data checks) to `data/processed/`.
- `load` recreates the tables in `RAW.FINN_SLATES`, checks the row counts, and records the load
  in `RAW.FINN_SLATES.LOAD_AUDIT`.

**2. Build the dbt models**, from the `dbt_project` folder:

```
dbt build --profiles-dir .
```

This builds all models in the `DEV` database and runs all data tests.

**3. Run the findings notebook**

```
jupyter notebook analysis/real_data_findings.ipynb
```

Choose **Run → Run All Cells**. It reads from `DEV`; set `FINN_DATABASE=PROD` to read the
production build.

## Tests

```
python -m pytest pipeline
```

The loader tests build small files with the same structure as the FINN data and check that the
extract step keeps every real row, drops padding, matches the source values, samples
reproducibly, and counts the known data rules correctly. The data tests run with `dbt build`.

## Data source

Eide et al., *FINN.no Slates Dataset*, RecSys 2021. https://github.com/finn-no/recsys_slates_dataset
