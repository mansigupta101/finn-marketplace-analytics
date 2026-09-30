# A/B test protocol: recommended-listing boost

| | |
|---|---|
| Experiment id | `recommended_listing_boost_v1` |
| Status | Committed before the simulation was run |
| Data | **Simulated** clicks and contacts, from a click model calibrated on real FINN data |

This protocol fixes the question, design, metrics, simulation parameters and decision rule
**before any simulated data exists**. The Git commit of this file is the record that nothing was
adjusted after seeing results. Any later change is listed under [Changes](#changes) with the
reason.

The purpose is to **validate the analysis method**: the simulation's true effects are known, so
the analysis must recover them. The results are not findings about FINN.

## 1. Question and hypothesis

FINN sells a paid product, *Anbefalt annonse* (recommended listing), that gives a listing extra
visibility in recommendations. The question is:

> How many extra clicks does a boost give the paying seller, and how much of that is taken from
> other sellers' listings or lost for buyers?

**Hypothesis.** Moving a promoted listing to position 1 in recommendation slates increases that
listing's click-through rate, without materially reducing buyers' overall likelihood of clicking a
recommendation ("materially" means a relative drop of more than 1%, see section 7). Part 1 found,
on real data, that click-through falls clearly with position in recommendation slates, so a higher
position should bring more clicks.

**Risk.** Recommendations are ordered by relevance. Moving a paid listing to the top pushes more
relevant listings down, so the boosted listing's gain may be partly taken from other sellers, and
buyers may click less overall.

## 2. Design

The boost is simulated as the simplest version of the product: in recommendation slates where a
boosted listing appears, it is moved to position 1 and the other listings move down one place.
The real product also shows boosted listings more often; that part is not simulated, because the
data only records slates that were actually shown.

The design randomises at **two levels**, so that the effect on other sellers can be measured:

- **Boosted listings.** A fixed random 6.25% of identified listings are boosted: a listing is
  boosted when the first hexadecimal digit of `md5('recommended_listing_boost_v1:listing:' ||
  item_id)` is 0. Real boosted listings are chosen by sellers, not at random; that difference is a
  limitation of the simulation.
- **Buyers: the unit of randomisation.** 50/50: a buyer is in the **boost-on** group when the first
  hexadecimal digit of `md5('recommended_listing_boost_v1:buyer:' || user_id)` is 8–f, otherwise
  **boost-off**. Boost-on buyers see boosted listings moved to the top; boost-off buyers see every
  slate in its original order.

**Why two levels.** If listings were randomised and compared directly (boosted against not
boosted), the comparison would be biased: every boosted listing pushes other listings down, so
the "not boosted" group is harmed by the treatment itself, and the gain would look larger than it
is. Randomising buyers instead gives two clean worlds, one with boosts and one without, where the
same listings appear in the same slates. Comparing them measures the gain for boosted listings,
the loss for the others, and the net effect on the whole marketplace, all without that bias.

**Scope.** Recommendation slates without a removed item (see the README), from the 5% sample,
with a slate size (number of listings) that occurs in at least 1,000 such slates. Rarer sizes are
left out because their click-through rates by position rest on too few slates to be reliable; the
share of slates this removes is reported with the power numbers in section 5.
Slates with more than one boosted listing put the boosted listings at the top in their original
order. Listings with a missing identity cannot be boosted and are never clicked.

**Eligible buyers.** Buyers with at least one recommendation slate in scope. Eligibility depends
only on the real data, not on the group, so it is the same in both groups.

## 3. Metrics

All metrics compare boost-on with boost-off buyers.

| Role | Metric | Definition |
|---|---|---|
| Primary | `boosted_listing_ctr` | Clicks on boosted listings ÷ times boosted listings were shown |
| Guardrail | `recommendation_slate_click_rate` | Recommendation slates with a click ÷ recommendation slates |
| Diagnostic | `other_listing_ctr` | Clicks on identified listings that are not boosted ÷ times they were shown |
| Diagnostic | `boosted_listing_contact_rate` | Seller contacts on boosted listings ÷ times boosted listings were shown |

- In the boost-off group, boosted listings are still shown, at their original position, so the
  primary metric compares the same listings with and without the boost.
- The **guardrail** measures what buyers get: if boosts push relevant listings down, buyers click
  less often overall.
- The **diagnostics** are reported but not part of the decision. `other_listing_ctr` shows how much
  of the gain is taken from other sellers. The contact rate puts the result in seller terms, but in
  this simulation contacts follow clicks at fixed rates, so it adds no information beyond clicks.

## 4. Simulation

**Click model.** For each slate, at most one listing is clicked, as in the real data. The chance
that the listing at position `k` is clicked is built from the real click-through rates measured in
Part 1:

```
ctr(size, k)  = real click-through rate at position k in recommendation slates of this size,
                computed over identified listings only
p(listing)    = ctr(size, k_now)^λ × ctr(size, k_original)^(1 − λ)
p(no click)   = 1 − sum of p over the slate
```

The real rate at each position mixes two things: the position itself (listings higher up are
seen more) and relevance (the recommender puts the most relevant listings first). `λ` sets how
much of the position effect is due to position itself. With `λ = 1`, moving a listing up gives it
the full rate of its new position; with `λ = 0`, moving it changes nothing. A listing keeps the
relevance of its original position wherever it is shown. In the boost-off group every listing is
at its original position, so the model reproduces the real rates. If a slate's click probabilities
add up to more than 1, both worlds' probabilities for that slate are scaled down by the same
factor so that they add up to at most 1.

| Parameter | Value |
|---|---|
| **`λ` (share of the position effect due to position itself)** | **0.5** |
| Boosted share of identified listings | 6.25% |
| Slate sizes | 1 to 24 listings |

`λ` cannot be estimated from this data, because position and relevance always move together in
FINN's logs. 0.5 is an assumption, and it is the parameter that decides how large the gain and
the loss are.

**Contacts.** A click becomes a seller contact with probability `base[category]`: BAP 0.05, JOB
0.06, MOTOR and BOAT 0.03, REAL_ESTATE 0.02, any other category 0.03. The boost does not change
these probabilities.

**Potential outcomes.** Each slate gets one random number for the click and one for the contact,
and the same numbers are used for the boost-on and boost-off version of the slate. The clicked
listing is chosen by comparing the click number with the cumulative probabilities of the listings
in their original order, so the two versions differ only where the probabilities differ. Every
buyer therefore has both outcomes, and the **true effect in this sample** is known exactly. The
observed tables contain only the outcome for the buyer's group; both outcomes are stored in a
ground-truth table that the analysis does not read.

**Expected effects.** Because the click model is fixed by the real rates and `λ`, the expected
effects can be computed from the parameters before any simulation is run. They are added here
before this file is committed:

- Primary: boosted-listing click-through from 7.54% to 8.40% (+11.4% relative).
- Guardrail: share of recommendation slates with a click from 58.09% to 58.09% (+0.00% relative).
- Other listings' click-through: −0.74% relative.
- Boosted-listing contact rate: +11.3% relative.

Under these parameters, the boost mostly moves clicks from other listings to the boosted ones,
rather than reducing buyers' overall clicking.

Random seed: `20261001`.

## 5. Power analysis

Two-sided tests, significance level 0.05, power 0.80, two equal groups of buyers. Because each
buyer has many slates, observations within a buyer are not independent; the variance is inflated
by a design effect of 1.5, a conservative assumption.

```
MDE = (1.96 + 0.84) × sqrt(design effect × 2 × p × (1 − p) / n)
```

`n` is the number of boosted-listing exposures (primary) or recommendation slates (guardrail) per
group, and `p` the baseline rate. The counts come from the real data before the simulation and are
filled in here before commit:

| Metric | `n` per group | Baseline `p` | MDE |
|---|---|---|---|
| Primary | 109,970 boosted-listing exposures | 7.54% | 0.39 percentage points (5.1% relative) |
| Guardrail | 233,620 slates | 58.09% | 0.50 percentage points (0.9% relative) |

Scope: 467,239 recommendation slates from 76,625 buyers; 27,164 boosted listings. Slate sizes in
scope: 1 to 24 (all sizes with at least 1,000 slates); the size cut-off removes 0.00% of slates.

After the experiment, the MDE is recalculated with the observed counts and rates. This is a
**sensitivity check only**; it does not change the design or the decision.

## 6. Analysis plan

1. **Sample ratio check.** Chi-square test of eligible buyers per group against 50/50. If
   p < 0.001, the assignment is faulty and no results are interpreted.
2. **Primary, guardrail and diagnostics.** Relative and absolute differences between the groups,
   with 95% confidence intervals from the **delta method for ratio metrics, clustered by buyer**.
   All metrics are ratios over slates or exposures, and one buyer contributes many of them, so the
   variance is computed from per-buyer totals, which keeps each buyer's slates together. Relative
   changes are computed on the log scale. The delta method is fast enough to be repeated in the
   coverage check below, so the method validated there is exactly the one used here. In the main
   run, a bootstrap over buyers (1,000 resamples) is reported alongside as a cross-check; it is not
   used for the decision.
3. **No segments** are analysed.
4. **Validation.**
   - **Coverage check (pass/fail).** The simulated outcomes and the boosted listings are kept
     fixed, and the buyer assignment is repeated 500 times with different salts. For each
     repetition, every metric is estimated as in the main run, and its 95% interval is compared
     with the true effect from the ground-truth table. The method passes if at least 93% of the
     500 intervals contain the true effect, for every metric. (500 repetitions give a standard
     error of about 1 percentage point, so 93% is about two standard errors below 95%. Coverage
     somewhat above 95% is expected, because the intervals are slightly conservative when the
     sample is fixed.) The repetitions also show how often the decision rule reaches the decision
     the true effects imply.
   - **Main run (sanity check).** The committed assignment is analysed once, and the estimates
     are shown next to the true effects.

## 7. Decision rule

Keep offering the boost in recommendations as it is only if both hold:

1. **It delivers value to the paying seller:** the lower bound of the 95% interval for the
   relative increase in `boosted_listing_ctr` is above 0. The estimate and its interval are also
   compared with a 10% value hurdle and reported, but the hurdle is not a pass/fail criterion:
   at the design stage, the expected effect (+11.4%) and the interval width (about ±3.6%) showed
   that the experiment cannot reliably resolve a 10% hurdle.
2. **It does not cost buyers:** the lower bound of the 95% interval for the relative change in
   `recommendation_slate_click_rate` is above −1%.

If the first holds but the second does not, the next step is a gentler placement, for example
position 2 or 3 instead of 1, or at most one boosted listing per slate. If the first does not
hold, the boost does not deliver enough value in recommendations to be sold as it is.

## 8. Data produced

The simulation writes to `RAW.SIMULATION`:

| Table | Content | Read by the analysis |
|---|---|---|
| `EXPERIMENT_ASSIGNMENTS` | One row per buyer: group | Yes |
| `BOOSTED_LISTINGS` | One row per boosted listing | Yes |
| `SIMULATED_CLICKS` | One row per recommendation slate: clicked listing and position, if any | Yes |
| `SIMULATED_CONTACTS` | One row per contact | Yes |
| `GROUND_TRUTH` | Both outcomes per slate | Validation only |

## Changes

None yet. Any change after this file is committed is listed here with the date and reason.
