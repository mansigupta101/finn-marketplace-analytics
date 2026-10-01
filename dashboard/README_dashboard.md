# Dashboard (Tableau Public)

Two dashboards, built in the free Tableau Public app from the CSV files in `data/`:

1. **Real data: how buyers click on FINN** (Part 1)
2. **Simulated experiment: recommended-listing boost** (Part 2)

Tableau Public cannot connect to Snowflake, so the data is exported first:

```
python analysis/export_dashboard_data.py
```

| File | Content |
|---|---|
| `real_search_vs_recs.csv` | REAL: one row per slate type |
| `real_position_ctr.csv` | REAL: clicks and exposures by slate type, slate size and position |
| `real_category_ctr.csv` | REAL: clicks and exposures by slate type and main category |
| `sim_experiment_metrics.csv` | SIMULATED: estimate, interval, true effect and coverage per metric |

## Setup

1. Download **Tableau Public** from https://public.tableau.com and create a free account.
2. Open it and choose **Connect → To a File → Text file**, then open
   `dashboard/data/real_search_vs_recs.csv`.
3. Add the other three files as separate data sources: **Data → New Data Source → Text file**, one
   file at a time. Do not join them.
4. Colours used throughout: **Search `#2a78d6`** (blue), **Recommendations `#eb6834`** (orange).
   In any sheet with `Slate Type` on Color, click the colour legend → **Edit Colors** and set them
   once; Tableau remembers them for the field.

Rates in the files are fractions (0.807 = 80.7%). To show them as percentages, right-click the field
→ **Default Properties → Number Format → Percentage**.

## Dashboard 1: Real data

**Calculated field** (in `real_position_ctr` and in `real_category_ctr`): **Analysis → Create
Calculated Field**, name it `CTR`:

```
SUM([Clicks]) / SUM([Exposures])
```

Using this field instead of averaging the rates keeps the result correct when rows are combined.

**Sheet "Click rate by slate type"** (`real_search_vs_recs`)
- Columns: `Slate Type`. Rows: `Slate Click Rate`.
- Drag `Slate Type` to Color, and `Slate Click Rate` to Label.
- Title: *Share of slates where the buyer clicked a listing*.

**Sheet "Position"** (`real_position_ctr`)
- Right-click `Display Position` → **Convert to Dimension**, then drag it to Columns. Rows: `CTR`.
- Marks card: **Line**; click Color → Markers → the option with dots.
- Drag `Slate Type` to Color.
- Drag `Slate Size` to Filters, choose any value, then right-click the filter → **Show Filter** and
  set it to **Single Value (dropdown)**. Choose 10 as the starting value.
- Title: *How often a listing is clicked, by its position in the slate*.

**Sheet "Categories"** (`real_category_ctr`)
- Drag `Show In Chart` to Filters and keep only **True**.
- Rows: `Main Category`, then `Slate Type`. Columns: `CTR`.
- Drag `Slate Type` to Color. Sort `Main Category` by `CTR`, descending.
- Title: *Click-through rate by main category*.

**Dashboard**: **Dashboard → New Dashboard**, size **Automatic**. Add a title, *Real data: how
buyers click on FINN*, a text line, *FINN.no slate dataset, random 5% sample of users (113,404
buyers)*, and the three sheets. Add a text box with the three findings from the README.

## Dashboard 2: Simulated experiment

**Sheet "Boost effect"** (`sim_experiment_metrics`)
- Drag `Role` to Filters and keep only **Primary**.
- Drag `Measure Names` to Filters and keep only `Rate Boost Off` and `Rate Boost On`.
- Columns: `Measure Names`. Rows: `Measure Values`. Drag `Measure Values` to Label.
- Title: *Boosted-listing click-through, without and with the boost*.

**Sheet "Results and validation"** (`sim_experiment_metrics`)
- Rows: `Metric Label`, then `Role`. Right-click `Metric Label` → **Sort** by `Sort Order`.
- Drag `Measure Names` to Columns, and `Measure Values` to the text area of the Marks card.
- Keep only these measures in the Measure Values card: `Relative Change`, `Ci Low`, `Ci High`,
  `True Relative Change`, `Coverage Relative`. Remove the rest.
- Format `Measure Values` as percentage with one decimal.
- Rename the column headers (right-click → **Edit Alias**): *Estimated change*, *95% CI low*,
  *95% CI high*, *True change*, *Coverage (500 repetitions)*.

**Dashboard**: title *Simulated experiment: recommended-listing boost*, and directly under it a
text box in bold: **Simulated data. These results validate the analysis method; they are not
findings about FINN.** Add both sheets and a text box with the decision and the two lessons from
the README.

## Publish

**File → Save to Tableau Public As**, and sign in. In the published workbook's settings on
public.tableau.com, turn on **Allow access** for downloading, then:

1. Copy the link into the README, under *Status* and in Part 1 and Part 2.
2. Download the workbook (`.twbx`) from the page and save it here as
   `dashboard/finn_marketplace_analytics.twbx`.
