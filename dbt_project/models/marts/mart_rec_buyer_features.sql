-- One row per buyer. Features from the first 5 interactions only (no leakage).

with first5 as (
    select * from {{ ref('int_rec_split') }} where period = 'first5'
),

clicks as (
    select f.user_id, i.main_category, i.county
    from first5 as f
    inner join {{ ref('stg_items') }} as i on i.item_id = f.clicked_item_id
    where f.has_click and not i.is_special_item
),

top_category as (
    select user_id, main_category,
        row_number() over (partition by user_id order by count(*) desc, main_category) as rn
    from clicks where main_category is not null
    group by user_id, main_category
),

top_county as (
    select user_id, county,
        row_number() over (partition by user_id order by count(*) desc, county) as rn
    from clicks where county is not null
    group by user_id, county
),

base as (
    select
        user_id,
        split_group,
        count(*) as n_first5_interactions,
        count_if(has_click) as n_first5_clicks,
        avg(iff(interaction_type = 'search', 1, 0)) as search_share
    from first5
    group by user_id, split_group
)

select
    base.*,
    top_category.main_category as top_category,
    top_county.county as top_county
from base
left join top_category on top_category.user_id = base.user_id and top_category.rn = 1
left join top_county on top_county.user_id = base.user_id and top_county.rn = 1