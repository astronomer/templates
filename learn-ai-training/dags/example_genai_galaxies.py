"""
### Galaxies Gen AI example DAG

This example demonstrates a Gen AI pipeline using Airflow. 
The pipeline loads galaxy names from a DuckDB database and a text file, 
prepares the data for training a Gen AI model, trains the model, 
generates prompts for the model, and generates new galaxy names using the 
trained model.
"""

from airflow.decorators import dag, task
from airflow.models.dataset import Dataset
from airflow.models.baseoperator import chain
from pendulum import datetime
import logging
import duckdb
import os

# use the Airflow task logger to log information to the task logs
t_log = logging.getLogger("airflow.task")

# define variables used in a DAG in the DAG code or as environment variables for your whole Airflow instance
# avoid hardcoding values in the DAG code
_DUCKDB_INSTANCE_NAME = os.getenv("DUCKDB_INSTANCE_NAME", "include/astronomy.db")
_DUCKDB_TABLE_NAME = os.getenv("DUCKDB_TABLE_NAME", "galaxy_data")
_DUCKDB_TABLE_URI = f"duckdb://{_DUCKDB_INSTANCE_NAME}/{_DUCKDB_TABLE_NAME}"
_FILEPATH_GALAXY_NAMES = os.getenv(
    "FILEPATH_GALAXY_NAMES", "include/data/galaxy_names.txt"
)

## Model parameters
_MODEL_PATH = os.getenv("MODEL_PATH", "include/galaxy_name_gen.h5")
# define the valid characters for the Gen AI model to learn and generate from, must include all characters from the training data
_VALID_CHARS = os.getenv("VALID_CHARS", "abcdefghijklmnopqrstuvwxyz ")
# define the length of each input sequence when training the model
_INPUT_SEQ_LENGTH = os.getenv("INPUT_SEQ_LENGTH", 5)
# define which terms to remove from the training data to reduce bias towards certain types of galaxy names
_TERMS_TO_REMOVE_FROM_TRAINING_DATA = os.getenv(
    "TERMS_TO_REMOVE_FROM_TRAINING_DATA", ["galaxy", "dwarf", "spheroidal"]
)

## Inference parameters
_NUM_PROMPTS = os.getenv("NUM_PROMPTS", 5)


# define the basic parameters of the DAG, like schedule and start_date
@dag(
    start_date=datetime(2024, 5, 1),
    schedule=[Dataset(_DUCKDB_TABLE_URI)],
    catchup=False,
    max_consecutive_failed_dag_runs=5,  # auto-pauses the DAG after 5 consecutive failed runs
    doc_md=__doc__,
    default_args={"owner": "Astro", "retries": 3},
    tags=["example", "ETL"],
)
def example_genai_galaxies():

    @task
    def load_galaxy_names(
        duckdb_instance_name: str = _DUCKDB_INSTANCE_NAME,
        table_name: str = _DUCKDB_TABLE_NAME,
        filepath_galaxy_names: str = _FILEPATH_GALAXY_NAMES,
    ) -> list[str]:
        """
        Load galaxy names from DuckDB and a local text file.
        Args:
            duckdb_instance_name: The name of the DuckDB instance.
            table_name: The name of the table in DuckDB.
            filepath_galaxy_names: The filepath to a text file with galaxy names.
        Returns:
            A list of galaxy names.
        """

        # if the `example_etl_galaxies` DAG is run before this DAG, some galaxy names can be loaded from DuckDB
        try:
            t_log.info("Loading galaxy names from DuckDB.")
            cursor = duckdb.connect(duckdb_instance_name)
            galaxy_names = cursor.execute(f"SELECT name FROM {table_name}").fetchall()
            galaxy_names_list = [name[0] for name in galaxy_names]
        except:
            t_log.error(
                "Error loading galaxy names from DuckDB. Will only load from text file."
            )
            galaxy_names_list = []

        # always add galaxy names from the text file
        with open(filepath_galaxy_names, "r") as f:
            galaxy_names_list += f.read().splitlines()

        # lowercase all galaxy names to reduce complexity
        galaxy_names_list = [name.lower() for name in galaxy_names_list]

        return galaxy_names_list

    @task
    def transform_galaxy_names(
        galaxy_names_list: list[str],
        terms_to_remove_from_training_data: list[
            str
        ] = _TERMS_TO_REMOVE_FROM_TRAINING_DATA,
    ) -> list[str]:
        """
        Transform the galaxy names by removing numbers and specific overused terms.
        Args:
            galaxy_names_list: A list of galaxy names.
        Returns:
            A list of transformed galaxy names.
        """

        galaxy_names_list = [
            name
            for name in galaxy_names_list
            if not any(char.isdigit() for char in name)
        ]

        for term in terms_to_remove_from_training_data:
            galaxy_names_list = [
                name.replace(term, "").strip() for name in galaxy_names_list
            ]

        return galaxy_names_list

    @task
    def prepare_training_data(
        galaxy_names_list: list[str],
        valid_chars=_VALID_CHARS,
        input_seq_length: int = _INPUT_SEQ_LENGTH,
    ) -> dict:
        """
        Prepare training data for the Gen AI model. This means processing the galaxy
        names into sequences of integers.
        Args:
            galaxy_names_list: A list of galaxy names.
        Returns:
            A dictionary containing the training data and parameters.
        """
        import numpy as np
        from tensorflow.keras.utils import to_categorical

        # map characters to integers
        char_to_int = {char: i for i, char in enumerate(sorted(set(valid_chars)))}
        train_set_vocab_size = len(char_to_int)

        # encode the characters of the galaxy names into sequences of integers to learn from
        # the input for the model will be a sequence of length seq_length and the output will
        # be the next character in the sequence, the model learns to predict the next character!
        dataX = []
        dataY = []
        for name in galaxy_names_list:
            for i in range(0, len(name) - input_seq_length, 1):
                seq_in = name[i : i + input_seq_length]
                seq_out = name[i + input_seq_length]
                dataX.append([char_to_int[char] for char in seq_in])
                dataY.append(char_to_int[seq_out])

        # reshape X for the model
        X = np.reshape(dataX, (len(dataX), input_seq_length, 1))
        # one hot encode the output variable
        y = to_categorical(dataY, num_classes=train_set_vocab_size)

        # convert to json serializable format
        X_list = X.tolist()
        y_list = y.tolist()

        return {
            "X_list": X_list,
            "y_list": y_list,
            "vocab_size": train_set_vocab_size,
            "seq_length": input_seq_length,
        }

    @task
    def train_model(
        train_data_input: dict,
        model_path: str = _MODEL_PATH,
        learning_rate: int = 0.001,
        epochs: int = 200,
        batch_size: int = 64,
        is_early_stopping: bool = True,
        early_stopping_patience: int = 10,
        early_stopping_metric: str = "loss",
        loss_function: str = "categorical_crossentropy",
        embedding_output_dim: int = 256,
        num_neuros_lstm_layer1: int = 128,
        num_neuros_lstm_layer2: int = 128,
        output_activation: str = "softmax",
    ):
        """
        Train a Gen AI model to generate new galaxy names.
        Args:
            train_data_input: A dictionary containing the training data and parameters.
            model_path: The path to save the trained model.
        """

        from keras import layers, models, optimizers, callbacks
        import numpy as np

        X_list = train_data_input["X_list"]
        y_list = train_data_input["y_list"]
        vocab_size = train_data_input["vocab_size"]
        seq_length = train_data_input["seq_length"]

        X = np.array(X_list)
        y = np.array(y_list)

        # model architecture
        inputs = layers.Input(shape=(seq_length,))
        embedding = layers.Embedding(
            input_dim=vocab_size, output_dim=embedding_output_dim
        )(inputs)
        lstm1 = layers.Bidirectional(
            layers.LSTM(num_neuros_lstm_layer1, return_sequences=True)
        )(embedding)
        lstm2 = layers.Bidirectional(layers.LSTM(num_neuros_lstm_layer2))(lstm1)
        outputs = layers.Dense(vocab_size, activation=output_activation)(lstm2)
        model = models.Model(inputs=inputs, outputs=outputs)

        optimizer = optimizers.Adam(learning_rate=learning_rate)

        if is_early_stopping:
            early_stopping = callbacks.EarlyStopping(
                monitor=early_stopping_metric,
                patience=early_stopping_patience,
                restore_best_weights=True,
            )  # early stopping can prevent overfitting

            model.compile(loss=loss_function, optimizer=optimizer)
            model.fit(
                X, y, epochs=epochs, batch_size=batch_size, callbacks=[early_stopping]
            )
        else:
            model.compile(loss=loss_function, optimizer=optimizer)
            model.fit(X, y, epochs=epochs, batch_size=batch_size)

        model.save(model_path)

    @task
    def get_prompts(num_prompts=_NUM_PROMPTS):
        """
        Get prompts for the Gen AI model to generate new galaxy names.
        """
        import random

        prompts_info = []

        for i in range(num_prompts):
            char1 = random.choice("bcdfghjklmnpqrstvwxz")
            char2 = random.choice("aeiouy")
            char3 = random.choice("bcdfghjklmnpqrstvwxz")
            prompt = f"{char1}{char2}{char3}"
            target_length = random.randint(8, 15)
            prompts_info.append({"prompt": prompt, "target_length": target_length})

        return prompts_info

    @task(map_index_template="{{ my_custom_map_index }}")
    def generate_new_galaxy_names(
        prompt_info: str,
        model_path: str = _MODEL_PATH,
        valid_chars=_VALID_CHARS,
        input_seq_length=_INPUT_SEQ_LENGTH,
    ):
        """
        Generate new galaxy names using the trained Gen AI model.
        """
        from keras.models import load_model
        import numpy as np

        model = load_model(model_path)
        prompt = prompt_info["prompt"]
        target_length = prompt_info["target_length"]

        char_to_int = {char: i for i, char in enumerate(sorted(set(valid_chars)))}
        int_to_char = {i: char for char, i in char_to_int.items()}

        def generate_name(model, prompt, length=10):
            result = prompt

            start = prompt[:input_seq_length].ljust(input_seq_length)

            for _ in range(length):

                x = np.array([[char_to_int[char] for char in start]])
                x = np.reshape(x, (1, input_seq_length, 1))
                prediction = model.predict(x, verbose=0)
                index = np.argmax(prediction)
                result += int_to_char[index]
                start = start[1:] + int_to_char[index]

            return result

        new_name = generate_name(model, prompt, length=target_length)

        # set custom map index template
        from airflow.operators.python import get_current_context

        context = get_current_context()
        context["my_custom_map_index"] = f"{prompt} -> {new_name}"

        return new_name

    # set dependencies
    load_galaxy_names_from_duckdb_obj = load_galaxy_names()
    transform_galaxy_names_obj = transform_galaxy_names(
        load_galaxy_names_from_duckdb_obj
    )
    prepare_training_data_obj = prepare_training_data(transform_galaxy_names_obj)
    train_model_obj = train_model(prepare_training_data_obj)
    get_prompts_obj = get_prompts()

    # dynamically map the generate_new_galaxy_names task to get one new galaxy name for each prompt
    generate_new_galaxy_names.expand(prompt_info=get_prompts_obj)

    chain(train_model_obj, get_prompts_obj)


example_genai_galaxies()
