"""Data explorer blueprint -- inspect the schema and sample rows of a CSV."""

from blueprint import BaseModel, Blueprint, Field
from include.operators.explorer_operators import DataExplorerOperator


class ExploreRawDataConfig(BaseModel):
    """Explore raw data configuration."""

    source_csv: str = Field(
        default="include/moon_missions.csv",
        description="Path to the CSV file relative to the project root",
    )
    num_rows: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of sample rows to display in the logs",
    )
    print_schema: bool = Field(
        default=True,
        description="Print the column names and types before the sample rows",
    )


class ExploreRawData(Blueprint[ExploreRawDataConfig]):
    """Print the schema and a sample of rows from a CSV to the Airflow logs."""

    def render(self, config: ExploreRawDataConfig) -> DataExplorerOperator:
        return DataExplorerOperator(
            task_id=self.step_id,
            source_csv=config.source_csv,
            num_rows=config.num_rows,
            print_schema=config.print_schema,
        )
