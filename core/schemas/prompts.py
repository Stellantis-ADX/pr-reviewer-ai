from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Final, List, Optional

from github.File import File
from github.IssueComment import IssueComment
from pydantic import BaseModel

from core.commenter import GithubCommentManager
from core.consts import (
    AVATAR_URL,
    BOT_NAME,
    BOT_NAME_NO_TAG,
    FEEDBACK_EMAIL,
    IGNORE_KEYWORD,
)
from core.github import GITHUB_CONTEXT
from core.schemas.comment_reply import CommentReply
from core.schemas.files import AiSummary, FilteredFile
from core.schemas.pr_common import PRDescription, ReviewedCommitIds
from core.templates.prompts import (
    COMMENT,
    REVIEW_FILE_DIFF,
    SUMMARIZE_CHANGESETS,
    SUMMARIZE_FILE_DIFF,
    SUMMARIZE_PREFIX,
    SUMMARIZE_SHORT,
    TRIAGE_FILE_DIFF,
)
from core.templates.tags import TAGS, get_content_within_tags


class Prompts(BaseModel):
    summarize: str  # prompt getting from the action.yml
    summarize_release_notes: str  # prompt getting from the action.yml
    summarize_file_diff: Final[Template] = SUMMARIZE_FILE_DIFF
    triage_file_diff: Final[Template] = TRIAGE_FILE_DIFF
    summarize_changesets: Final[Template] = SUMMARIZE_CHANGESETS
    summarize_prefix: Final[Template] = SUMMARIZE_PREFIX
    summarize_short: Final[Template] = SUMMARIZE_SHORT
    review_file_diff: Final[Template] = REVIEW_FILE_DIFF
    comment: Final[Template] = COMMENT

    def _render(self, content: str | Template, replacements: dict) -> str:
        if not content:
            return ""
        return content.safe_substitute(replacements)

    def ensure_template(self, maybe_str: str | Template) -> Template:
        if isinstance(maybe_str, Template):
            return maybe_str
        else:
            return Template(str(maybe_str))

    def _safe_add_template(
        self, template_1: str | Template, template_2: str | Template
    ) -> Template:
        return Template(
            self.ensure_template(template_1).template
            + self.ensure_template(template_2).template
        )

    def render_summarize_file_diff(
        self, file: FilteredFile, review_simple_changes: bool
    ) -> str:
        prompt = self.summarize_file_diff
        if not review_simple_changes:
            prompt = self._safe_add_template(prompt, self.triage_file_diff)

        return self._render(prompt, replacements=file.model_dump())

    def render_summarize_raw(self, ai_summary: AiSummary) -> str:
        return self._render(
            self.summarize_changesets, replacements=ai_summary.model_dump()
        )

    def render_summarize_changeset(self, ai_summary: AiSummary) -> str:
        prompt = self._safe_add_template(self.summarize_prefix, self.summarize)
        return self._render(prompt, replacements=ai_summary.model_dump())

    def render_summarize_short(self, ai_summary: AiSummary) -> str:
        prompt = self._safe_add_template(self.summarize_prefix, self.summarize_short)
        return self._render(prompt, replacements=ai_summary.model_dump())

    def render_summarize_release_notes(self, ai_summary: AiSummary) -> str:
        prompt = self._safe_add_template(
            self.summarize_prefix, self.summarize_release_notes
        )
        return self._render(prompt, replacements=ai_summary.model_dump())

    def render_comment(
        self,
        comment_reply: CommentReply | None,
        pr_description: PRDescription | None,
        ai_summary: AiSummary | None,
        exclude: str | None = None,
    ) -> str:
        replacements = {}
        if comment_reply is not None:
            replacements = {**replacements, **comment_reply.model_dump()}
        if comment_reply.file is not None:
            exclude = {exclude} if exclude is not None else set()
            replacements = {
                **replacements,
                **comment_reply.file.model_dump(exclude=exclude),
            }
        if ai_summary is not None:
            replacements = {**replacements, **ai_summary.model_dump()}
        if pr_description is not None:
            replacements = {**replacements, **pr_description.model_dump()}

        return self._render(self.comment, replacements=replacements)

    def render_review_file_diff(
        self, file: FilteredFile, ai_summary: AiSummary, pr_description: PRDescription
    ) -> str:
        replacements = {
            **file.model_dump(),
            **file.patches.model_dump(by_alias=True),
            **ai_summary.model_dump(),
            **pr_description.model_dump(),
        }
        return self._render(self.review_file_diff, replacements=replacements)


class StatusMessagePrompt(BaseModel):
    commits_summary: Template = Template(
        "<details>\n<summary>Commits</summary>\nFiles that changed from the base of the PR and between $highest_reviewed_commit_id and $head_sha commits.\n</details>\n"
    )
    files_selected: Template = Template(
        "<details>\n<summary>Files selected ($files_selected_count)</summary>\n\n* $files_selected_list\n</details>\n"
    )
    files_ignored: Template = Template(
        "<details>\n<summary>Files ignored due to filter ($files_ignored_count)</summary>\n\n* $files_ignored_list\n\n</details>\n"
    )
    skipped_files: Template = Template(
        "<details>\n<summary>Files not processed due to max files limit ($count)</summary>\n\n* $files\n\n</details>\n"
    )
    summaries_failed: Template = Template(
        "<details>\n<summary>Files not summarized due to errors ($count)</summary>\n\n* $files\n\n</details>\n"
    )
    reviews_failed: Template = Template(
        "<details>\n<summary>Files not reviewed due to errors ($count)</summary>\n\n* $files\n\n</details>\n"
    )

    reviews_skipped: Template = Template(
        "<details>\n<summary>Files skipped from review due to trivial changes ($count)</summary>\n\n* $files\n\n</details>\n"
    )
    review_comments_generated: Template = Template(
        "\n<details>\n<summary>Review comments generated ($total_count)</summary>\n\n* "
        "Review: $review_count\n* LGTM: $lgtm_count\n\n</details>\n"
    )

    tips: Template = Template(
        "\n---\n\n<details>\n<summary>Tips</summary>\n\n"
        '### Chat with <img src="$avatar_url" '
        'alt="Image description" width="20" height="20">  $bot_name_no_tag Bot (`$bot_name`)\n- '
        "Reply on review comments left by this bot to ask follow-up questions. "
        "A review comment is a comment on a diff or a file.\n- "
        "Invite the bot into a review comment chain by tagging `$bot_name` in a reply.\n\n### "
        "Code suggestions\n- The bot may make code suggestions, but please review them carefully before "
        "committing since the line number ranges may be misaligned.\n- "
        "You can edit the comment made by the bot and manually tweak the suggestion"
        " if it is slightly off.\n\n### Pausing incremental reviews\n- "
        "Add `$ignore_keyword` anywhere in the PR description to pause further reviews"
        " from the bot.\n\n</details>\n"
    )
    summary_message: str = ""

    class Config:
        arbitrary_types_allowed = True

    def render_commits_summary(
        self, highest_reviewed_commit_id: str, head_sha: str
    ) -> str:
        self.summary_message += self.commits_summary.substitute(
            highest_reviewed_commit_id=highest_reviewed_commit_id, head_sha=head_sha
        )
        return self.summary_message

    def render_files_selected(self, filtered_files: List[FilteredFile]) -> str:
        files_selected_list = "\n* ".join(
            [f"{file.filename} ({len(file.patches)})" for file in filtered_files]
        )
        self.summary_message += self.files_selected.substitute(
            files_selected_count=len(filtered_files),
            files_selected_list=files_selected_list,
        )
        return self.summary_message

    def render_files_ignored(self, filter_ignored_files: List[File]) -> str:
        files_ignored_list = "\n* ".join(
            [file.filename for file in filter_ignored_files]
        )
        self.summary_message += self.files_ignored.substitute(
            files_ignored_count=len(filter_ignored_files),
            files_ignored_list=files_ignored_list,
        )
        return self.summary_message

    def render_skipped_files(self, skipped_files: List[str]) -> str:
        if len(skipped_files) > 0:
            self.summary_message += "\n" + self.skipped_files.substitute(
                count=len(skipped_files), files="\n* ".join(skipped_files)
            )
        return self.summary_message

    def render_summaries_failed(self, summaries_failed: List[str]) -> str:
        if len(summaries_failed) > 0:
            self.summary_message += "\n" + self.summaries_failed.substitute(
                count=len(summaries_failed), files="\n* ".join(summaries_failed)
            )
        return self.summary_message

    def render_reviews_failed(self, reviews_failed: List[str]) -> str:
        if len(reviews_failed) > 0:
            self.summary_message += "\n" + self.reviews_failed.substitute(
                count=len(reviews_failed), files="\n* ".join(reviews_failed)
            )
        return self.summary_message

    def render_reviews_skipped(self, reviews_skipped: List[str]) -> str:
        if len(reviews_skipped) > 0:
            self.summary_message += "\n" + self.reviews_skipped.substitute(
                count=len(reviews_skipped), files="\n* ".join(reviews_skipped)
            )
        return self.summary_message

    def render_review_comments_generated(
        self, review_count: int, lgtm_count: int
    ) -> str:
        self.summary_message += self.review_comments_generated.substitute(
            total_count=review_count + lgtm_count,
            review_count=review_count,
            lgtm_count=lgtm_count,
        )
        return self.summary_message

    def render_tips(self) -> str:
        self.summary_message += self.tips.substitute(
            avatar_url=AVATAR_URL,
            bot_name_no_tag=BOT_NAME_NO_TAG,
            bot_name=BOT_NAME,
            ignore_keyword=IGNORE_KEYWORD,
        )
        return self.summary_message

    def __str__(self):
        return self.summary_message

    def init(
        self,
        highest_reviewed_commit_id: str,
        selected_files: List[FilteredFile],
        ignored_files: List[File],
    ) -> StatusMessagePrompt:
        # TODO do it better, need to move out template strings from the class
        self.render_commits_summary(
            highest_reviewed_commit_id,
            GITHUB_CONTEXT.payload.pull_request.head.sha,
        )
        self.render_files_selected(selected_files)
        self.render_files_ignored(ignored_files)
        return self

    def in_progress(self, comment_body: str) -> str:
        start = comment_body.find(TAGS.IN_PROGRESS_START_TAG)
        end = comment_body.find(TAGS.IN_PROGRESS_END_TAG)
        # add to the beginning of the comment body if the marker doesn't exist
        # otherwise do nothing
        if start == -1 or end == -1:
            return (
                f"{TAGS.IN_PROGRESS_START_TAG}\n\n"
                f"Currently reviewing new changes in this PR..."
                f"\n\n{self.summary_message}\n\n{TAGS.IN_PROGRESS_END_TAG}\n\n---\n\n"
                f"{comment_body}"
            )
        return comment_body

    def finished_review(
        self,
        skipped_files: List[str],
        summaries_failed: List[str],
        reviews_failed: List[str],
        reviews_skipped: List[str],
        review_count: int,
        lgtm_count: int,
    ) -> str:
        # TODO probably it's not a good idea to change state of the object here
        # But right now it's ok
        self.render_skipped_files(skipped_files)
        self.render_summaries_failed(summaries_failed)
        self.render_reviews_failed(reviews_failed)
        self.render_reviews_skipped(reviews_skipped)
        self.render_review_comments_generated(review_count, lgtm_count)
        self.render_tips()
        return self.summary_message


@dataclass
class ExistingSummarizedComment:
    # Class represents existing *Walkthrough* summary comment
    # With underlayed raw summary, short summary and reviewed commit ids
    commenter: GithubCommentManager
    ai_summary: Optional[AiSummary] = None
    reviewed_commits_ids: Optional[ReviewedCommitIds] = None
    status_message: Optional[str] = None

    def __post_init__(self):
        self.ai_summary = AiSummary(
            raw_summary=self.get_raw_summary(self.body),
            short_summary=self.get_short_summary(self.body),
            changeset_summary="",
        )

    @property
    def comment(self) -> Optional[IssueComment]:
        return self.commenter.find_issue_comment_with_tag(
            TAGS.SUMMARIZE_TAG, pr_number=GITHUB_CONTEXT.payload.pull_request.number
        )

    @property
    def body(self) -> str:
        if self.comment is not None:
            return self.comment.body
        return ""

    def get_raw_summary(self, summary: str) -> str:
        return get_content_within_tags(
            summary, TAGS.RAW_SUMMARY_START_TAG, TAGS.RAW_SUMMARY_END_TAG
        )

    def get_short_summary(self, summary: str) -> str:
        return get_content_within_tags(
            summary, TAGS.SHORT_SUMMARY_START_TAG, TAGS.SHORT_SUMMARY_END_TAG
        )

    def update_reviewed_commit_ids(
        self, reviewed_commit_ids: ReviewedCommitIds
    ) -> None:
        self.reviewed_commits_ids = reviewed_commit_ids

    def update_ai_summary(self, ai_summary: AiSummary) -> None:
        self.ai_summary = ai_summary

    def status_message_in_progress(
        self, filtered_files: list[FilteredFile], ignored_files: list[File]
    ) -> str:
        init_msg = StatusMessagePrompt().init(
            self.reviewed_commits_ids.highest_reviewed_commit_id,
            filtered_files,
            ignored_files,
        )
        self.status_message = init_msg.in_progress(comment_body=self.body)
        return self.status_message

    def render(self, disable_review: bool) -> str:
        base_message = (
            f"{self.ai_summary.changeset_summary}\n"
            f"{TAGS.RAW_SUMMARY_START_TAG}\n{self.ai_summary.raw_summary}\n{TAGS.RAW_SUMMARY_END_TAG}\n"
            f"{TAGS.SHORT_SUMMARY_START_TAG}\n{self.ai_summary.short_summary}\n{TAGS.SHORT_SUMMARY_END_TAG}\n"
            f"\n---\n\n<details>\n"
            f"<summary>Feedback us to {FEEDBACK_EMAIL} </summary>\n\n"
            f"If you like this project, please feedback us. We are happy to hear from you.\n\n"
            f"Any feedback is welcome, including feature requests, bug reports, and general comments."
            f"\n\n</details>\n"
        )
        if not disable_review:
            base_message = f"{base_message}\n{self.reviewed_commits_ids.current_reviewed_commit_id}"

        return base_message
