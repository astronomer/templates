"""Date-related moon mission blueprints.

EnterDate stores an arbitrary date (e.g. a birthday or historical anchor) in an
Airflow Variable. SelectMissionsBasedOnDate reads that date and selects moon
missions at the chosen grain (closest, year, or decade).
"""

from datetime import date, datetime

from pydantic import field_validator

from blueprint import BaseModel, Blueprint, Field
from include.operators.date_operators import (
    SelectMissionsByDateOperator,
    StoreDateOperator,
)


class EnterDateConfig(BaseModel):
    """Enter date configuration."""

    date: str = Field(
        default="1990-12-19",
        description="A date in YYYY-MM-DD format (e.g. a birthday or reference date)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    variable_name: str = Field(
        default="my_date",
        description="Airflow Variable name to store the date in",
    )

    @field_validator("date", mode="before")
    @classmethod
    def _coerce_date_to_iso_string(cls, v):
        """YAML and some loaders pass native date objects; Pydantic expects str."""
        if isinstance(v, datetime):
            return v.date().isoformat()
        if isinstance(v, date):
            return v.isoformat()
        return v


class EnterDate(Blueprint[EnterDateConfig]):
    """Store a date in an Airflow Variable for use by downstream steps."""

    def render(self, config: EnterDateConfig) -> StoreDateOperator:
        return StoreDateOperator(
            task_id=self.step_id,
            date=config.date,
            variable_name=config.variable_name,
        )


class SelectMissionsBasedOnDateConfig(BaseModel):
    """Select missions based on date configuration."""

    source_csv: str = Field(
        default="include/moon_missions.csv",
        description="Path to the moon missions CSV relative to the project root",
    )
    date_variable: str = Field(
        default="my_date",
        description="Airflow Variable name containing the target date",
    )
    grain: str = Field(
        default="closest",
        description="How to match missions: 'closest' (single nearest), 'year' (same calendar year), or 'decade' (same decade)",
        pattern="^(closest|year|decade)$",
    )


class SelectMissionsBasedOnDate(Blueprint[SelectMissionsBasedOnDateConfig]):
    """Select moon missions matching a stored date at a configurable grain."""

    def render(self, config: SelectMissionsBasedOnDateConfig) -> SelectMissionsByDateOperator:
        return SelectMissionsByDateOperator(
            task_id=self.step_id,
            source_csv=config.source_csv,
            date_variable=config.date_variable,
            grain=config.grain,
        )
