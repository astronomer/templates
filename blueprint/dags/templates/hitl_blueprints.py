"""Human-in-the-loop blueprints.

HitlSelect presents the user with options derived from a CSV column and
stores their selection in an Airflow Variable. QueryBySelection filters the
CSV by that stored selection, automatically using the same column.
"""

import os

import duckdb
from airflow.providers.standard.operators.hitl import HITLOperator
from airflow.sdk import TaskGroup

from blueprint import BaseModel, Blueprint, Field
from include.operators.hitl_operators import (
    QueryBySelectionOperator,
    StoreSelectionOperator,
)


def _read_unique_values(source_csv: str, column: str) -> list[str]:
    """Read unique values for a column from the CSV at parse time."""
    airflow_home = os.environ.get("AIRFLOW_HOME", "/usr/local/airflow")
    csv_path = os.path.join(airflow_home, source_csv)
    conn = duckdb.connect()
    rows = conn.execute(
        f"SELECT DISTINCT {column} FROM read_csv_auto('{csv_path}') ORDER BY {column}"
    ).fetchall()
    conn.close()
    return [str(row[0]) for row in rows]


class AddHumanInTheLoopStepConfig(BaseModel):
    """Add Human in the loop step configuration."""

    source_csv: str = Field(
        default="include/moon_missions.csv",
        description="Path to the CSV file relative to the project root",
    )
    column: str = Field(
        default="spacecraft",
        description="CSV column whose unique values become the selectable options",
    )
    subject: str = Field(
        default="Choose an option",
        description="Title shown to the user in the HITL prompt",
    )
    body: str = Field(
        default="Select one or more options from the list below",
        description="Description shown to the user in the HITL prompt (supports markdown)",
    )
    multiple: bool = Field(
        default=True,
        description="Allow selecting multiple options",
    )
    variable_name: str = Field(
        default="hitl_selection",
        description="Airflow Variable name to store the selection in",
    )


class AddHumanInTheLoopStep(Blueprint[AddHumanInTheLoopStepConfig]):
    """Present the user with selectable options from a CSV column and store their choice.

    Reads unique values from the specified column in the CSV file and presents
    them as selectable options in the Airflow UI. The user's selection is stored
    in an Airflow Variable alongside the column name, so downstream steps can
    automatically filter by the same column.
    """

    def render(self, config: AddHumanInTheLoopStepConfig) -> TaskGroup:
        options = _read_unique_values(config.source_csv, config.column)

        with TaskGroup(group_id=self.step_id) as group:
            hitl = HITLOperator(
                task_id="select",
                subject=config.subject,
                body=config.body,
                options=options,
                multiple=config.multiple,
            )
            store = StoreSelectionOperator(
                task_id="store_selection",
                variable_name=config.variable_name,
                hitl_task_id=f"{self.step_id}.select",
                column=config.column,
            )
            hitl >> store
        return group


class QueryBasedOnHumanSelectionConfig(BaseModel):
    """Query based on Human selection configuration."""

    source_csv: str = Field(
        default="include/moon_missions.csv",
        description="Path to the CSV file relative to the project root",
    )
    selection_variable: str = Field(
        default="hitl_selection",
        description="Airflow Variable name containing the selection (column is auto-detected from the stored payload)",
    )


class QueryBasedOnHumanSelection(Blueprint[QueryBasedOnHumanSelectionConfig]):
    """Filter a CSV by a human selection stored in an Airflow Variable.

    The column to filter on is automatically read from the Variable payload
    set by the upstream HITL step -- no need to specify it manually.
    """

    def render(self, config: QueryBasedOnHumanSelectionConfig) -> QueryBySelectionOperator:
        return QueryBySelectionOperator(
            task_id=self.step_id,
            source_csv=config.source_csv,
            selection_variable=config.selection_variable,
        )
