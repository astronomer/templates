"Contains profile mappings used in the project"

from cosmos import ProfileConfig
from pathlib import Path

from constants import jaffle_shop_path

airflow_db = ProfileConfig(
    profile_name="airflow_db",
    target_name="dev",
    profiles_yml_filepath=Path(jaffle_shop_path, "profiles.yml"),
)
