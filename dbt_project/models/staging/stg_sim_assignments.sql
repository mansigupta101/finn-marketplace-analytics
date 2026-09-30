-- SIMULATED. One row per eligible buyer, with the experiment group.

select
    user_id,
    experiment_id,
    variant

from {{ source('simulation', 'experiment_assignments') }}
