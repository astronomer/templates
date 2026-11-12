"""Operators for the human-in-the-loop blueprint.

Stores the user's HITL selection (and the column it came from) in an
Airflow Variable, then queries the CSV filtered by that selection.
"""

import json
import os

import duckdb
from airflow.sdk import Variable
from airflow.sdk.bases.operator import BaseOperator


class StoreSelectionOperator(BaseOperator):
    """Read the HITL operator's chosen options and store them in a Variable.

    Stores a JSON object with both the selected values and the column
    they came from, so downstream tasks can auto-derive the filter column.

    :param variable_name: Airflow Variable name to write the selection to
    :param hitl_task_id: Task ID of the upstream HITL operator to pull XCom from
    :param column: The CSV column the options were drawn from
    """

    def __init__(self, variable_name: str, hitl_task_id: str, column: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.variable_name = variable_name
        self.hitl_task_id = hitl_task_id
        self.column = column

    def execute(self, context):
        ti = context["ti"]
        result = ti.xcom_pull(task_ids=self.hitl_task_id)
        chosen = result["chosen_options"]
        payload = {"column": self.column, "values": chosen}
        Variable.set(self.variable_name, json.dumps(payload))
        self.log.info(
            "Stored selection for column '%s': %s in Variable '%s'",
            self.column, chosen, self.variable_name,
        )
        return {"variable": self.variable_name, "chosen": chosen}


class QueryBySelectionOperator(BaseOperator):
    """Query the CSV for rows matching a selection stored in a Variable.

    The filter column is automatically read from the Variable payload
    (set by StoreSelectionOperator). An explicit ``filter_column`` can
    still be provided to override.

    :param source_csv: Path to the CSV relative to AIRFLOW_HOME
    :param selection_variable: Variable name containing the selection payload
    :param filter_column: Optional override for the column to filter on
    """

    def __init__(
        self,
        source_csv: str,
        selection_variable: str,
        filter_column: str | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.source_csv = source_csv
        self.selection_variable = selection_variable
        self.filter_column = filter_column

    def execute(self, context):
        raw = Variable.get(self.selection_variable)
        payload = json.loads(raw)

        if isinstance(payload, dict) and "column" in payload:
            column = self.filter_column or payload["column"]
            selected = payload["values"]
        else:
            column = self.filter_column
            selected = payload
            if not column:
                raise ValueError(
                    f"Variable '{self.selection_variable}' does not contain column metadata "
                    "and no filter_column was provided."
                )

        self.log.info("Filtering %s by %s IN %s", self.source_csv, column, selected)

        airflow_home = os.environ.get("AIRFLOW_HOME", "/usr/local/airflow")
        csv_path = os.path.join(airflow_home, self.source_csv)

        placeholders = ", ".join(f"'{v}'" for v in selected)
        sql = (
            f"SELECT * FROM read_csv_auto('{csv_path}') "
            f"WHERE {column} IN ({placeholders}) "
            f"ORDER BY launch_date"
        )

        conn = duckdb.connect()
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        conn.close()

        col_widths = [
            max(len(str(c)), *(len(str(r[i])) for r in rows) if rows else 0)
            for i, c in enumerate(columns)
        ]
        col_widths = [min(w, 40) for w in col_widths]

        header = "  ".join(c.ljust(w) for c, w in zip(columns, col_widths))
        sep = "  ".join("-" * w for w in col_widths)

        lines = [
            "",
            f"=== Missions matching {column} IN {selected} ({len(rows)} results) ===",
            header,
            sep,
        ]
        for row in rows:
            lines.append(
                "  ".join(str(v)[:w].ljust(w) for v, w in zip(row, col_widths))
            )
        lines.append(f"=== {len(rows)} mission(s) found ===")

        self.log.info("\n".join(lines))
        return {"count": len(rows), "selection": selected}
