-- Click-through rate by main category, for each slate type.
-- One row per interaction type and main category.
--
-- Listings whose identity is missing (item id 2) have no category and are grouped as
-- UNKNOWN. Only clicks on listings that are in the recorded item list are counted, so every
-- click has a matching exposure.

with slates as (

    select * from {{ ref('int_slates') }}

),

items as (

    select item_id, coalesce(main_category, 'UNKNOWN') as main_category
    from {{ ref('stg_items') }}

),

exposures as (

    select
        slates.interaction_type,
        items.main_category,
        count(*) as exposures
    from {{ ref('stg_exposures') }} as exposures
    inner join slates
        on slates.user_id = exposures.user_id
        and slates.interaction_step = exposures.interaction_step
    left join items
        on items.item_id = exposures.item_id
    group by 1, 2

),

clicks as (

    select
        slates.interaction_type,
        items.main_category,
        count(*) as clicks
    from slates
    left join items
        on items.item_id = slates.clicked_item_id
    where slates.has_click
        and slates.clicked_display_position is not null
    group by 1, 2

)

select
    exposures.interaction_type,
    coalesce(exposures.main_category, 'UNKNOWN') as main_category,
    exposures.exposures,
    coalesce(clicks.clicks, 0) as clicks,
    div0(coalesce(clicks.clicks, 0), exposures.exposures) as click_through_rate

from exposures
left join clicks
    on clicks.interaction_type = exposures.interaction_type
    and clicks.main_category is not distinct from exposures.main_category
