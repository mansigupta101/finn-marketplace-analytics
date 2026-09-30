-- SIMULATED. One row per seller contact, with whether the listing is boosted.

select
    contacts.user_id,
    contacts.interaction_step,
    contacts.item_id,
    boosted.item_id is not null as is_boosted_listing

from {{ source('simulation', 'simulated_contacts') }} as contacts
left join {{ source('simulation', 'boosted_listings') }} as boosted
    on boosted.item_id = contacts.item_id
