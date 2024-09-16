import json
import os
from pathlib import Path

from core.input_reader import read_yaml_file

AVATAR_URL = "https://github.adx.fcagroup.com/avatars/u/355"
ROOT_FOLDER = Path(__file__).resolve().parent.parent
ACTION_INPUTS = (
    {"inputs": json.loads(os.environ.get("INPUTS").strip("'"))}
    if "GITHUB_ACTIONS" in os.environ
    else read_yaml_file(str(ROOT_FOLDER.joinpath("action.yml")))
)
BOT_NAME = "@devtoolsai"
BOT_NAME_NO_TAG = "Dev Tools AI"
IGNORE_KEYWORD = f"{BOT_NAME}: ignore"
PR_LINES_LIMIT = 1000
FEEDBACK_EMAIL = "devtools@stellantis.com"
DISMISSAL_MESSAGE = (
    "🤖🙂 Review deleted, smiles undefeated! 🙂🤖 (option less_spammy ✅)"
)
