-- A clicked listing can only be missing from the item list when an item was removed from
-- that slate. Returns clicks that break the rule; the test passes when none are returned.

select
    slate_id,
    clicked_item_id
from {{ ref('int_slates') }}
where has_click
    and clicked_display_position is null
    and not has_removed_item
