SELECT
    mission_number,
    mission_name,
    CAST(launch_date AS DATE) AS launch_date,
    country,
    operator,
    carrier_rocket,
    spacecraft,
    SPLIT_PART(spacecraft, ' ', 1) AS spacecraft_type,
    mission_type,
    outcome,
    CAST(crewed AS BOOLEAN) AS is_crewed,
    description
FROM read_csv_auto('/usr/local/airflow/include/moon_missions.csv')
