# Recommended-listing boost: results

**All data here is simulated** (see `docs/ab_test_protocol.md`). The results validate the
analysis method; they are not findings about FINN.

**Sample ratio check:** 38,181 boost-on and 38,444 boost-off buyers, p = 0.342 (passed).

| Metric | Boost-off | Boost-on | Relative change (95% CI) | Bootstrap check |
|---|---|---|---|---|
| Boosted-listing click-through (primary) | 7.51% | 8.44% | +12.37% (+9.26% to +15.56%) | +9.34% to +15.60% |
| Slates with a click (guardrail) | 58.21% | 58.16% | -0.09% (-0.77% to +0.60%) | -0.76% to +0.62% |
| Other listings' click-through | 7.50% | 7.43% | -1.00% (-1.52% to -0.48%) | -1.49% to -0.48% |
| Boosted-listing contact rate | 0.26% | 0.26% | +0.07% (-14.99% to +17.79%) | -15.05% to +18.62% |

**Decision:** keep. Value hurdle: the interval includes the 10% value hurdle.

**MDE sensitivity** (observed counts and control rates): primary 5.1% relative, guardrail 0.9% relative.

## Validation against the ground truth

| Metric | True change | Estimated change | Interval contains truth | Coverage, relative | Coverage, absolute |
|---|---|---|---|---|---|
| Boosted-listing click-through (primary) | +11.94% | +12.37% | yes | 94.6% | 94.8% |
| Slates with a click (guardrail) | +0.01% | -0.09% | yes | 95.8% | 95.8% |
| Other listings' click-through | -0.76% | -1.00% | yes | 95.2% | 95.2% |
| Boosted-listing contact rate | +7.61% | +0.07% | yes | 96.2% | 96.2% |

**Coverage check:** 500 repeated assignments; pass threshold 93% for every metric: **PASSED**.

**Decision:** the true effects imply "keep". The main run reached the same decision; across the repetitions, the decision matched in 85.2% of cases.
