from types import SimpleNamespace

from core.consts import ACTION_INPUTS, BOT_NAME_NO_TAG
from core.utils import get_input_default

COMMENT_GREETING = (
    f"{get_input_default(ACTION_INPUTS, key='bot_icon')} {BOT_NAME_NO_TAG}"
)

COMMENT_TAG = f"<!-- This is an auto-generated comment by {BOT_NAME_NO_TAG} -->"

COMMENT_REPLY_TAG = f"<!-- This is an auto-generated reply by {BOT_NAME_NO_TAG} -->"

SUMMARIZE_TAG = (
    f"<!-- This is an auto-generated comment: summarize by {BOT_NAME_NO_TAG} -->"
)

IN_PROGRESS_START_TAG = f"<!-- This is an auto-generated comment: summarize review in progress by {BOT_NAME_NO_TAG} -->"

IN_PROGRESS_END_TAG = f"<!-- end of auto-generated comment: summarize review in progress by {BOT_NAME_NO_TAG} -->"

DESCRIPTION_START_TAG = (
    f"<!-- This is an auto-generated comment: release notes by {BOT_NAME_NO_TAG} -->"
)
DESCRIPTION_END_TAG = (
    f"<!-- end of auto-generated comment: release notes by {BOT_NAME_NO_TAG} -->"
)

RAW_SUMMARY_START_TAG = (
    f"<!-- This is an auto-generated comment: raw summary by {BOT_NAME_NO_TAG} --><!--"
)
RAW_SUMMARY_END_TAG = (
    f"--><!-- end of auto-generated comment: raw summary by {BOT_NAME_NO_TAG} -->"
)

SHORT_SUMMARY_START_TAG = f"<!-- This is an auto-generated comment: short summary by {BOT_NAME_NO_TAG} --><!--"

SHORT_SUMMARY_END_TAG = (
    f"--><!-- end of auto-generated comment: short summary by {BOT_NAME_NO_TAG} -->"
)

COMMIT_ID_START_TAG = "<!-- commit_ids_reviewed_start -->"
COMMIT_ID_END_TAG = "<!-- commit_ids_reviewed_end -->"

TAGS = SimpleNamespace(
    COMMENT_GREETING=COMMENT_GREETING,
    COMMENT_TAG=COMMENT_TAG,
    COMMENT_REPLY_TAG=COMMENT_REPLY_TAG,
    SUMMARIZE_TAG=SUMMARIZE_TAG,
    IN_PROGRESS_START_TAG=IN_PROGRESS_START_TAG,
    IN_PROGRESS_END_TAG=IN_PROGRESS_END_TAG,
    DESCRIPTION_START_TAG=DESCRIPTION_START_TAG,
    DESCRIPTION_END_TAG=DESCRIPTION_END_TAG,
    RAW_SUMMARY_START_TAG=RAW_SUMMARY_START_TAG,
    RAW_SUMMARY_END_TAG=RAW_SUMMARY_END_TAG,
    SHORT_SUMMARY_START_TAG=SHORT_SUMMARY_START_TAG,
    SHORT_SUMMARY_END_TAG=SHORT_SUMMARY_END_TAG,
    COMMIT_ID_START_TAG=COMMIT_ID_START_TAG,
    COMMIT_ID_END_TAG=COMMIT_ID_END_TAG,
)
