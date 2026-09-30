-- One row per known listing shown in a slate, labelled clicked or not.
-- Slices used later:
--   ALS / popularity:      clicked = 1, period = 'first5' (all buyers)
--   LightGBM option A:     interaction_type = 'recommendation', split_group = 'train', period = 'later'
--   evaluation targets:    clicked = 1, split_group in ('validation','test'), period = 'later'
-- Clicks on a removed item (about 0.5% of clicks) have no shown row, so they are not included.

select
    split.split_group,
    split.period,
    split.user_id,
    split.interaction_step,
    split.interaction_seq,
    split.interaction_type,
    split.has_removed_item,
    exposures.item_id,
    exposures.display_position,
    coalesce(exposures.item_id = split.clicked_item_id, false)::int as clicked
from {{ ref('int_rec_split') }} as split
inner join {{ ref('stg_exposures') }} as exposures
    on exposures.user_id = split.user_id
    and exposures.interaction_step = split.interaction_step
where not exposures.is_unknown_item