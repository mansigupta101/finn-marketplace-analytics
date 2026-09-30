# FINN Marketplace Analytics

How buyers on FINN move from seeing a listing to clicking it, and how a change to that journey
can be measured reliably.

The project uses two kinds of data, kept strictly apart:

- **Real data.** The FINN.no slate dataset: which listings buyers were shown in search results and
  recommendations, and which listing they clicked, if any. Findings from this data are findings
  about FINN.
- **Simulated data** (Part 2). An A/B test of FINN's paid "recommended listing" boost, with clicks
  and seller contacts simulated from a click model calibrated on the real data. Results from this
  data validate the analysis method. They are not findings about FINN.

## Status

| Part | Content | Status |
|---|---|---|
| 1 | Real data: loading, data quality, dbt models, findings | Done |
| 2 | Simulated A/B test of the recommended-listing boost, with validation | Done (dashboard in progress) |
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

## Part 2: A/B test of the recommended-listing boost (simulated)

> **Everything in this section is simulated.** It shows how the effect of a paid product would be
> measured, and proves the analysis recovers known true effects. It is not a finding about FINN.

**Question.** FINN sells *Anbefalt annonse*, a paid boost that gives a listing extra visibility in
recommendations. How many extra clicks does a boost give the paying seller, and how much of that is
taken from other sellers or lost for buyers?

**Hypothesis.** Moving a promoted listing to position 1 in recommendation slates increases that
listing's click-through rate, without materially reducing buyers' overall likelihood of clicking a
recommendation (a relative drop of more than 1%). The hypothesis builds on the real finding above
that position matters in recommendations.

**Pre-registration.** The full design, metrics, parameters and decision rule are in
[`docs/ab_test_protocol.md`](docs/ab_test_protocol.md), committed to Git before the simulation was
run. The expected effects and power numbers in it were computed from the real data and the fixed
parameters, without drawing any simulated outcome.

### Design

- **Two levels of randomisation.** A fixed random 6.25% of listings are boosted, and buyers are
  split 50/50 into boost-on (boosted listings moved to position 1) and boost-off (original order).
  Comparing boosted with non-boosted listings directly would be biased, because every boosted
  listing pushes the others down; comparing two buyer groups avoids that and measures the gain for
  boosted listings, the loss for other listings and the net effect for buyers.
- **Click model calibrated on real data.** Click probabilities by position come from the real
  click-through rates in recommendation slates. One assumption, `λ = 0.5`, sets how much of the
  drop with position is caused by position itself rather than by the recommender placing better
  listings first; the data cannot separate the two. In the boost-off group, the model reproduces
  the real click rate (58.1% of slates with a click, against 58.5% in the real data).
- **Potential outcomes.** Every slate is simulated with and without the boost, using the same
  random numbers, so the true effect in the sample is known exactly and stored separately from the
  data the analysis reads.
- **Analysis.** Ratio metrics with delta-method confidence intervals clustered by buyer, and a
  bootstrap over buyers as a cross-check.

### Results

76,625 buyers and 467,239 recommendation slates. Sample ratio check: 38,181 boost-on and 38,444
boost-off buyers, p = 0.34 (passed).

| Metric | Boost-off | Boost-on | Relative change (95% CI) | True change |
|---|---|---|---|---|
| Boosted-listing click-through (primary) | 7.51% | 8.44% | +12.4% (+9.3% to +15.6%) | +11.9% |
| Slates with a click (guardrail) | 58.21% | 58.16% | −0.09% (−0.77% to +0.60%) | +0.01% |
| Other listings' click-through | 7.50% | 7.43% | −1.0% (−1.5% to −0.5%) | −0.76% |
| Boosted-listing contact rate | 0.26% | 0.26% | +0.1% (−15.0% to +17.8%) | +7.6% |

**Decision: keep the boost.** The boosted listing gains about 12% more clicks, most of it taken
from other listings, while buyers' overall clicking is unchanged. The interval includes the 10%
value hurdle, so the experiment cannot say whether the gain clears it; this was expected at the
design stage.

### Validation

- **Every interval contains its true effect**, and the decision matches the one the true effects
  imply.
- **Coverage check (pass/fail):** the buyer assignment was repeated 500 times. The share of 95%
  intervals containing the true effect was 94.6–96.2% for every metric, above the pre-registered
  93% threshold: **passed**.

### What the experiment teaches

- **Seller contacts are too rare to measure a change of this size.** The contact rate's interval
  runs from −15% to +18%. This is why contacts were a diagnostic, not the primary metric.
- **The guardrail limit sits at the edge of what the sample can measure.** Across the 500
  repetitions, the decision matched the truth in 85% of cases. The misses come from the guardrail:
  its true change is about zero, but its interval is about ±0.7% wide, so its lower end sometimes
  falls below −1% by chance and the rule wrongly asks for a gentler placement. A larger sample, or
  a limit chosen with the measurable precision in mind, would reduce these false alarms.

Full results: [`analysis/results/experiment_report.md`](analysis/results/experiment_report.md).

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

**Simulation (Part 2)**
- Clicks and contacts in the experiment are simulated; only the click-through rates by position
  that calibrate the click model are real.
- `λ = 0.5` is an assumption; it decides how large the gain and the loss are.
- Boosted listings are chosen at random, while real sellers choose which listings to boost.
- Only the reordering is simulated. The real product also shows boosted listings more often.
- Contacts follow clicks at fixed rates per category, so they add no information beyond clicks.

**Infrastructure**
- Snowflake runs on a 30-day free trial. The environment is not permanent.
- Single developer: access control and service-level agreements are out of scope. The data is
  anonymised, so no personal data handling is required.

## Project structure

```
finn-marketplace-analytics/
├── pipeline/            Loading the FINN data, simulating the experiment, and their tests
├── snowflake/           One-time Snowflake setup (warehouse, databases, role)
├── dbt_project/         dbt models and data tests
│   ├── models/staging/        Cleaned raw tables: stg_interactions, stg_exposures, stg_items
│   ├── models/intermediate/   int_slates: one row per slate, with click position and data flags
│   ├── models/marts/          Tables for analysis, including one row per buyer for the experiment
│   └── tests/                 Data rules found during loading
├── analysis/            Findings notebook, experiment analysis, saved charts and results
├── docs/                A/B test protocol
└── dashboard/           Power BI dashboard
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

**4. Simulate the experiment** (only after the protocol is committed)

```
python pipeline/simulate_boost.py expected
python pipeline/simulate_boost.py simulate
```

`expected` prints the expected effects and power numbers from the real data, without drawing any
outcomes; they go into the protocol before it is committed. `simulate` draws the outcomes and loads
them into `RAW.SIMULATION`. Then run `dbt build --profiles-dir .` again to build the experiment
models.

**5. Analyse and validate the experiment**

```
python analysis/evaluate_experiment.py all
```

This runs the analysis plan, compares it with the ground truth, runs the 500-repetition coverage
check, and writes `analysis/results/experiment_report.md` and `experiment_results.json`.

## Tests

```
python -m pytest analysis pipeline
```

- The loader tests check that the extract step keeps every real row, drops padding, matches the
  source values, samples reproducibly and counts the known data rules correctly.
- The simulation tests check that the boost-off world reproduces the real click rates, that
  boosted listings move to the top, that each slate gets at most one click, and that the
  assignment splits as specified.
- The analysis tests check that the delta-method intervals reach 95% coverage on clustered data
  with a known answer, and that ignoring the clustering would not.

The data tests run with `dbt build`.

## Data source

Eide et al., *FINN.no Slates Dataset*, RecSys 2021. https://github.com/finn-no/recsys_slates_dataset
