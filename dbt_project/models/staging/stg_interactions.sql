-- One row per slate: one search result page or recommendation block shown to a buyer.

with source as (

    select * from {{ source('finn_slates', 'interactions') }}

)

select
    user_id::varchar || '-' || interaction_step::varchar as slate_id,
    user_id,
    interaction_step,
    interaction_type_code,
    case interaction_type_code
        when 1 then 'search'
        when 2 then 'recommendation'
        else 'unknown'
    end as interaction_type,
    clicked_item_id <> 1 as has_click,
    -- Item 1 is the "no click" item, so it is not a clicked listing.
    case when clicked_item_id <> 1 then clicked_item_id end as clicked_item_id,
    click_slot_index,
    -- Auxiliary field from FINN. The item list in stg_exposures is the source of truth.
    slate_length as recorded_slate_length

from source
