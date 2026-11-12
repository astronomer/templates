"""DAG loader -- discovers all *.dag.yaml files and builds them into Airflow DAGs.

Blueprint classes are auto-discovered from Python files in the same directory tree.
"""

from blueprint import build_all

build_all(
    # Applied to every DAG; a DAG's own YAML values take precedence.
    dag_defaults={
        "default_args": {
            "retries": 3,  # tasks retry 3 times before they fail
            "retry_delay_seconds": 30,  # tasks wait 30s in between retries
        },
    },
)
