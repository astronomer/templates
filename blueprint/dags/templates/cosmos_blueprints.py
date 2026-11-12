"""Cosmos dbt blueprint -- run dbt models via Astronomer Cosmos DbtTaskGroup.

Uses DuckDB as the warehouse so the project is fully self-contained
with no external database required.
"""

import json
import os
import time

from airflow.sdk import BaseOperator, TaskGroup, Variable
from cosmos import DbtTaskGroup, ExecutionConfig, ExecutionMode, ProfileConfig, ProjectConfig, RenderConfig

from blueprint import BaseModel, Blueprint, Field


def _dbt_project_path(project_name: str) -> str:
    """Absolute path to a dbt project under AIRFLOW_HOME/include/dbt/<project_name>."""
    return os.path.join(
        os.environ.get("AIRFLOW_HOME", "/usr/local/airflow"),
        "include",
        "dbt",
        project_name,
    )

_STORE_RESULT_RETRIES = 40
_STORE_RESULT_DELAY_SEC = 0.25


def _is_duckdb_lock_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "lock" in msg or "conflicting" in msg


class _StoreDbtResultOperator(BaseOperator):
    """Query a dbt result table from DuckDB and store as JSON in an Airflow Variable."""

    def __init__(
        self,
        result_table: str,
        target_variable: str,
        duckdb_path: str,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.result_table = result_table
        self.target_variable = target_variable
        self.duckdb_path = duckdb_path

    def execute(self, context):
        import duckdb

        for attempt in range(_STORE_RESULT_RETRIES):
            try:
                conn = duckdb.connect(self.duckdb_path, read_only=True)
                try:
                    result = conn.execute(f"SELECT * FROM {self.result_table}")
                    columns = [desc[0] for desc in result.description]
                    rows = result.fetchall()
                finally:
                    conn.close()

                data = [dict(zip(columns, row)) for row in rows]
                json_result = json.dumps(data, default=str)
                Variable.set(self.target_variable, json_result)

                self.log.info(
                    "Stored %d rows from '%s' in Variable '%s'",
                    len(data), self.result_table, self.target_variable,
                )
                return {"variable": self.target_variable, "rows": len(data)}
            except Exception as e:
                if attempt < _STORE_RESULT_RETRIES - 1 and _is_duckdb_lock_error(e):
                    delay = min(
                        _STORE_RESULT_DELAY_SEC * (2**min(attempt, 5)),
                        3.0,
                    )
                    self.log.warning(
                        "DuckDB lock when opening %s (attempt %d/%d); retrying in %.2fs: %s",
                        self.duckdb_path,
                        attempt + 1,
                        _STORE_RESULT_RETRIES,
                        delay,
                        e,
                    )
                    time.sleep(delay)
                    continue
                raise


class _PrintVariableOperator(BaseOperator):
    """Read an Airflow Variable containing JSON results and pretty-print to logs."""

    def __init__(self, source_variable: str, **kwargs):
        super().__init__(**kwargs)
        self.source_variable = source_variable

    def execute(self, context):
        raw = Variable.get(self.source_variable)
        data = json.loads(raw)

        if isinstance(data, list) and data:
            columns = list(data[0].keys())
            col_widths = [
                max(len(str(c)), *(len(str(row.get(c, ""))) for row in data))
                for c in columns
            ]
            header = "  ".join(c.ljust(w) for c, w in zip(columns, col_widths))
            sep = "  ".join("-" * w for w in col_widths)
            lines = [
                f"\n=== Query results: {self.source_variable} ({len(data)} rows) ===",
                header, sep,
            ]
            for row in data:
                lines.append(
                    "  ".join(
                        str(row.get(c, "")).ljust(w)
                        for c, w in zip(columns, col_widths)
                    )
                )
            self.log.info("\n".join(lines))
        else:
            self.log.info("Result: %s", raw)

        return {"variable": self.source_variable, "rows": len(data) if isinstance(data, list) else 1}


# ---------------------------------------------------------------------------
# Blueprint 1: run dbt models and store the final result in a Variable
# ---------------------------------------------------------------------------

class RunDbtProjectWithCosmosConfig(BaseModel):
    """Configuration for running dbt models via Cosmos."""

    dbt_project_name: str = Field(
        default="moon_analytics",
        description=(
            "Name of the dbt project folder under include/dbt/ (contains dbt_project.yml "
            "and profiles.yml), e.g. moon_analytics."
        ),
    )
    select: str | None = Field(
        default=None,
        description="dbt node selector (e.g. 'tag:daily', 'staging.*', 'fct_spacecraft_outcomes+'). Leave empty to run all models.",
    )
    exclude: str | None = Field(
        default=None,
        description="dbt node exclusion selector (e.g. 'tag:slow')",
    )
    full_refresh: bool = Field(
        default=False,
        description="Run with --full-refresh (rebuilds all models from scratch)",
    )
    result_table: str = Field(
        default="fct_spacecraft_outcomes",
        description="DuckDB table (dbt model) to query for the final result",
    )
    target_variable: str = Field(
        default="dbt_results",
        description="Airflow Variable name to store the dbt results in",
    )


class RunDbtProjectWithCosmos(Blueprint[RunDbtProjectWithCosmosConfig]):
    """Run the moon_analytics dbt project via Astronomer Cosmos.

    Uses DuckDB as the warehouse and ExecutionMode.LOCAL so
    everything runs inside the Airflow worker with no external dependencies.
    The dbt model graph is fully linear (stg -> int_missions -> int_failures -> fct)
    to avoid DuckDB file-locking contention.

    After the dbt run completes, the final result table is queried and stored
    as JSON in an Airflow Variable.
    """

    def render(self, config: RunDbtProjectWithCosmosConfig) -> TaskGroup:
        project_path = _dbt_project_path(config.dbt_project_name)
        # Profile key and warehouse path follow the bundled profiles.yml convention
        # (profile name = project folder name; DuckDB at /tmp/<project>.duckdb).
        profile_name = config.dbt_project_name
        duckdb_path = f"/tmp/{config.dbt_project_name}.duckdb"

        with TaskGroup(group_id=self.step_id) as group:
            dbt = DbtTaskGroup(
                group_id="dbt",
                project_config=ProjectConfig(dbt_project_path=project_path),
                profile_config=ProfileConfig(
                    profile_name=profile_name,
                    target_name="dev",
                    profiles_yml_filepath=os.path.join(project_path, "profiles.yml"),
                ),
                execution_config=ExecutionConfig(execution_mode=ExecutionMode.LOCAL),
                render_config=RenderConfig(
                    select=[config.select] if config.select else [],
                    exclude=[config.exclude] if config.exclude else [],
                ),
                operator_args={"full_refresh": config.full_refresh},
            )

            store = _StoreDbtResultOperator(
                task_id="store_results",
                result_table=config.result_table,
                target_variable=config.target_variable,
                duckdb_path=duckdb_path,
            )

            dbt >> store
        return group


# ---------------------------------------------------------------------------
# Blueprint 2: print tabular JSON from a Variable
# ---------------------------------------------------------------------------

class PrintConfig(BaseModel):
    """Print tabular JSON stored in an Airflow Variable (dbt or any ETL query result)."""

    source_variable: str = Field(
        description=(
            "Airflow Variable containing a JSON array of objects (e.g. dbt final model rows "
            "or Custom Moon Data ETL output). Pretty-printed as an aligned table in the logs."
        ),
    )


class Print(Blueprint[PrintConfig]):
    """Pretty-print JSON row results from an Airflow Variable (dbt, DuckDB ETL, or similar)."""

    def render(self, config: PrintConfig) -> _PrintVariableOperator:
        return _PrintVariableOperator(
            task_id=self.step_id,
            source_variable=config.source_variable,
        )
