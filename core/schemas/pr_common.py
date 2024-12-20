from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from github.Commit import Commit
from github.Comparison import Comparison
from github.PaginatedList import PaginatedList
from github_action_utils import warning
from pydantic import BaseModel

from core.bots.bot import Bot
from core.consts import BOT_NAME_NO_TAG, IGNORE_KEYWORD
from core.github import GITHUB_CONTEXT, REPO

if TYPE_CHECKING:  # a hack to avoid circular imports, when we ONLY want to type hint
    # https://peps.python.org/pep-0563/#runtime-annotation-resolution-and-type-checking
    from core.schemas.files import AiSummary
    from core.schemas.options import Options
    from core.schemas.prompts import Prompts

from core.templates.tags import (
    TAGS,
    get_content_within_tags,
    remove_content_within_tags,
)


@dataclass
class PRInfo:
    base_sha: str | None = None
    head_sha: str | None = None
    number: int | None = None
    target_branch_diff: Comparison | None = None
    # Members above are set during fetch_commits
    commits: PaginatedList[Commit] | None = None
    incremental_diff: Comparison | None = None

    def __post_init__(self):
        self.base_sha = GITHUB_CONTEXT.payload.pull_request.base.sha
        self.head_sha = GITHUB_CONTEXT.payload.pull_request.head.sha
        self.number = int(GITHUB_CONTEXT.payload.pull_request.number)
        self.target_branch_diff: Comparison = REPO.compare(self.base_sha, self.head_sha)

    def fetch_commits(self, highest_reviewed_commit_id: str) -> None:
        self.incremental_diff: Comparison = REPO.compare(
            highest_reviewed_commit_id,
            self.head_sha,
        )
        self.commits = self.incremental_diff.commits

    @property
    def last_commit(self) -> Commit:
        return self.commits[-1]


class PRDescription(BaseModel):
    description: str = (
        ""  # provided human description of the PR without AI generated content
    )
    title: str = ""
    # currently not used for prompt
    release_notes: str = ""

    def model_post_init(self, __context: Any) -> None:
        if GITHUB_CONTEXT.payload.pull_request.body is not None:
            body = GITHUB_CONTEXT.payload.pull_request.body
            self.description = self.get_description(description=body)
            self.release_notes = self.get_release_notes(description=body)

        self.title = GITHUB_CONTEXT.payload.pull_request.title

    def get_release_notes(self, description: str) -> str:
        # TODO not used right now
        release_notes = get_content_within_tags(
            description, TAGS.DESCRIPTION_START_TAG, TAGS.DESCRIPTION_END_TAG
        )
        return re.sub(r"(^|\n)> .*", "", release_notes)

    @property
    def user_ask_to_ignore(self) -> bool:
        return IGNORE_KEYWORD in self.description.lower()

    def update_description(self, pull_number: int, message: str):
        # add this response to the description field of the PR as release notes by looking
        # for the tag (marker)
        try:
            # get latest description from PR
            pr = REPO.get_pull(pull_number)
            body = pr.body if pr.body else ""
            self.description = self.get_description(body)

            message_clean = remove_content_within_tags(
                message, TAGS.DESCRIPTION_START_TAG, TAGS.DESCRIPTION_END_TAG
            )
            new_description = f"{self.description}\n{TAGS.DESCRIPTION_START_TAG}\n{message_clean}\n{TAGS.DESCRIPTION_END_TAG}"
            pr.edit(body=new_description)
        except Exception as e:
            warning(
                f"Failed to get PR: {e}, skipping adding release notes to description."
            )

    def get_description(self, description: str) -> str:
        return remove_content_within_tags(
            description, TAGS.DESCRIPTION_START_TAG, TAGS.DESCRIPTION_END_TAG
        )

    def update_description_with_release_notes(
        self,
        heavy_bot: Bot,
        prompts: Prompts,
        ai_summary: AiSummary,
        options: Options,
        pr_info: PRInfo,
    ) -> None:
        if options.disable_release_notes:
            return

        release_notes_response = heavy_bot.chat(
            prompts.render_summarize_release_notes(ai_summary)
        )
        if release_notes_response.message == "":
            print(
                f"release notes: nothing obtained from {options.heavy_model_name} model"
            )
        else:
            self.release_notes = (
                f"### Release notes by {BOT_NAME_NO_TAG}\n\n"
                + release_notes_response.message
            )
            try:
                self.update_description(pr_info.number, message=self.release_notes)
            except Exception as e:
                print(f"release notes: error from github: {str(e)}")


@dataclass
class ReviewedCommitIds:
    reviewed_commit_ids_block: str | None = None
    highest_reviewed_commit_id: str | None = None
    current_reviewed_commit_id: str | None = None

    @staticmethod
    def get_reviewed_commit_ids_block(comment_body: str) -> str:
        start = comment_body.find(TAGS.COMMIT_ID_START_TAG)
        end = comment_body.find(TAGS.COMMIT_ID_END_TAG)
        if start == -1 or end == -1:
            return ""
        return comment_body[start : end + len(TAGS.COMMIT_ID_END_TAG)]

    @staticmethod
    def get_highest_reviewed_commit_id(
        commit_ids: list[str], reviewed_commit_ids: list[str]
    ) -> str:
        for i in range(len(commit_ids) - 1, -1, -1):
            if commit_ids[i] in reviewed_commit_ids:
                return commit_ids[i]
        return ""

    @staticmethod
    def get_all_commit_ids(pr_info: PRInfo) -> list[str]:
        all_commits = []
        try:
            pull = REPO.get_pull(pr_info.number)
            # Get the commits from the pull request:
            commits = pull.get_commits()
            return [commit.sha for commit in commits]
        except Exception as e:
            print(f"Failed to list commits: {e}")

        return all_commits

    @staticmethod
    def get_reviewed_commit_ids(comment_body: str) -> list[str]:
        start = comment_body.find(TAGS.COMMIT_ID_START_TAG)
        end = comment_body.find(TAGS.COMMIT_ID_END_TAG)
        if start == -1 or end == -1:
            return []
        ids = comment_body[start + len(TAGS.COMMIT_ID_START_TAG) : end]
        return [
            _id.replace("-->", "").strip()
            for _id in ids.split("<!--")
            if _id.strip() != ""
        ]

    @classmethod
    def from_summarized_comment(cls, body: str, pr_info: PRInfo) -> ReviewedCommitIds:
        reviewed_commit_ids_block = cls.get_reviewed_commit_ids_block(body)

        if reviewed_commit_ids_block:
            highest_reviewed_commit_id = cls.get_highest_reviewed_commit_id(
                cls.get_all_commit_ids(pr_info),
                cls.get_reviewed_commit_ids(reviewed_commit_ids_block),
            )
        else:
            highest_reviewed_commit_id = ""

        if (
            not highest_reviewed_commit_id
            or highest_reviewed_commit_id == pr_info.head_sha
        ):
            # print(
            #     f"Will review from the base commit: {GITHUB_CONTEXT.payload.pull_request.base.sha}"
            # )
            highest_reviewed_commit_id = pr_info.base_sha

        return cls(
            reviewed_commit_ids_block, highest_reviewed_commit_id, pr_info.head_sha
        )

    def add_current_reviewed_commit_id(self, comment_body: str):
        start = comment_body.find(TAGS.COMMIT_ID_START_TAG)
        end = comment_body.find(TAGS.COMMIT_ID_END_TAG)

        if start == -1 or end == -1:
            return f"{comment_body}\n{TAGS.COMMIT_ID_START_TAG}\n<!-- {self.current_reviewed_commit_id} -->\n{TAGS.COMMIT_ID_END_TAG}"

        ids = comment_body[start + len(TAGS.COMMIT_ID_START_TAG) : end]
        return f"{comment_body[:start + len(TAGS.COMMIT_ID_START_TAG)]}{ids}<!-- {self.current_reviewed_commit_id} -->\n{comment_body[end:]}"
