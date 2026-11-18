-- Top Customers by Activity
-- Template: top_customers
-- Parameters: start_date, end_date, limit
-- Description: Most active customers in a date range with transaction metrics

SELECT
    customer_id,
    customer_name,
    COUNT(*) AS total_transactions,
    COUNT(DISTINCT DATE(transaction_date)) AS active_days,
    ROUND(SUM(amount), 2) AS total_amount,
    ROUND(AVG(amount), 2) AS avg_transaction,
    MIN(transaction_date) AS first_transaction,
    MAX(transaction_date) AS last_transaction
FROM "analytics"."transactions"
WHERE
    transaction_date >= {{start_date}}
    AND transaction_date <= {{end_date}}
    AND status = 'completed'
GROUP BY customer_id, customer_name
ORDER BY total_amount DESC
LIMIT {{limit}}
