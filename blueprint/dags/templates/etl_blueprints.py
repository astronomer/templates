"""CSV ETL blueprint -- extract from CSV, transform with SQL, load to Variable.

Users write SQL in the YAML to define their transformation. The CSV is
registered as a DuckDB table named after the file (e.g. ``moon_missions``),
so the SQL can reference it directly.
"""

from airflow.sdk import TaskGroup

from blueprint import BaseModel, Blueprint, Field
from include.operators.etl_operators import (
    CsvExtractOperator,
    DuckDbTransformOperator,
    VariableLoadOperator,
)


class CustomMoonDataEtlConfig(BaseModel):
    """Custom Moon Data ETL configuration."""

    source_csv: str = Field(
        default="include/moon_missions.csv",
        description="Path to the source CSV file relative to the project root (e.g. 'include/moon_missions.csv')",
    )
    sql: str = Field(
        default="SELECT * FROM moon_missions WHERE launch_date >= '2023-12-19'",
        title="Transformation SQL Query",
        description=(
            "SQL query to run against the CSV data via DuckDB. "
            "The CSV is available as a table named after the file "
            "(e.g. 'moon_missions' for moon_missions.csv)."
        ),
    )
    target_variable: str = Field(
        default="moon_etl_result",
        description="Airflow Variable name to store the query result in",
    )


class CustomMoonDataEtl(Blueprint[CustomMoonDataEtlConfig]):
    """Extract data from a CSV, transform it with SQL, and load into an Airflow Variable."""

    def render(self, config: CustomMoonDataEtlConfig) -> TaskGroup:
        with TaskGroup(group_id=self.step_id) as group:
            extract = CsvExtractOperator(
                task_id="extract",
                source_csv=config.source_csv,
            )
            transform = DuckDbTransformOperator(
                task_id="transform",
                source_csv=config.source_csv,
                sql=config.sql,
            )
            load = VariableLoadOperator(
                task_id="load",
                target_variable=config.target_variable,
            )
            extract >> transform >> load
        return group
