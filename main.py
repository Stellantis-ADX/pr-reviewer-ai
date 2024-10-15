import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

from box import Box
from github_action_utils import error
from github_action_utils import notice
from github_action_utils import notice as warning

from core.bot_hf import HFBot, HFOptions
from core.bot_mistral import MistralBot, MistralOptions
from core.consts import ACTION_INPUTS, PR_LINES_LIMIT
from core.review.code import code_review
from core.review.comment import handle_review_comment
from core.schemas.options import Options
from core.schemas.prompts import Prompts
from core.utils import get_input_default, get_total_new_lines, string_to_bool

# Entry point of the application.
# This function is responsible for running the code review process based on the provided options and prompts.
# It creates two instances of the Bot class, one for summary and one for review.
# It checks the event type and performs the appropriate action based on the event.
# If the event is a pull request, it calls the codeReview function.
# If the event is a pull request review comment, it calls the handleReviewComment function.
# If the event is neither a pull request nor a pull request review comment, it logs a warning message.
# If any error occurs during the process, it sets the action as failed and logs the error message.

WORKSPACE_PATH = Path(__file__).resolve().parent

sys.path.insert(1, str(WORKSPACE_PATH))


def debug_context():
    payload = {}
    if "GITHUB_EVENT_PATH" in os.environ:
        event_path = os.environ["GITHUB_EVENT_PATH"]
        if Path(event_path).exists():
            with open(event_path, "r") as f:
                # TODO check if need in real GITHUB_ACTIONS
                payload = Box(json.load(f))
                if payload.get("payload", None) is not None:
                    payload = payload.payload

        else:
            notice(f"[EARLY DEBUG]: GITHUB_EVENT_PATH {event_path} does not exist")
    payload = json.dumps(payload, indent=2)
    notice(
        f"[EARLY DEBUG]: -------------------- EARLY DEBUG CONTEXT--------------------:\n {payload}"
    )


async def run():
    try:
        options = Options(
            debug=string_to_bool(get_input_default(ACTION_INPUTS, key="debug")),
            disable_review=string_to_bool(
                get_input_default(ACTION_INPUTS, key="disable_review")
            ),
            disable_release_notes=string_to_bool(
                get_input_default(ACTION_INPUTS, key="disable_release_notes")
            ),
            max_files=get_input_default(ACTION_INPUTS, key="max_files"),
            review_simple_changes=string_to_bool(
                get_input_default(ACTION_INPUTS, key="review_simple_changes")
            ),
            review_comment_lgtm=string_to_bool(
                get_input_default(ACTION_INPUTS, key="review_comment_lgtm")
            ),
            path_filters=get_input_default(ACTION_INPUTS, key="path_filters"),
            system_message=get_input_default(ACTION_INPUTS, key="system_message"),
            light_model_name=get_input_default(ACTION_INPUTS, key="light_model_name"),
            heavy_model_name=get_input_default(ACTION_INPUTS, key="heavy_model_name"),
            model_temperature=get_input_default(ACTION_INPUTS, key="model_temperature"),
            retries=get_input_default(ACTION_INPUTS, key="retries"),
            timeout_ms=get_input_default(ACTION_INPUTS, key="timeout_ms"),
            concurrency_limit=get_input_default(ACTION_INPUTS, key="concurrency_limit"),
            github_concurrency_limit=get_input_default(
                ACTION_INPUTS, key="github_concurrency_limit"
            ),
            api_base_urls=get_input_default(ACTION_INPUTS, key="api_base_url"),
            language=get_input_default(ACTION_INPUTS, key="language"),
            light_model_port=get_input_default(ACTION_INPUTS, key="light_model_port"),
            heavy_model_port=get_input_default(ACTION_INPUTS, key="heavy_model_port"),
            allow_empty_review=string_to_bool(
                get_input_default(ACTION_INPUTS, key="allow_empty_review")
            ),
            less_spammy=string_to_bool(
                get_input_default(ACTION_INPUTS, key="less_spammy")
            ),
            api_base_url_azure=get_input_default(
                ACTION_INPUTS, key="api_base_url_azure"
            ),
            light_model_name_azure=get_input_default(
                ACTION_INPUTS, key="light_model_name_azure"
            ),
            light_model_token_azure=get_input_default(
                ACTION_INPUTS, key="light_model_token_azure"
            ),
            heavy_model_name_azure=get_input_default(
                ACTION_INPUTS, key="heavy_model_name_azure"
            ),
            heavy_model_token_azure=get_input_default(
                ACTION_INPUTS, key="heavy_model_token_azure"
            ),
        )

        options.print()

        prompts = Prompts(
            summarize=get_input_default(ACTION_INPUTS, key="summarize"),
            summarize_release_notes=get_input_default(
                ACTION_INPUTS, key="summarize_release_notes"
            ),
        )

        # Create two bots, one for summary and one for review

        try:
            light_bot_azure = None
            if options.light_model_token_azure:
                light_bot_azure = MistralBot(
                    options,
                    MistralOptions(
                        options.light_model_name_azure, options.light_token_limits_azure
                    ),
                    api_key=options.light_model_token_azure,
                    base_url=options.api_base_url_azure[0],
                )
            light_bot = HFBot(
                options,
                HFOptions(options.light_model_name, options.light_token_limits),
                back_up_bot=light_bot_azure,
            )

        except Exception as e:
            warning(
                f"Skipped: failed to create summary bot {options.light_model_name}: {e}, "
                f"backtrace: {e.__traceback__}"
            )
            return

        try:
            heavy_bot_azure = None
            if options.heavy_model_token_azure:
                heavy_bot_azure = MistralBot(
                    options,
                    MistralOptions(
                        options.heavy_model_name_azure, options.heavy_token_limits_azure
                    ),
                    api_key=options.heavy_model_token_azure,
                    base_url=options.api_base_url_azure[1],
                )
            heavy_bot = HFBot(
                options,
                HFOptions(options.heavy_model_name, options.heavy_token_limits),
                back_up_bot=heavy_bot_azure,
            )

        except Exception as e:
            warning(
                f"Skipped: failed to create review bot {options.heavy_model_name}:"
                f" {e}, backtrace: {str(e.__traceback__)}"
            )
            return

        numbers_new_lines = get_total_new_lines()
        print("Number of new lines in PR: ", numbers_new_lines)

        try:
            # check if the event is pull_request
            event_name = os.getenv("GITHUB_EVENT_NAME")
            if event_name in ("pull_request", "pull_request_target"):

                if numbers_new_lines > PR_LINES_LIMIT:
                    warning("PR is too large, skipping review process.")
                    return

                code_review(light_bot, heavy_bot, options, prompts)
            elif event_name == "pull_request_review_comment":
                handle_review_comment(heavy_bot, options, prompts)
            else:
                warning(
                    "Skipped: this action only works on push events or pull_request"
                )
        except Exception as e:
            #  TODO must be set fail
            error(f"Failed to run: {str(e)}, backtrace: {traceback.format_exc()}")

    except Exception as e:
        warning(f"Unhandled exception: {str(e)}, backtrace: {e.__traceback__}")


if __name__ == "__main__":
    debug_context()
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()
