import json
import os
from pathlib import Path
from typing import Dict

from box import Box


class GithubActionContext:
    """
    Hydrate the context from the environment
    """

    def __init__(self):
        self.payload: Dict = {}
        if "GITHUB_EVENT_PATH" in os.environ:
            event_path = os.environ["GITHUB_EVENT_PATH"]
            if Path(event_path).exists():
                with open(event_path, "r") as f:
                    # TODO check if need in real GITHUB_ACTIONS
                    self.payload = Box(json.load(f))
                    if self.payload.get("payload", None) is not None:
                        self.payload = self.payload.payload
                self.payload["repository"]["full_name"] = self.full_name
            else:
                print(f"GITHUB_EVENT_PATH {event_path} does not exist")

        self.event_name = os.environ.get("GITHUB_EVENT_NAME")
        self.sha = os.environ.get("GITHUB_SHA")
        self.ref = os.environ.get("GITHUB_REF")
        self.workflow = os.environ.get("GITHUB_WORKFLOW")
        self.action = os.environ.get("GITHUB_ACTION")
        self.actor = os.environ.get("GITHUB_ACTOR")
        self.job = os.environ.get("GITHUB_JOB")
        self.run_number = int(os.environ.get("GITHUB_RUN_NUMBER", 0))
        self.run_id = int(os.environ.get("GITHUB_RUN_ID", 0))
        self.api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        self.server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        self.graphql_url = os.environ.get(
            "GITHUB_GRAPHQL_URL", "https://api.github.com/graphql"
        )

    @property
    def full_name(self):
        return f"{self.repo['owner']}/{self.repo['repo']}"

    @property
    def issue(self) -> Dict[str, str]:
        return {
            **self.repo,
            "number": (
                self.payload.get("issue")
                or self.payload.get("pull_request")
                or self.payload
            ).get("number"),
        }

    @property
    def repo(self) -> Dict[str, str]:
        if "GITHUB_REPOSITORY" in os.environ:
            owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
            return {"owner": owner, "repo": repo}
        if "pull_request" in self.payload:
            return {
                "owner": self.payload["pull_request"]["base"]["repo"]["owner"]["login"],
                "repo": self.payload["pull_request"]["base"]["repo"]["name"],
            }
        raise ValueError(
            "context.repo requires a GITHUB_REPOSITORY environment variable like 'owner/repo'"
        )

    def __str__(self):
        """
        Print all the fields in the context
        """
        return json.dumps(self.__dict__, indent=2)


GITHUB_ACTION_CONTEXT = GithubActionContext()
