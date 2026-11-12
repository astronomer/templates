"""Aggregate blueprint -- extract from CSV, bucket revenue by calendar grain, load to Variable."""

from pathlib import Path

from airflow.sdk import TaskGroup

from blueprint import BaseModel, Blueprint, Field
from include.operators.etl_operators import (
    CsvExtractOperator,
    DuckDbTransformOperator,
    VariableLoadOperator,
)


_GRAIN_SQL = {
    "week": "week",
    "month": "month",
    "quarter": "quarter",
}


class ExtractAndAggregateConfig(BaseModel):
    """Extract and aggregate configuration (revenue by time period)."""

    source_csv: str = Field(
        default="include/moon_merch_sales.csv",
        description="Path to the source CSV relative to the project root",
    )
    grain: str = Field(
        default="month",
        description="Calendar bucket for aggregation: week (ISO), month, or quarter",
        pattern="^(week|month|quarter)$",
    )
    date_column: str = Field(
        default="order_date",
        description="Column containing dates to bucket (cast to DATE in SQL)",
    )
    revenue_column: str = Field(
        default="line_revenue_usd",
        description="Numeric column to sum as revenue",
    )
    target_variable: str = Field(
        default="merch_revenue_by_period",
        description="Airflow Variable name to store the JSON result (one row per period)",
    )


class ExtractAndAggregate(Blueprint[ExtractAndAggregateConfig]):
    """Extract merchandise (or similar) CSV data and aggregate revenue by week, month, or quarter.

    Runs in DuckDB; only the aggregated rows (small JSON) are stored in an Airflow Variable.
    """

    def render(self, config: ExtractAndAggregateConfig) -> TaskGroup:
        trunc = _GRAIN_SQL[config.grain]
        # Table name matches CSV stem (see DuckDbTransformOperator)
        table = Path(config.source_csv.replace("\\", "/")).stem

        sql = (
            f"SELECT "
            f"DATE_TRUNC('{trunc}', CAST({config.date_column} AS DATE)) AS period_start, "
            f"ROUND(SUM({config.revenue_column}), 2) AS revenue_usd, "
            f"COUNT(*)::BIGINT AS line_items "
            f"FROM {table} "
            f"GROUP BY 1 ORDER BY 1"
        )

        with TaskGroup(group_id=self.step_id) as group:
            extract = CsvExtractOperator(
                task_id="extract",
                source_csv=config.source_csv,
            )
            transform = DuckDbTransformOperator(
                task_id="transform",
                source_csv=config.source_csv,
                sql=sql,
            )
            load = VariableLoadOperator(
                task_id="load",
                target_variable=config.target_variable,
            )
            extract >> transform >> load
        return group
