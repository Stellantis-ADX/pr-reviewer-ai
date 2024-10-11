import contextlib
import warnings
from typing import Any, Dict

import requests
from urllib3.exceptions import InsecureRequestWarning

from core.github.context import GITHUB_ACTION_CONTEXT
from core.github.github import GITHUB_API


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


def git_diff_from_discussion(
    diff: str, start_line: int, end_line: int, html_url: str
) -> str:
    try:
        if "discussion" in html_url:
            return "\n".join(diff.split("\n")[start_line : end_line + 1])
    except Exception as e:
        print(f"Failed to get diff from discussion: {e}")
        print(f"Will use the diff_chunk from comment: {diff}")
    return diff


def get_total_new_lines():
    # Authenticate with GitHub using the personal access token
    github_context = GITHUB_ACTION_CONTEXT
    repo = GITHUB_API.get_repo(github_context.payload.repository.full_name)

    # Get the pull request
    pull = repo.get_pull(github_context.payload.pull_request.number)

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
