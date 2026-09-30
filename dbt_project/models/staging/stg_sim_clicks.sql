-- SIMULATED. One row per recommendation slate in the experiment, with the click in the buyer's own group.

select
    user_id::varchar || '-' || interaction_step::varchar as slate_id,
    user_id,
    interaction_step,
    variant,
    clicked_item_id,
    clicked_position,
    clicked_item_id is not null as has_click

from {{ source('simulation', 'simulated_clicks') }}
