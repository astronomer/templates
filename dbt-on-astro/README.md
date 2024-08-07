# Project Overview

Apache Airflow is one of the most widely-used engines for orchestrating Extract, Transform, and Load (ETL) jobs, especially for transformations using [dbt](https://www.getdbt.com). dbt is a framework to create reliable transformations to produce high-quality data for businesses, usually in analytical databases like Snowflake and BigQuery.

This project showcases using dbt and Airflow together with [Cosmos](https://github.com/astronomer/astronomer-cosmos), allowing users to deploy dbt in production with Airflow best-practices.

# Learning Paths

To learn more about data engineering with Apache Airflow, dbt, and Cosmos, make a few changes to this project! For example, try one of the following:

1. Write a new DAG to 
2. Take a look at the architecture of [Ask Astro](https://github.com/astronomer/ask-astro), Astronomer's reference architecture for LLM applications

# Project Contents

Your Astro project contains the following files and folders:

- dags: This folder contains the Python files for your Airflow DAGs. By default, this directory includes one example DAG:
  - `example_vector_embeddings.py`: This DAG demonstrates how to compute vector embeddings of words using the SentenceTransformers library and
    compare the embeddings of a word of interest to a list of words to find the semantically closest match.get-started-with-airflow).
- Dockerfile: This file contains a versioned Astro Runtime Docker image that provides a differentiated Airflow experience. If you want to execute other commands or overrides at runtime, specify them here.
- include: This folder contains any additional files that you want to include as part of your project. It is empty by default.
- packages.txt: Install OS-level packages needed for your project by adding them to this file. It is empty by default.
- requirements.txt: Install Python packages needed for your project by adding them to this file. It is empty by default.
- plugins: Add custom or community plugins for your project to this file. It is empty by default.
- airflow_settings.yaml: Use this local-only file to specify Airflow Connections, Variables, and Pools instead of entering them in the Airflow UI as you develop DAGs in this project.
