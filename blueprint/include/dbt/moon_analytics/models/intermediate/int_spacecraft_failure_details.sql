SELECT
    failures.spacecraft_type,
    failures.spacecraft,
    failures.mission_name,
    failures.launch_date,
    failures.country,
    failures.description,
    missions.total_missions
FROM {{ ref('stg_moon_missions') }} AS failures
INNER JOIN {{ ref('int_missions_by_spacecraft') }} AS missions
    ON failures.spacecraft_type = missions.spacecraft_type
WHERE failures.outcome = 'Spacecraft failure'
