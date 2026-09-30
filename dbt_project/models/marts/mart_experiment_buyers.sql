-- SIMULATED. One row per eligible buyer in the recommended-listing boost experiment, with the
-- per-buyer totals that every metric in docs/ab_test_protocol.md is built from:
--
--   boosted_listing_ctr              = boosted_clicks / boosted_exposures
--   recommendation_slate_click_rate  = slates_with_click / slates
--   other_listing_ctr                = other_clicks / other_exposures
--   boosted_listing_contact_rate     = boosted_contacts / boosted_exposures
--
-- Ratios are computed in the analysis, not here, so that the variance can be taken over buyers.
-- The listings shown are real (stg_exposures); the clicks and contacts are simulated.

with slates as (

    select * from {{ ref('stg_sim_clicks') }}

),

boosted as (

    select item_id from {{ source('simulation', 'boosted_listings') }}

),

exposures as (

    select
        exposures.user_id,
        count_if(boosted.item_id is not null) as boosted_exposures,
        count_if(not exposures.is_unknown_item and boosted.item_id is null) as other_exposures
    from {{ ref('stg_exposures') }} as exposures
    inner join slates
        on slates.user_id = exposures.user_id
        and slates.interaction_step = exposures.interaction_step
    left join boosted
        on boosted.item_id = exposures.item_id
    group by 1

),

clicks as (

    select
        slates.user_id,
        count(*) as slates,
        count_if(slates.has_click) as slates_with_click,
        count_if(boosted.item_id is not null) as boosted_clicks,
        count_if(slates.has_click and boosted.item_id is null) as other_clicks
    from slates
    left join boosted
        on boosted.item_id = slates.clicked_item_id
    group by 1

),

contacts as (

    select
        user_id,
        count_if(is_boosted_listing) as boosted_contacts
    from {{ ref('stg_sim_contacts') }}
    group by 1

)

select
    assignments.user_id,
    assignments.variant,
    coalesce(clicks.slates, 0) as slates,
    coalesce(clicks.slates_with_click, 0) as slates_with_click,
    coalesce(exposures.boosted_exposures, 0) as boosted_exposures,
    coalesce(clicks.boosted_clicks, 0) as boosted_clicks,
    coalesce(exposures.other_exposures, 0) as other_exposures,
    coalesce(clicks.other_clicks, 0) as other_clicks,
    coalesce(contacts.boosted_contacts, 0) as boosted_contacts

from {{ ref('stg_sim_assignments') }} as assignments
left join clicks
    on clicks.user_id = assignments.user_id
left join exposures
    on exposures.user_id = assignments.user_id
left join contacts
    on contacts.user_id = assignments.user_id
