from string import Template
from typing import Final, List

from github.File import File
from pydantic import BaseModel

from core.bot import AiResponse
from core.consts import (
    AVATAR_URL,
    BOT_NAME,
    BOT_NAME_NO_TAG,
    FEEDBACK_EMAIL,
    IGNORE_KEYWORD,
)
from core.schemas.files import FilteredFile
from core.schemas.inputs import Inputs
from core.templates.prompts import (
    COMMENT,
    REVIEW_FILE_DIFF,
    SUMMARIZE_CHANGESETS,
    SUMMARIZE_FILE_DIFF,
    SUMMARIZE_PREFIX,
    SUMMARIZE_SHORT,
    TRIAGE_FILE_DIFF,
)
from core.templates.tags import TAGS


class Prompts(BaseModel):
    summarize: str
    summarize_release_notes: str
    summarize_file_diff: Final[Template] = SUMMARIZE_FILE_DIFF
    triage_file_diff: Final[Template] = TRIAGE_FILE_DIFF
    summarize_changesets: Final[Template] = SUMMARIZE_CHANGESETS
    summarize_prefix: Final[Template] = SUMMARIZE_PREFIX
    summarize_short: Final[Template] = SUMMARIZE_SHORT
    review_file_diff: Final[Template] = REVIEW_FILE_DIFF
    comment: Final[Template] = COMMENT

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
        self, inputs: Inputs, review_simple_changes: bool
    ) -> str:
        prompt = self.summarize_file_diff
        if not review_simple_changes:
            prompt = self._safe_add_template(prompt, self.triage_file_diff)
        return inputs.render(prompt)

    def render_summarize_changesets(self, inputs: Inputs) -> str:
        return inputs.render(self.summarize_changesets)

    def render_summarize(self, inputs: Inputs) -> str:
        prompt = self._safe_add_template(self.summarize_prefix, self.summarize)
        return inputs.render(prompt)

    def render_summarize_short(self, inputs: Inputs) -> str:
        prompt = self._safe_add_template(self.summarize_prefix, self.summarize_short)
        return inputs.render(prompt)

    def render_summarize_release_notes(self, inputs: Inputs) -> str:
        prompt = self._safe_add_template(
            self.summarize_prefix, self.summarize_release_notes
        )
        return inputs.render(prompt)

    def render_comment(self, inputs: Inputs) -> str:
        return inputs.render(self.comment)

    def render_review_file_diff(self, inputs: Inputs) -> str:
        return inputs.render(self.review_file_diff)


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


class SummarizeComment:
    def __init__(
        self,
        summary_changes: AiResponse,
        inputs: Inputs,
        raw_summary_start_tag: TAGS = TAGS.RAW_SUMMARY_START_TAG,
        raw_summary_end_tag: TAGS = TAGS.RAW_SUMMARY_START_TAG,
        short_summary_start_tag: TAGS = TAGS.SHORT_SUMMARY_START_TAG,
        short_summary_end_tag: TAGS = TAGS.SHORT_SUMMARY_END_TAG,
        feedback_email: str = FEEDBACK_EMAIL,
    ):
        self.summary_changes = summary_changes
        self.inputs = inputs
        self.raw_summary_start_tag = raw_summary_start_tag
        self.raw_summary_end_tag = raw_summary_end_tag
        self.short_summary_start_tag = short_summary_start_tag
        self.short_summary_end_tag = short_summary_end_tag
        self.feedback_email = feedback_email
        self._reviewed_commit_id: str = ""

    def render(self) -> str:
        base_message = (
            f"{self.summary_changes.message}\n"
            f"{self.raw_summary_start_tag}\n{self.inputs.raw_summary}\n{self.raw_summary_end_tag}\n"
            f"{self.short_summary_start_tag}\n{self.inputs.short_summary}\n{self.short_summary_end_tag}\n"
            f"\n---\n\n<details>\n"
            f"<summary>Feedback us to {self.feedback_email} </summary>\n\n"
            f"If you like this project, please feedback us. We are happy to hear from you.\n\n"
            f"Any feedback is welcome, including feature requests, bug reports, and general comments."
            f"\n\n</details>\n"
        )
        if self.reviewed_commit_id:
            base_message = f"{base_message}\n{self.reviewed_commit_id}"

        return base_message

    @property
    def reviewed_commit_id(self):
        return self._reviewed_commit_id

    @reviewed_commit_id.setter
    def reviewed_commit_id(self, value: str):
        self._reviewed_commit_id = value

    def __str__(self):
        return self.render()
