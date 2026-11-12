"""Operator for the data explorer blueprint.

Pretty-prints the schema and a sample of rows from a CSV file.
"""

import os

import duckdb
from airflow.sdk.bases.operator import BaseOperator


class DataExplorerOperator(BaseOperator):
    """Read a CSV and log its schema and top N rows.

    :param source_csv: Path to the CSV relative to AIRFLOW_HOME
    :param num_rows: Number of sample rows to display
    """

    def __init__(self, source_csv: str, num_rows: int = 5, print_schema: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_csv = source_csv
        self.num_rows = num_rows
        self.print_schema = print_schema

    def execute(self, context):
        airflow_home = os.environ.get("AIRFLOW_HOME", "/usr/local/airflow")
        csv_path = os.path.join(airflow_home, self.source_csv)

        conn = duckdb.connect()
        relation = conn.sql(f"SELECT * FROM read_csv_auto('{csv_path}')")

        columns = relation.columns
        types = relation.types
        total_rows = conn.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{csv_path}')"
        ).fetchone()[0]

        if self.print_schema:
            col_width = max(len(c) for c in columns)
            header = f"\n{'Column'.ljust(col_width)}  Type"
            separator = "-" * (col_width + 30)
            schema_lines = [
                f"\n=== Schema for {self.source_csv} ({total_rows} rows) ===",
                header,
                separator,
            ]
            for col, dtype in zip(columns, types):
                schema_lines.append(f"{col.ljust(col_width)}  {dtype}")

            self.log.info("\n".join(schema_lines))

        # Sample rows
        sample = conn.execute(
            f"SELECT * FROM read_csv_auto('{csv_path}') LIMIT {self.num_rows}"
        ).fetchall()

        col_widths = [max(len(str(col)), *(len(str(row[i])) for row in sample))
                      for i, col in enumerate(columns)]

        header_row = "  ".join(
            str(col).ljust(w) for col, w in zip(columns, col_widths)
        )
        sep_row = "  ".join("-" * w for w in col_widths)

        sample_lines = [
            f"\n=== Top {self.num_rows} rows ===",
            header_row,
            sep_row,
        ]
        for row in sample:
            sample_lines.append(
                "  ".join(str(val).ljust(w) for val, w in zip(row, col_widths))
            )

        self.log.info("\n".join(sample_lines))
        conn.close()

        return {"rows": total_rows, "columns": len(columns)}
