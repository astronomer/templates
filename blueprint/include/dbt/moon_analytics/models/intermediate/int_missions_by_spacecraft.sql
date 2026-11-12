SELECT
    spacecraft_type,
    COUNT(*) AS total_missions,
    COUNT(*) FILTER (WHERE outcome = 'Success') AS successful_missions,
    COUNT(*) FILTER (WHERE outcome != 'Success') AS failed_missions
FROM {{ ref('stg_moon_missions') }}
GROUP BY spacecraft_type
