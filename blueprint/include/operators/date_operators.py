"""Operators for date-related moon mission blueprints.

Stores a user-provided date in an Airflow Variable and selects moon missions
based on that date at a configurable grain (closest single mission, same year,
or same decade).
"""

import os

import duckdb
from airflow.sdk import Variable
from airflow.sdk.bases.operator import BaseOperator


class StoreDateOperator(BaseOperator):
    """Write a date string to an Airflow Variable.

    :param date: Date string in ISO format (YYYY-MM-DD)
    :param variable_name: Airflow Variable name to store the date in
    """

    def __init__(self, date: str, variable_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.date = date
        self.variable_name = variable_name

    def execute(self, context):
        Variable.set(self.variable_name, self.date)
        self.log.info(
            "Stored date '%s' in Variable '%s'",
            self.date,
            self.variable_name,
        )
        return {"variable": self.variable_name, "value": self.date}


class SelectMissionsByDateOperator(BaseOperator):
    """Select moon missions based on a date stored in an Airflow Variable.

    The ``grain`` parameter controls how missions are matched:
    - ``"closest"``: the single mission with the nearest launch date
    - ``"year"``: all missions launched in the same calendar year
    - ``"decade"``: all missions launched in the same decade

    :param source_csv: Path to the CSV relative to AIRFLOW_HOME
    :param date_variable: Airflow Variable name containing the date
    :param grain: One of "closest", "year", "decade"
    """

    def __init__(
        self,
        source_csv: str,
        date_variable: str,
        grain: str = "closest",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.source_csv = source_csv
        self.date_variable = date_variable
        self.grain = grain

    def execute(self, context):
        target_date = Variable.get(self.date_variable)
        self.log.info("Selecting missions for date %s (grain=%s)", target_date, self.grain)

        airflow_home = os.environ.get("AIRFLOW_HOME", "/usr/local/airflow")
        csv_path = os.path.join(airflow_home, self.source_csv)
        conn = duckdb.connect()

        if self.grain == "closest":
            return self._find_closest(conn, csv_path, target_date)
        elif self.grain == "year":
            return self._find_by_year(conn, csv_path, target_date)
        elif self.grain == "decade":
            return self._find_by_decade(conn, csv_path, target_date)
        else:
            raise ValueError(f"Unknown grain: {self.grain!r}. Use 'closest', 'year', or 'decade'.")

    def _find_closest(self, conn, csv_path: str, target_date: str):
        result = conn.execute(
            f"""
            SELECT *, ABS(launch_date::DATE - DATE '{target_date}') AS days_apart
            FROM read_csv_auto('{csv_path}')
            ORDER BY days_apart ASC
            LIMIT 1
            """
        )
        columns = [d[0] for d in result.description]
        row = result.fetchone()
        conn.close()

        mission = dict(zip(columns, row))
        lines = [
            "",
            "=" * 60,
            f"  Your date: {target_date}",
            f"  Closest moon mission: {mission['mission_name']}",
            f"  Days apart: {mission['days_apart']}",
            "=" * 60,
        ]
        for key, value in mission.items():
            if key != "days_apart":
                lines.append(f"  {key}: {value}")
        lines.append("=" * 60)
        self.log.info("\n".join(lines))

        return {
            "mission_name": mission["mission_name"],
            "launch_date": str(mission["launch_date"]),
            "days_apart": int(mission["days_apart"]),
            "count": 1,
        }

    def _find_by_year(self, conn, csv_path: str, target_date: str):
        year = target_date[:4]
        return self._find_by_range(conn, csv_path, f"{year}-01-01", f"{year}-12-31", f"year {year}")

    def _find_by_decade(self, conn, csv_path: str, target_date: str):
        decade_start = int(target_date[:4]) // 10 * 10
        return self._find_by_range(
            conn, csv_path,
            f"{decade_start}-01-01", f"{decade_start + 9}-12-31",
            f"the {decade_start}s",
        )

    def _find_by_range(self, conn, csv_path: str, start: str, end: str, label: str):
        result = conn.execute(
            f"""
            SELECT mission_name, launch_date, country, spacecraft, outcome
            FROM read_csv_auto('{csv_path}')
            WHERE launch_date::DATE BETWEEN DATE '{start}' AND DATE '{end}'
            ORDER BY launch_date
            """
        )
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
        conn.close()

        col_widths = [
            max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(c)
            for i, c in enumerate(columns)
        ]
        col_widths = [min(w, 40) for w in col_widths]

        header = "  ".join(c.ljust(w) for c, w in zip(columns, col_widths))
        sep = "  ".join("-" * w for w in col_widths)
        lines = [
            f"\n=== Moon missions in {label} ({len(rows)} found) ===",
            header, sep,
        ]
        for row in rows:
            lines.append("  ".join(str(v)[:w].ljust(w) for v, w in zip(row, col_widths)))
        lines.append(f"=== {len(rows)} mission(s) ===")
        self.log.info("\n".join(lines))

        return {"count": len(rows), "range": f"{start} to {end}"}
