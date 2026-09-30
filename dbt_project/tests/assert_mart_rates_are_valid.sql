-- Rates in the marts must be between 0 and 1, and clicks can never exceed exposures.
-- Returns the rows that break the rule; the test passes when none are returned.

select 'mart_position_ctr' as mart, interaction_type, click_through_rate as rate
from {{ ref('mart_position_ctr') }}
where click_through_rate not between 0 and 1 or clicks > exposures

union all

select 'mart_category_ctr', interaction_type, click_through_rate
from {{ ref('mart_category_ctr') }}
where click_through_rate not between 0 and 1 or clicks > exposures

union all

select 'mart_search_vs_recs', interaction_type, slate_click_rate
from {{ ref('mart_search_vs_recs') }}
where slate_click_rate not between 0 and 1
    or unknown_listing_share not between 0 and 1
    or removed_item_share not between 0 and 1
