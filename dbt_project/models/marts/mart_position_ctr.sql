-- Click-through rate by display position, for each slate type and slate size.
-- One row per interaction type, number of listings in the slate, and display position.
--
-- Only slates without a removed item are used, because positions in the other slates are
-- shifted by one after the removed item. Slate size is kept as a column because a click can
-- only go to one listing per slate: in a slate with more listings, each position gets a
-- smaller share of clicks. Compare positions within the same slate size.

with clean_slates as (

    select
        user_id,
        interaction_step,
        interaction_type,
        n_listings_shown,
        clicked_display_position
    from {{ ref('int_slates') }}
    where not has_removed_item
        and n_listings_shown > 0

),

exposures as (

    select
        clean_slates.interaction_type,
        clean_slates.n_listings_shown,
        exposures.display_position,
        coalesce(clean_slates.clicked_display_position = exposures.display_position, false) as is_clicked
    from {{ ref('stg_exposures') }} as exposures
    inner join clean_slates
        on clean_slates.user_id = exposures.user_id
        and clean_slates.interaction_step = exposures.interaction_step

)

select
    interaction_type,
    n_listings_shown as slate_size,
    display_position,
    count(*) as exposures,
    count_if(is_clicked) as clicks,
    div0(count_if(is_clicked), count(*)) as click_through_rate

from exposures
group by 1, 2, 3
