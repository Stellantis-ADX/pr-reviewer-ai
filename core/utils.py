import contextlib
import re
import warnings
from typing import Any, Dict

import requests
from box import Box
from github.PullRequestComment import PullRequestComment
from urllib3.exceptions import InsecureRequestWarning

from core.github import GITHUB_CONTEXT, REPO


def get_input_default(inputs: Dict[str, Any], key: str) -> str:
    key = inputs.get("inputs").get(key)
    if isinstance(key, str):
        return key
    elif isinstance(key, dict):
        return key.get("default")
    raise ValueError(f"Invalid input: {key}")


def string_to_bool(value: str) -> bool:
    if value.lower() == "true":
        return True
    elif value.lower() == "false":
        return False
    else:
        raise ValueError(f"Invalid value: {value}")


@contextlib.contextmanager
def no_ssl_verification():
    old_merge_environment_settings = requests.Session.merge_environment_settings
    opened_adapters = set()

    def merge_environment_settings(self, url, proxies, stream, verify, cert):
        # Verification happens only once per connection so we need to close
        # all the opened adapters once we're done. Otherwise, the effects of
        # verify=False persist beyond the end of this context manager.
        opened_adapters.add(self.get_adapter(url))

        settings = old_merge_environment_settings(
            self, url, proxies, stream, verify, cert
        )
        settings["verify"] = False

        return settings

    requests.Session.merge_environment_settings = merge_environment_settings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            yield
    finally:
        requests.Session.merge_environment_settings = old_merge_environment_settings

        for adapter in opened_adapters:
            try:
                adapter.close()
            except:
                pass


def get_total_new_lines():
    pull = REPO.get_pull(GITHUB_CONTEXT.payload.pull_request.number)

    # Initialize a variable to store the total number of new lines added
    total_new_lines = 0

    # Iterate over the files in the pull request
    for file in pull.get_files():
        # Get the diff hunks for the file
        if file.patch is None:
            print(f"Skipped: {file.filename} has no patch")
            continue
        diff_hunks = file.patch.split("@@")[1:]

        # Iterate over the diff hunks
        for diff_hunk in diff_hunks:
            # Split the diff hunk into lines
            lines = diff_hunk.split("\n")

            # Iterate over the lines in the diff hunk
            for line in lines:
                # If the line starts with a "+", increment the total number of new lines added
                if line.startswith("+"):
                    total_new_lines += 1

    # Return the total number of new lines added
    return total_new_lines


def sanitize_code_block(comment: str, code_block_label: str) -> str:
    code_block_start = f"```{code_block_label}"
    code_block_end = "```"
    line_number_regex = r"^ *(\d+): "

    code_block_start_index = comment.find(code_block_start)

    while code_block_start_index != -1:
        code_block_end_index = comment.find(
            code_block_end, code_block_start_index + len(code_block_start)
        )

        if code_block_end_index == -1:
            break

        code_block = comment[
            code_block_start_index + len(code_block_start) : code_block_end_index
        ]
        sanitized_block = re.sub(line_number_regex, "", code_block, flags=re.MULTILINE)

        comment = (
            comment[: code_block_start_index + len(code_block_start)]
            + sanitized_block
            + comment[code_block_end_index:]
        )

        code_block_start_index = comment.find(
            code_block_start,
            code_block_start_index
            + len(code_block_start)
            + len(sanitized_block)
            + len(code_block_end),
        )

    return comment


def sanitize_response(comment: str) -> str:
    comment = sanitize_code_block(comment, "suggestion")
    comment = sanitize_code_block(comment, "diff")
    return comment


def from_box_comment_to_review_comment(
    box_comment: Box, review_comments: list[PullRequestComment]
) -> PullRequestComment:
    for review_comment in review_comments:
        if (
            review_comment.html_url == box_comment.html_url
            and review_comment.body == box_comment.body
            and review_comment.path == box_comment.path
        ):
            return review_comment

    raise ValueError(
        "Review comment box cannot be found in the list of review comments"
    )
