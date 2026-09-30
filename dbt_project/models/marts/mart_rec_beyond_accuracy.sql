-- One row per model and split group: how the recommendations are spread over the catalogue.
--   buyers_scored          buyers with a list
--   fallback_share         share of buyers who got the popularity list instead of a personal one
--   catalogue_items        listings the models can recommend (at least one first-5 click)
--   distinct_items         different catalogue listings that were recommended at least once
--   catalogue_coverage     distinct_items / catalogue_items
--   top1pct_popular_share  share of all recommendations that are one of the 1% most-clicked
--                          listings (the popularity-bias measure; higher = more popularity-driven)

with scores as (
    select * from {{ source('recommender', 'scores') }}
),

-- Listings the models can recommend: listings with at least one click in a buyer's first 5
-- interactions (the same listings the ALS model is trained on).
catalogue as (
    select item_id, n_clicks_first5
    from {{ ref('mart_rec_item_features') }}
    where n_clicks_first5 > 0
),

catalogue_count as (
    select count(*) as n from catalogue
),

popular_items as (
    select item_id
    from catalogue
    qualify row_number() over (order by n_clicks_first5 desc, item_id)
            <= ceil(0.01 * (select n from catalogue_count))
),

tagged as (
    select
        scores.split_group,
        scores.model,
        scores.user_id,
        scores.item_id,
        scores.is_fallback,
        catalogue.item_id is not null as in_catalogue,
        popular_items.item_id is not null as is_popular
    from scores
    left join catalogue on catalogue.item_id = scores.item_id
    left join popular_items on popular_items.item_id = scores.item_id
)

select
    split_group,
    model,
    count(distinct user_id) as buyers_scored,
    count(distinct iff(is_fallback, user_id, null)) / count(distinct user_id) as fallback_share,
    (select n from catalogue_count) as catalogue_items,
    count(distinct iff(in_catalogue, item_id, null)) as distinct_items,
    distinct_items / catalogue_items as catalogue_coverage,
    avg(iff(is_popular, 1.0, 0.0)) as top1pct_popular_share
from tagged
group by split_group, model
