-- One row per slate, with what was actually in the item list and where the click happened.
--
-- Known FINN recording rule, found while loading the data:
--   In about 12% of slates, one item was removed from the list and the items after it moved
--   up one position. The recorded slate length still counts the removed item, so it is one
--   more than the number of filled slots. Positions in these slates are not reliable, so
--   position analysis uses only slates where has_removed_item is false.

with interactions as (

    select * from {{ ref('stg_interactions') }}

),

filled_slots as (

    -- All filled slots, including the "no click" item, to compare with the recorded length.
    select
        user_id,
        interaction_step,
        count(*) as n_filled_slots
    from {{ source('finn_slates', 'exposures') }}
    group by 1, 2

),

listings as (

    select
        user_id,
        interaction_step,
        count(*) as n_listings_shown,
        count_if(is_unknown_item) as n_unknown_listings
    from {{ ref('stg_exposures') }}
    group by 1, 2

),

click_positions as (

    select
        interactions.user_id,
        interactions.interaction_step,
        min(exposures.display_position) as clicked_display_position
    from interactions
    inner join {{ ref('stg_exposures') }} as exposures
        on exposures.user_id = interactions.user_id
        and exposures.interaction_step = interactions.interaction_step
        and exposures.item_id = interactions.clicked_item_id
    where interactions.has_click
    group by 1, 2

)

select
    interactions.slate_id,
    interactions.user_id,
    interactions.interaction_step,
    interactions.interaction_type,
    interactions.has_click,
    interactions.clicked_item_id,
    click_positions.clicked_display_position,
    coalesce(listings.n_listings_shown, 0) as n_listings_shown,
    coalesce(listings.n_unknown_listings, 0) as n_unknown_listings,
    interactions.recorded_slate_length,
    filled_slots.n_filled_slots,
    interactions.recorded_slate_length - filled_slots.n_filled_slots as recorded_extra_slots,
    interactions.recorded_slate_length - filled_slots.n_filled_slots = 1 as has_removed_item

from interactions
inner join filled_slots
    on filled_slots.user_id = interactions.user_id
    and filled_slots.interaction_step = interactions.interaction_step
left join listings
    on listings.user_id = interactions.user_id
    and listings.interaction_step = interactions.interaction_step
left join click_positions
    on click_positions.user_id = interactions.user_id
    and click_positions.interaction_step = interactions.interaction_step
