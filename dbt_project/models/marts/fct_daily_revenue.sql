-- NOTE: This model is intentionally simple. If the customer dimension has more
-- than one active row per customer, the join can inflate revenue without a SQL
-- error. Students should add tests/unit tests that expose this failure mode.

with completed_orders as (
    select *
    from {{ ref('stg_orders') }}
    where status = 'completed'
),
active_customers as (
    -- Defensive SCD handling: only one active row may participate in the join.
    -- The singular test still alerts upstream owners when duplicates exist.
    select customer_id
    from {{ ref('stg_customers') }}
    where is_active = true
    qualify row_number() over (
        partition by customer_id
        order by valid_from desc nulls last
    ) = 1
)
select
    o.order_date,
    count(*) as completed_order_rows,
    sum(o.amount_usd) as daily_revenue
from completed_orders o
left join active_customers c
    on o.customer_id = c.customer_id
group by 1
order by 1
