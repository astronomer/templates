"""Operators for the data quality check blueprint.

Runs column-level and table-level quality checks against a CSV using DuckDB,
modeled after Airflow's SQLColumnCheckOperator and SQLTableCheckOperator.

Also supports checks against JSON row lists stored in Airflow Variables (ETL output).
"""

import json
import os

import duckdb
from airflow.sdk import Variable
from airflow.sdk.bases.operator import BaseOperator


def _get_conn(source_csv: str):
    airflow_home = os.environ.get("AIRFLOW_HOME", "/usr/local/airflow")
    csv_path = os.path.join(airflow_home, source_csv)
    table_name = os.path.splitext(os.path.basename(csv_path))[0]

    conn = duckdb.connect()
    conn.execute(
        f"CREATE TABLE {table_name} AS "
        f"SELECT * FROM read_csv_auto('{csv_path}')"
    )
    return conn, table_name


class DuckDbColumnCheckOperator(BaseOperator):
    """Run column-level quality checks on a CSV via DuckDB.

    Supported check types: ``not_null``, ``unique``.

    :param source_csv: Path to the CSV relative to AIRFLOW_HOME
    :param columns: List of column names to check
    :param check: Type of check to run
    """

    def __init__(
        self,
        source_csv: str,
        columns: list[str],
        check: str,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.source_csv = source_csv
        self.columns = columns
        self.check = check

    def execute(self, context):
        conn, table_name = _get_conn(self.source_csv)
        failures = []

        for col in self.columns:
            if self.check == "not_null":
                result = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE {col} IS NULL"
                ).fetchone()[0]
                passed = result == 0
                self.log.info(
                    "not_null check on '%s': %d nulls found — %s",
                    col, result, "PASSED" if passed else "FAILED",
                )
            elif self.check == "unique":
                total = conn.execute(
                    f"SELECT COUNT({col}) FROM {table_name}"
                ).fetchone()[0]
                distinct = conn.execute(
                    f"SELECT COUNT(DISTINCT {col}) FROM {table_name}"
                ).fetchone()[0]
                passed = total == distinct
                self.log.info(
                    "unique check on '%s': %d total, %d distinct — %s",
                    col, total, distinct, "PASSED" if passed else "FAILED",
                )
            else:
                raise ValueError(f"Unknown check type: {self.check}")

            if not passed:
                failures.append(col)

        conn.close()

        if failures:
            raise ValueError(
                f"{self.check} check failed for column(s): {', '.join(failures)}"
            )

        return {"check": self.check, "columns": self.columns, "status": "passed"}


class DuckDbTableCheckOperator(BaseOperator):
    """Run table-level SQL checks on a CSV via DuckDB.

    Each check is a SQL expression that must evaluate to a truthy value
    (e.g. ``COUNT(*) >= 100``).

    :param source_csv: Path to the CSV relative to AIRFLOW_HOME
    :param checks: List of SQL expressions to evaluate
    """

    def __init__(
        self,
        source_csv: str,
        checks: list[str],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.source_csv = source_csv
        self.checks = checks

    def execute(self, context):
        conn, table_name = _get_conn(self.source_csv)
        failures = []

        for check_sql in self.checks:
            result = conn.execute(
                f"SELECT ({check_sql}) FROM {table_name}"
            ).fetchone()[0]
            passed = bool(result)
            self.log.info(
                "Table check '%s' = %s — %s",
                check_sql, result, "PASSED" if passed else "FAILED",
            )
            if not passed:
                failures.append(check_sql)

        conn.close()

        if failures:
            raise ValueError(
                f"Table check(s) failed: {'; '.join(failures)}"
            )

        return {"checks": len(self.checks), "status": "passed"}


class VariableJsonQualityCheckOperator(BaseOperator):
    """Run quality checks on a JSON array stored in an Airflow Variable.

    Expects ``Variable`` value to be a JSON list of objects (e.g. DuckDB ETL result).

    :param source_variable: Airflow Variable name
    :param min_rows: If set, require at least this many rows
    :param not_null_keys: Keys that must be present and non-null in every row
    :param unique_keys: Keys whose values must be unique across rows
    """

    def __init__(
        self,
        source_variable: str,
        min_rows: int | None = None,
        not_null_keys: list[str] | None = None,
        unique_keys: list[str] | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.source_variable = source_variable
        self.min_rows = min_rows
        self.not_null_keys = not_null_keys or []
        self.unique_keys = unique_keys or []

    def execute(self, context):
        raw = Variable.get(self.source_variable)
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(
                f"Variable '{self.source_variable}' must contain a JSON array, got {type(data).__name__}"
            )

        n = len(data)
        if self.min_rows is not None and n < self.min_rows:
            raise ValueError(
                f"min_rows check failed: got {n} rows, need >= {self.min_rows}"
            )
        self.log.info(
            "Row count for '%s': %d%s",
            self.source_variable,
            n,
            f" (min_rows >= {self.min_rows})" if self.min_rows is not None else "",
        )

        for i, row in enumerate(data):
            if not isinstance(row, dict):
                raise ValueError(f"Row {i} is not an object: {type(row).__name__}")
            for key in self.not_null_keys:
                if key not in row or row[key] is None:
                    raise ValueError(
                        f"not_null check failed: row {i} missing or null key '{key}'"
                    )

        if self.not_null_keys:
            self.log.info(
                "not_null checks on keys %s: PASSED (%d rows)",
                self.not_null_keys,
                n,
            )

        for key in self.unique_keys:
            values = [row.get(key) for row in data]
            if len(values) != len(set(values)):
                raise ValueError(f"unique check failed: duplicate values for key '{key}'")
            self.log.info("unique check on '%s': PASSED (%d distinct)", key, len(set(values)))

        return {
            "variable": self.source_variable,
            "rows": n,
            "status": "passed",
        }
