import os
from typing import Any

import yaml


def read_yaml_file(filepath: str) -> dict[str, Any]:
    from github_action_utils import notice as warning

    warning(f"from yaml {os.getcwd()}")
    with open(filepath, "r") as file:
        return yaml.safe_load(file)
