-- A customer may have historical SCD rows, but no more than one active row.
-- Returning zero rows means the assertion passes.
select
    customer_id,
    count(*) as active_version_count
from {{ ref('stg_customers') }}
where is_active = true
group by customer_id
having count(*) > 1
