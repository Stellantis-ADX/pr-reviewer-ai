from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from box import Box
from github.PullRequestComment import PullRequestComment
from github_action_utils import warning

from core.commenter import GithubCommentManager
from core.consts import BOT_NAME
from core.github import GITHUB_CONTEXT
from core.schemas.comment_chains import CommentChain
from core.schemas.files import BaseFile
from core.schemas.pr_common import PRInfo
from core.templates.tags import TAGS


@dataclass
class CommentReply:
    body: str | None = None
    diff: str | None = None
    comment_chain: CommentChain | None = None
    file: BaseFile | None = None
    top_level_comment: PullRequestComment | None = None
    original_commit_id: str | None = None

    def model_dump(self) -> dict[str, Any]:

        return {
            "comment": self.body,
            "diff": self.diff,
            "comment_chain": self.comment_chain.comment,
        }

    def init_with(
        self, comment: Box, comment_manager: GithubCommentManager, pr_info: PRInfo
    ) -> CommentReply:
        self.body = f"{comment.user.login}: {comment.body}"
        self.original_commit_id = comment.original_commit_id

        self.file = BaseFile.get_base_file(comment.path, ref=comment.original_commit_id)

        self.diff = self.git_diff_from_discussion(
            diff=comment.diff_hunk,
            start_line=comment.start_line,
            end_line=comment.original_line,
            html_url=comment.html_url,
        )

        if not self.diff:
            self.diff = self._diff_mentioned_file_in_comment_base_head(pr_info=pr_info)

        chain_body, self.top_level_comment = comment_manager.get_comment_chain(
            pr_info.number, comment
        )
        self.comment_chain = CommentChain(
            start_line=comment.start_line,
            end_line=comment.original_line,
            comment=chain_body,
            top_level_comment_id=self.top_level_comment.id,
        )

        return self

    @staticmethod
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

    @property
    def is_top_level_comment_found(self) -> bool:
        if self.top_level_comment is None:
            print("Failed to find the top-level comment to reply to")
            return False

        return True

    @property
    def is_bot_mentioned_in_comment_chain(self) -> bool:
        if (
            TAGS.COMMENT_TAG in self.comment_chain.comment
            or TAGS.COMMENT_REPLY_TAG in self.comment_chain.comment
            or BOT_NAME in self.body.lower()
        ):
            return True

        warning(
            f"Skipped: {GITHUB_CONTEXT.event_name} event:"
            f" comment does not contain {TAGS.COMMENT_TAG} or {TAGS.COMMENT_REPLY_TAG}"
            f" or {BOT_NAME} in the body"
        )

        return False

    def _diff_mentioned_file_in_comment_base_head(self, pr_info: PRInfo) -> str:
        # Diff between the base and head commits of the pull request for the file
        file_diff = ""
        try:
            files = pr_info.target_branch_diff.files
            if files is not None:
                file = next(
                    (f for f in files if f.filename == self.file.filename), None
                )
                if file is not None and file.patch is not None:
                    file_diff = file.patch
        except Exception as error:
            warning(f"Failed to get file diff: {error}, skipping.")
        return file_diff
