-- Search results compared with recommendations. One row per interaction type.

select
    interaction_type,
    count(*) as slates,
    count(distinct user_id) as buyers,
    count_if(has_click) as slates_with_click,
    div0(count_if(has_click), count(*)) as slate_click_rate,
    avg(n_listings_shown) as avg_listings_shown,
    div0(sum(n_unknown_listings), sum(n_listings_shown)) as unknown_listing_share,
    -- Position of the click, only in slates where positions are reliable.
    avg(case when not has_removed_item then clicked_display_position end) as avg_clicked_position,
    div0(count_if(has_removed_item), count(*)) as removed_item_share

from {{ ref('int_slates') }}
group by 1
