SELECT
    missions.spacecraft_type,
    missions.total_missions,
    missions.successful_missions,
    missions.failed_missions,
    COUNT(failures.mission_name) AS spacecraft_failures,
    ROUND(
        100.0 * missions.successful_missions / missions.total_missions, 1
    ) AS mission_success_rate_pct,
    ROUND(
        100.0 * (missions.total_missions - COUNT(failures.mission_name)) / missions.total_missions, 1
    ) AS spacecraft_success_rate_pct
FROM {{ ref('int_missions_by_spacecraft') }} AS missions
LEFT JOIN {{ ref('int_spacecraft_failure_details') }} AS failures
    ON missions.spacecraft_type = failures.spacecraft_type
GROUP BY
    missions.spacecraft_type,
    missions.total_missions,
    missions.successful_missions,
    missions.failed_missions
ORDER BY missions.total_missions DESC
