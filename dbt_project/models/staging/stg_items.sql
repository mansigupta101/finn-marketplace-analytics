-- One row per item, with its item group split into main category, subcategory and county.
-- Group names look like "BAP,antiques,Trøndelag" or "MOTOR,,Oslo" (empty subcategory).
-- Groups 0, 1 and 2 are the special values PAD, noClick and <UNK>.

with items as (

    select * from {{ source('finn_slates', 'items') }}

),

item_groups as (

    select
        item_group_code,
        item_group_name,
        split(item_group_name, ',') as name_parts
    from {{ source('finn_slates', 'item_groups') }}

)

select
    items.item_id,
    items.item_group_code,
    item_groups.item_group_name,
    items.item_group_code <= 2 as is_special_item,
    case
        when items.item_group_code > 2
            then trim(get(item_groups.name_parts, 0)::varchar)
    end as main_category,
    case
        when items.item_group_code > 2 and array_size(item_groups.name_parts) >= 3
            then nullif(trim(get(item_groups.name_parts, 1)::varchar), '')
    end as subcategory,
    case
        when items.item_group_code > 2 and array_size(item_groups.name_parts) >= 2
            then nullif(trim(get(item_groups.name_parts, array_size(item_groups.name_parts) - 1)::varchar), '')
    end as county

from items
left join item_groups
    on items.item_group_code = item_groups.item_group_code
