FROM astrocrpublic.azurecr.io/runtime:3.0-6

# install dbt into a virtual environment
RUN python -m venv dbt_venv && source dbt_venv/bin/activate && \
    pip install --no-cache-dir dbt-duckdb==1.8.2 && deactivate