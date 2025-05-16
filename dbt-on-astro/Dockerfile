FROM astrocrpublic.azurecr.io/runtime:3.0-2

# Writing to DuckDB from multiple processes is not supported
# https://duckdb.org/docs/stable/connect/concurrency.html
ENV AIRFLOW__CORE__MAX_ACTIVE_RUNS_PER_DAG=1

# install dbt into a virtual environment
RUN python -m venv dbt_venv && source dbt_venv/bin/activate && \
    pip install --no-cache-dir dbt-duckdb==1.8.2 && deactivate