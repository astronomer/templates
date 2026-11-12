"""Operators for the CSV ETL blueprint.

Extracts data from a CSV, transforms it with DuckDB SQL, and loads
the result into an Airflow Variable.
"""

import json
import os
from pathlib import Path

import duckdb
from airflow.sdk import Variable
from airflow.sdk.bases.operator import BaseOperator


def _resolve_csv_path(source_csv: str) -> str:
    airflow_home = os.environ.get("AIRFLOW_HOME", "/usr/local/airflow")
    return os.path.join(airflow_home, source_csv)


def _table_name_from_path(csv_path: str) -> str:
    return Path(csv_path).stem


class CsvExtractOperator(BaseOperator):
    """Validate that a CSV file exists and log its shape.

    :param source_csv: Path to the CSV relative to AIRFLOW_HOME
    """

    def __init__(self, source_csv: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_csv = source_csv

    def execute(self, context):
        csv_path = _resolve_csv_path(self.source_csv)
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        conn = duckdb.connect()
        row_count = conn.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{csv_path}')"
        ).fetchone()[0]
        col_count = len(conn.execute(
            f"SELECT * FROM read_csv_auto('{csv_path}') LIMIT 0"
        ).description)

        self.log.info("Extracted CSV: %s", csv_path)
        self.log.info("Shape: %d rows x %d columns", row_count, col_count)
        conn.close()
        return {"csv_path": csv_path, "rows": row_count, "columns": col_count}


class DuckDbTransformOperator(BaseOperator):
    """Run a SQL query against a CSV file using DuckDB.

    The CSV is registered as a table whose name matches the filename
    stem (e.g. ``moon_missions.csv`` becomes the table ``moon_missions``).

    :param source_csv: Path to the CSV relative to AIRFLOW_HOME
    :param sql: SQL query to execute against the CSV data
    """

    template_fields = ("sql",)

    def __init__(self, source_csv: str, sql: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_csv = source_csv
        self.sql = sql

    def execute(self, context):
        csv_path = _resolve_csv_path(self.source_csv)
        table_name = _table_name_from_path(csv_path)

        conn = duckdb.connect()
        conn.execute(
            f"CREATE TABLE {table_name} AS "
            f"SELECT * FROM read_csv_auto('{csv_path}')"
        )

        self.log.info("Running SQL against table '%s':\n%s", table_name, self.sql)
        result = conn.execute(self.sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        conn.close()

        data = [dict(zip(columns, row)) for row in rows]
        json_result = json.dumps(data, default=str)
        self.log.info("Query returned %d row(s): %s", len(data), json_result)
        return json_result


class VariableLoadOperator(BaseOperator):
    """Store a JSON string in an Airflow Variable.

    :param target_variable: Name of the Airflow Variable to write to
    """

    def __init__(self, target_variable: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_variable = target_variable

    def execute(self, context):
        ti = context["ti"]
        json_result = ti.xcom_pull(task_ids=f"{ti.task_id.rsplit('.', 1)[0]}.transform")
        if json_result is None:
            raise ValueError("No data received from transform step")

        Variable.set(self.target_variable, json_result)
        self.log.info(
            "Stored result in Airflow Variable '%s' (%d chars)",
            self.target_variable,
            len(json_result),
        )

        data = json.loads(json_result)
        if isinstance(data, list) and data:
            columns = list(data[0].keys())
            col_widths = [
                max(len(str(c)), *(len(str(row.get(c, ""))) for row in data))
                for c in columns
            ]
            header = "  ".join(c.ljust(w) for c, w in zip(columns, col_widths))
            sep = "  ".join("-" * w for w in col_widths)
            lines = [f"\n=== Variable '{self.target_variable}' ({len(data)} rows) ===", header, sep]
            for row in data:
                lines.append("  ".join(str(row.get(c, "")).ljust(w) for c, w in zip(columns, col_widths)))
            self.log.info("\n".join(lines))
        else:
            self.log.info("Result: %s", json_result)

        return {"variable": self.target_variable, "size": len(json_result)}
