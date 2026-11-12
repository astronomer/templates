"""Quality blueprints -- SQL checks on CSV via DuckDB, and row-count checks on Variable JSON."""

from airflow.sdk import TaskGroup

from blueprint import BaseModel, Blueprint, Field
from include.operators.quality_operators import (
    DuckDbColumnCheckOperator,
    DuckDbTableCheckOperator,
    VariableJsonQualityCheckOperator,
)


class SqlDataQualityCheckConfig(BaseModel):
    """Configuration for SQL data quality checks on a CSV."""

    source_csv: str = Field(
        default="include/moon_missions.csv",
        description="Path to the CSV file relative to the project root",
    )
    not_null_columns: list[str] = Field(
        default=["mission_name", "launch_date", "country", "outcome"],
        description="Column names to check for non-null values",
    )
    unique_columns: list[str] = Field(
        default=["mission_number"],
        description="Column names to check for uniqueness",
    )
    table_checks: list[str] = Field(
        default=["COUNT(*) >= 100"],
        description="List of SQL expressions that must evaluate to true (e.g. 'COUNT(*) >= 100')",
    )
    min_rows: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optional minimum row count: adds COUNT(*) >= min_rows to the table checks "
            "(useful when you expect a full extract such as a year of orders)"
        ),
    )


class SqlDataQualityCheck(Blueprint[SqlDataQualityCheckConfig]):
    """SQL data quality check: column and table checks on a CSV via DuckDB."""

    def render(self, config: SqlDataQualityCheckConfig) -> TaskGroup:
        checks = list(config.table_checks)
        if config.min_rows is not None:
            checks.append(f"COUNT(*) >= {config.min_rows}")

        with TaskGroup(group_id=self.step_id) as group:
            column_tasks = []

            if config.not_null_columns:
                t = DuckDbColumnCheckOperator(
                    task_id="not_null_check",
                    source_csv=config.source_csv,
                    columns=config.not_null_columns,
                    check="not_null",
                )
                column_tasks.append(t)

            if config.unique_columns:
                t = DuckDbColumnCheckOperator(
                    task_id="unique_check",
                    source_csv=config.source_csv,
                    columns=config.unique_columns,
                    check="unique",
                )
                column_tasks.append(t)

            if checks:
                table_task = DuckDbTableCheckOperator(
                    task_id="table_checks",
                    source_csv=config.source_csv,
                    checks=checks,
                )
                for t in column_tasks:
                    t >> table_task

        return group


class RowCountCheckConfig(BaseModel):
    """Configuration for row-count / key checks on JSON in an Airflow Variable."""

    source_variable: str = Field(
        default="merch_revenue_by_period",
        description="Airflow Variable containing a JSON array of row objects from an upstream ETL step",
    )
    min_rows: int | None = Field(
        default=None,
        ge=1,
        description="Require at least this many rows in the JSON array (e.g. 12 for monthly buckets over a year)",
    )
    not_null_keys: list[str] = Field(
        default_factory=list,
        description="Object keys that must be present and non-null in every row",
    )
    unique_keys: list[str] = Field(
        default_factory=list,
        description="Object keys whose values must be unique across rows (e.g. period_start)",
    )


class RowCountCheck(Blueprint[RowCountCheckConfig]):
    """Row count check: validate ETL JSON in an Airflow Variable (min rows, not-null keys, unique keys)."""

    def render(self, config: RowCountCheckConfig) -> VariableJsonQualityCheckOperator:
        return VariableJsonQualityCheckOperator(
            task_id=self.step_id,
            source_variable=config.source_variable,
            min_rows=config.min_rows,
            not_null_keys=config.not_null_keys,
            unique_keys=config.unique_keys,
        )
