-- One row per slate, with the buyer's split group and whether the slate is in the
-- first 5 interactions or later.

with slates as (

    select
        *,
        row_number() over (partition by user_id order by interaction_step) as interaction_seq,
        count(*) over (partition by user_id) as n_interactions
    from {{ ref('int_slates') }}

),

buyers as (

    select
        user_id,
        max(n_interactions) as n_interactions,
        mod(md5_number_lower64('rec_split_v1:' || user_id::varchar), 100) as bucket
    from slates
    group by user_id

),

assigned as (

    select
        user_id,
        case
            when n_interactions <= 5 then 'train'
            when bucket < 70 then 'train'
            when bucket < 80 then 'validation'
            else 'test'
        end as split_group
    from buyers

)

select
    slates.slate_id,
    slates.user_id,
    slates.interaction_step,
    slates.interaction_seq,
    slates.interaction_type,
    slates.has_click,
    slates.clicked_item_id,
    slates.has_removed_item,
    assigned.split_group,
    case when slates.interaction_seq <= 5 then 'first5' else 'later' end as period
from slates
inner join assigned
    on assigned.user_id = slates.user_id