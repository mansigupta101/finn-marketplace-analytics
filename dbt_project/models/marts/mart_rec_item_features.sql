-- One row per known listing shown in the first 5 interactions (this is also the catalogue
-- for coverage). Popularity from the first 5 interactions only.

select
    t.item_id,
    i.main_category,
    i.county,
    count(*) as n_shown_first5,
    sum(t.clicked) as n_clicks_first5
from {{ ref('mart_rec_train') }} as t
inner join {{ ref('stg_items') }} as i on i.item_id = t.item_id
where t.period = 'first5' and not i.is_special_item
group by t.item_id, i.main_category, i.county