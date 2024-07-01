"""
## Galaxies ETL example DAG

This example demonstrates an ETL pipeline using Airflow. 
The pipeline extracts data about galaxies, filters the data based on the distance 
from the Milky Way, and loads the filtered data into a DuckDB database.
"""

from airflow.decorators import dag, task
from airflow.models.dataset import Dataset
from airflow.models.baseoperator import chain
from pendulum import datetime
from tabulate import tabulate
import pandas as pd
import duckdb
import logging
import os

# modularize code by importing functions from the include folder
from include.custom_functions.galaxy_functions import get_galaxy_data

# use the Airflow task logger to log information to the task logs
t_log = logging.getLogger("airflow.task")

# define variables used in a DAG in the DAG code or as environment variables for your whole Airflow instance
# avoid hardcoding values in the DAG code
_CLOSENESS_THRESHOLD_LIGHT_YEARS = os.getenv("CLOSENESS_THRESHOLD_LIGHT_YEARS", 500000)
_NUM_GALAXIES_TOTAL = os.getenv("NUM_GALAXIES_TOTAL", 20)
_DUCKDB_INSTANCE_NAME = os.getenv("DUCKDB_INSTANCE_NAME", "include/astronomy.db")
_DUCKDB_TABLE_NAME = os.getenv("DUCKDB_TABLE_NAME", "galaxy_data")
_DUCKDB_TABLE_URI = f"duckdb://{_DUCKDB_INSTANCE_NAME}/{_DUCKDB_TABLE_NAME}"


# Define the basic parameters of the DAG, like schedule and start_date
@dag(
    start_date=datetime(2024, 5, 1),
    schedule="@daily",
    catchup=False,
    max_consecutive_failed_dag_runs=5,  # auto-pauses the DAG after 5 consecutive failed runs
    doc_md=__doc__,
    default_args={"owner": "Astro", "retries": 3},
    tags=["example", "ETL"],
)
def example_etl_galaxies():

    @task
    def create_galaxy_table_in_duckdb(
        duckdb_instance_name: str = _DUCKDB_INSTANCE_NAME,
        table_name: str = _DUCKDB_TABLE_NAME,
    ):
        """
        Create a table in DuckDB to store galaxy data.
        This task simulates a setup step in an ETL pipeline.
        Args:
            duckdb_instance_name: The name of the DuckDB instance.
            table_name: The name of the table to be created.
        """

        t_log.info("Creating galaxy table in DuckDB.")

        cursor = duckdb.connect(duckdb_instance_name)

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                name STRING PRIMARY KEY,
                distance_from_milkyway INT,
                distance_from_solarsystem INT,
                type_of_galaxy STRING,
                characteristics STRING
            )"""
        )
        cursor.close()

        t_log.info(f"Table {table_name} created in DuckDB.")

    @task
    def extract_galaxy_data(num_galaxies: int = _NUM_GALAXIES_TOTAL) -> pd.DataFrame:
        """
        Retrieve data about galaxies.
        This task simulates an extraction step in an ETL pipeline.
        Args:
            num_galaxies (int): The number of galaxies for which data should be returned.
            Default is 20. Maximum is 20.
        Returns:
            pd.DataFrame: A DataFrame containing data about galaxies.
        """

        galaxy_df = get_galaxy_data(num_galaxies)

        return galaxy_df

    @task
    def transform_galaxy_data(
        galaxy_df: pd.DataFrame,
        closeness_threshold_light_years: int = _CLOSENESS_THRESHOLD_LIGHT_YEARS,
    ):
        """
        Filter the galaxy data based on the distance from the Milky Way.
        This task simulates a transformation step in an ETL pipeline.
        Args:
            closeness_threshold_light_years (int): The threshold for filtering
            galaxies based on distance.
            Default is 500,000 light years.
        Returns:
            pd.DataFrame: A DataFrame containing filtered galaxy data.
        """

        t_log.info(
            f"Filtering for galaxies closer than {closeness_threshold_light_years} light years."
        )

        filtered_galaxy_df = galaxy_df[
            galaxy_df["distance_from_milkyway"] < closeness_threshold_light_years
        ]

        return filtered_galaxy_df

    @task(
        outlets=[
            Dataset(_DUCKDB_TABLE_URI)
        ]  # Define that this task updates the `galaxy_data` Dataset
    )
    def load_galaxy_data(
        filtered_galaxy_df: pd.DataFrame,
        duckdb_instance_name: str = _DUCKDB_INSTANCE_NAME,
        table_name: str = _DUCKDB_TABLE_NAME,
    ):
        """
        Load the filtered galaxy data into a DuckDB database.
        This task simulates a loading step in an ETL pipeline.
        Args:
            filtered_galaxy_df (pd.DataFrame): The filtered galaxy data to be loaded.
            duckdb_instance_name (str): The name of the DuckDB instance.
            table_name (str): The name of the table to load the data into.
        """

        t_log.info("Loading galaxy data into DuckDB.")
        cursor = duckdb.connect(duckdb_instance_name)
        cursor.sql(
            f"INSERT OR IGNORE INTO {table_name} BY NAME SELECT * FROM filtered_galaxy_df;"
        )
        t_log.info("Galaxy data loaded into DuckDB.")

    @task
    def print_loaded_galaxies(
        duckdb_instance_name: str = _DUCKDB_INSTANCE_NAME,
        table_name: str = _DUCKDB_TABLE_NAME,
    ):
        """
        Get the galaxies stored in the DuckDB database that were filtered
        based on closeness to the Milky Way.
        Args:
            duck_db_conn_id (str): The connection ID for the duckdb database
            where the table is stored.
        Returns:
            pd.DataFrame: A DataFrame containing the galaxies closer than
            500,000 light years from the Milky Way.
        """

        cursor = duckdb.connect(duckdb_instance_name)
        near_galaxies_df = cursor.sql(f"SELECT * FROM {table_name};").df()
        near_galaxies_df = near_galaxies_df.sort_values(
            by="distance_from_milkyway", ascending=True
        )
        t_log.info(tabulate(near_galaxies_df, headers="keys", tablefmt="pretty"))

    # Define the task dependencies
    create_galaxy_table_in_duckdb_obj = create_galaxy_table_in_duckdb()
    extract_galaxy_data_obj = extract_galaxy_data()
    transform_galaxy_data_obj = transform_galaxy_data(extract_galaxy_data_obj)
    load_galaxy_data_obj = load_galaxy_data(transform_galaxy_data_obj)

    chain(
        create_galaxy_table_in_duckdb_obj, load_galaxy_data_obj, print_loaded_galaxies()
    )


# Instantiate the DAG
example_etl_galaxies()
