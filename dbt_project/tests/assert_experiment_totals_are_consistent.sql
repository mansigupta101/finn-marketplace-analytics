-- Per-buyer totals in the experiment mart must be internally consistent: every click is on either
-- a boosted or another listing, clicks never exceed exposures, and every buyer has slates.
-- Returns the buyers that break a rule; the test passes when none are returned.

select user_id
from {{ ref('mart_experiment_buyers') }}
where slates_with_click <> boosted_clicks + other_clicks
    or boosted_clicks > boosted_exposures
    or other_clicks > other_exposures
    or boosted_contacts > boosted_clicks
    or slates_with_click > slates
    or slates = 0
