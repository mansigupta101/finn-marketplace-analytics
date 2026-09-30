{{ config(materialized='table') }}

-- One row per listing shown in a slate. The "no click" item (id 1) is not a listing and is removed.

with source as (

    select * from {{ source('finn_slates', 'exposures') }}

)

select
    user_id::varchar || '-' || interaction_step::varchar as slate_id,
    user_id,
    interaction_step,
    item_id,
    -- Item 2 means a listing was shown but its identity is missing ("<UNK>").
    item_id = 2 as is_unknown_item,
    slot_index,
    -- Position as the buyer saw it: 1 for the first listing, 2 for the second, and so on.
    row_number() over (
        partition by user_id, interaction_step
        order by slot_index
    ) as display_position

from source
where item_id <> 1
