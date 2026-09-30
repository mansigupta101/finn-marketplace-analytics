-- Filled slots must be contiguous: no empty slot inside a slate's item list.
-- Returns the slates that break the rule; the test passes when none are returned.

select
    user_id,
    interaction_step,
    count(*) as n_filled_slots,
    max(slot_index) + 1 as last_slot_plus_one
from {{ source('finn_slates', 'exposures') }}
group by 1, 2
having count(*) <> max(slot_index) + 1
