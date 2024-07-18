"""
## Compute and compare vector embeddings of words

This DAG demonstrates how to compute vector embeddings of words using the SentenceTransformers library and
compare the embeddings of a word of interest to a list of words to find the semantically closest match.
"""

from airflow.decorators import dag, task
from airflow.models.baseoperator import chain
from airflow.models.param import Param
from pendulum import datetime
from tabulate import tabulate
import duckdb
import logging
import os

# use the Airflow task logger to log information to the task logs
t_log = logging.getLogger("airflow.task")

# define variables used in a DAG in the DAG code or as environment variables for your whole Airflow instance
# avoid hardcoding values in the DAG code
_DUCKDB_INSTANCE_NAME = os.getenv("DUCKDB_INSTANCE_NAME", "include/astronomy.db")
_DUCKDB_TABLE_NAME = os.getenv("DUCKDB_TABLE_NAME", "embeddings_table")


def get_embeddings_one_word(word):
    """
    Embeds a single word using the SentenceTransformers library.
    Args:
        word (str): The word to embed.
    Returns:
        dict: A dictionary with the word as key and the embeddings as value.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")

    embeddings = model.encode(word)
    embeddings = embeddings.tolist()

    return {word: embeddings}


# Define the basic parameters of the DAG, like schedule and start_date
@dag(
    start_date=datetime(2024, 5, 1),
    schedule="@daily",
    catchup=False,
    max_consecutive_failed_dag_runs=5,  # auto-pauses the DAG after 5 consecutive failed runs
    max_active_runs=1,
    doc_md=__doc__,
    default_args={"owner": "Astro", "retries": 3},
    tags=["example", "ETL"],
    params={
        "my_word_of_interest": Param(
            "star",
            type="string",
            title="The word you want to search a close match for.",
            minLength=1,
            maxLength=50,
        ),
        "my_list_of_words": Param(
            ["sun", "rocket", "planet", "light", "happiness"],
            type="array",
            title="A list of words to compare to the word of interest.",
        ),
    },
)
def example_vector_embeddings():
    @task
    def get_words(**context) -> list:
        """
        Get the list of words to embed from the context.
        Returns:
            list: A list of words to embed.
        """
        words = context["params"]["my_list_of_words"]

        return words

    @task
    def create_embeddings(list_of_words: list) -> list:
        """
        Create embeddings for a list of words.
        Args:
            list_of_words (list): A list of words to embed.
        Returns:
            list: A list of dictionaries with the words as keys and the embeddings as values.
        """

        list_of_words_and_embeddings = []

        for word in list_of_words:
            word_and_embeddings = get_embeddings_one_word(word)
            list_of_words_and_embeddings.append(word_and_embeddings)

        return list_of_words_and_embeddings

    @task(
        max_active_tis_per_dag=1,
    )
    def create_vector_table(
        duckdb_instance_name: str = _DUCKDB_INSTANCE_NAME,
        table_name: str = _DUCKDB_TABLE_NAME,
    ) -> None:
        """
        Create a table in DuckDB to store the embeddings.
        Args:
            duckdb_instance_name (str): The name of the DuckDB instance.
            table_name (str): The name of the table to create.
        """

        cursor = duckdb.connect(duckdb_instance_name)
        cursor.execute("INSTALL vss;")
        cursor.execute("LOAD vss;")
        cursor.execute("SET hnsw_enable_experimental_persistence = true;")

        table_name = "embeddings_table"

        cursor.execute(
            f"""
            CREATE OR REPLACE TABLE {table_name} (
                text STRING,
                vec FLOAT[384]
            );

            -- Create an HNSW index on the embedding vector
            CREATE INDEX my_hnsw_index ON {table_name} USING HNSW (vec);
            """
        )
        cursor.close()

    @task(
        max_active_tis_per_dag=1,
    )
    def insert_words_into_db(
        duckdb_instance_name: str = _DUCKDB_INSTANCE_NAME,
        table_name: str = _DUCKDB_TABLE_NAME,
        list_of_words_and_embeddings: list = None,
    ) -> None:
        """
        Insert words and their embeddings into the DuckDB table.
        Args:
            duckdb_instance_name (str): The name of the DuckDB instance.
            table_name (str): The name of the table to insert into.
            list_of_words_and_embeddings (list): A list of dictionaries with words as keys and embeddings as values.
        """

        cursor = duckdb.connect(duckdb_instance_name)
        cursor.execute("LOAD vss;")

        for i in list_of_words_and_embeddings:
            word = list(i.keys())[0]
            vec = i[word]
            cursor.execute(
                f"""
                INSERT INTO {table_name} (text, vec)
                VALUES (?, ?);
                """,
                (word, vec),
            )

        cursor.close()

    @task
    def embed_word(**context):
        """
        Embed a single word and return the embeddings.
        Returns:
            dict: A dictionary with the word as key and the embeddings as value.
        """

        my_word_of_interest = context["params"]["my_word_of_interest"]
        embeddings = get_embeddings_one_word(my_word_of_interest)

        embeddings = embeddings[my_word_of_interest]

        return {my_word_of_interest: embeddings}

    @task(
        max_active_tis_per_dag=1,
    )
    def find_closest_word_match(
        duckdb_instance_name: str = _DUCKDB_INSTANCE_NAME,
        table_name: str = _DUCKDB_TABLE_NAME,
        word_of_interest_embedding: dict = None,
    ):
        """
        Find the closest word match to the word of interest in the DuckDB table.
        Args:
            duckdb_instance_name (str): The name of the DuckDB instance.
            table_name (str): The name of the table to query.
            word_of_interest_embedding (dict): A dictionary with the word as key and the embeddings as value.
        Returns:
            list: A list of the top 3 closest words to the word of interest.
        """

        cursor = duckdb.connect(duckdb_instance_name)
        cursor.execute("LOAD vss;")

        word = list(word_of_interest_embedding.keys())[0]
        vec = word_of_interest_embedding[word]

        top_3 = cursor.execute(
            f"""
            SELECT text FROM {table_name}
            ORDER BY array_distance(vec, {vec}::FLOAT[384])
            LIMIT 3;
            """
        )

        top_3 = top_3.fetchall()

        t_log.info(f"Top 3 closest words to '{word}':")
        t_log.info(tabulate(top_3, headers=["Word"], tablefmt="pretty"))

        return top_3

    # Define the task dependencies
    create_embeddings_obj = create_embeddings(list_of_words=get_words())
    embed_word_obj = embed_word()

    chain(
        create_vector_table(),
        insert_words_into_db(list_of_words_and_embeddings=create_embeddings_obj),
        find_closest_word_match(word_of_interest_embedding=embed_word_obj),
    )


example_vector_embeddings()
