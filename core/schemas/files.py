from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, List, Tuple

from box import Box
from github.File import File
from pydantic import BaseModel

from core.bots.bot import Bot
from core.github import GITHUB_CONTEXT, REPO
from core.tokenizer import get_token_count

if TYPE_CHECKING:  # a hack to avoid circular imports, when we ONLY want to type hint
    # https://peps.python.org/pep-0563/#runtime-annotation-resolution-and-type-checking
    from core.commenter import GithubCommentManager
    from core.schemas.prompts import Prompts
    from core.schemas.comment_chains import CommentChains

from core.schemas.options import Options
from core.schemas.patch import (
    Patch,
    Patches,
    parse_patch,
    patch_start_end_line,
    split_patch,
)
from core.templates.tags import TAGS


class BaseFile(BaseModel):
    filename: str
    file_content: str

    @classmethod
    def get_base_file(cls, filename: str, ref: str) -> BaseFile:
        file_content = ""
        try:
            contents = REPO.get_contents(filename, ref=ref)
            file_content = contents.decoded_content.decode() if contents else ""
        except Exception as e:
            print(
                f"Failed to get file contents: {str(e)}. This is OK if it's a new file: {filename}"
            )

        return cls(filename=filename, file_content=file_content)

    @property
    def content_tokens(self) -> int:
        return get_token_count(self.file_content)


class FilteredFile(BaseModel):
    filename: str
    file_content: str
    file_diff: str
    patches: Patches

    def compute_patch_associated_comment_chains(
        self, commenter: GithubCommentManager
    ) -> list[Tuple[Patch, CommentChains | None]]:
        patch_associated_comment_chains = []
        for patch in self.patches.items:
            comment_chains = None
            try:
                comment_chains = commenter.get_comment_chains_within_range(
                    GITHUB_CONTEXT.payload.pull_request.number,
                    path=self.filename,
                    start_line=patch.start_line,
                    end_line=patch.end_line,
                    tag=TAGS.COMMENT_REPLY_TAG,
                )
                if comment_chains:
                    print(f"Found comment chains: {comment_chains} for {self.filename}")

            except Exception as e:
                print(
                    f"Failed to get comment chains: {str(e)}, skipping. backtrace: {traceback.format_exc()}"
                )

            patch_associated_comment_chains.append((patch, comment_chains))

            return patch_associated_comment_chains

    @classmethod
    def get_file_contents(cls, file: File) -> str:
        try:
            contents = REPO.get_contents(
                file.filename, ref=GITHUB_CONTEXT.payload.pull_request.base.sha
            )
            return contents.decoded_content.decode() if contents else ""
        except Exception as e:
            print(
                f"Failed to get file contents: {str(e)}. This is OK if it's a new file: {file.filename}"
            )
            return ""

    @classmethod
    def parse_patch(cls, patch: str) -> Patch | None:
        patch_lines = patch_start_end_line(patch)
        if not patch_lines:
            return None
        patch_lines = Box(patch_lines)
        # TODO make better typing not Box
        hunks = Box(parse_patch(patch, patch_lines))
        if not hunks:
            return None
        return Patch(
            start_line=patch_lines.new_hunk.start_line,
            end_line=patch_lines.new_hunk.end_line,
            patch_str=f"\n---new_hunk---\n```\n{hunks.new_hunk}\n```\n"
            f"\n---old_hunk---\n```\n{hunks.old_hunk}\n```\n",
        )

    @classmethod
    def get_filtered_files(
        cls, files: List[File], options: Options
    ) -> List[FilteredFile]:
        """Filter files based on options and extract relevant information."""
        filter_selected_files = [
            file for file in files if options.check_path(file.filename)
        ]
        if not filter_selected_files:
            print("Skipped: filter_selected_files is None")
            return []

        filtered_files = []
        for file in filter_selected_files:
            file_content = cls.get_file_contents(file)
            patches = [
                parsed_patch
                for patch in split_patch(file.patch)
                if (parsed_patch := cls.parse_patch(patch))
            ]
            if patches:
                filtered_files.append(
                    cls(
                        filename=file.filename,
                        file_content=file_content,
                        file_diff=file.patch if file.patch else "",
                        patches=Patches(items=patches),
                    )
                )
        return filtered_files


class FileSummary(BaseModel):
    filename: str
    summary: str
    needs_review: bool


class AiSummary(BaseModel):
    raw_summary: str
    short_summary: str
    changeset_summary: str

    @property
    def short_summary_tokens(self) -> int:
        return get_token_count(self.short_summary)

    def generate_new_raw_summary(
        self,
        heavy_bot: Bot,
        prompts: Prompts,
        summaries: List[FileSummary],
        options: Options,
        batch_size: int = 10,
    ) -> None:

        if not summaries:
            return

        for i in range(0, len(summaries), batch_size):
            summaries_batch = summaries[i : i + batch_size]
            batch_summary = "\n---\n".join(
                f"{file_summary.filename}: {file_summary.summary}"
                for file_summary in summaries_batch
            )
            # The raw summary, could be non-empty from previously generated summary comment
            # In this way we pass the previous summary to the model in the first batch
            self.raw_summary += f"\n---\n{batch_summary}"
            # TODO need to define an AI function here, which will give the unified summary
            summarize_resp = heavy_bot.chat(prompts.render_summarize_raw(self))
            if not summarize_resp.message:
                print(
                    f"summarize: nothing obtained from {options.heavy_model_name} model"
                )
            else:
                self.raw_summary = summarize_resp.message

    def generate_new_short_summary(self, heavy_bot: Bot, prompts: Prompts) -> None:
        # TODO check if we don't have raw empty summary in this way we should skip
        self.short_summary = heavy_bot.chat(
            prompts.render_summarize_short(self)
        ).message

    def generate_new_changeset_summary(self, heavy_bot: Bot, prompts: Prompts) -> None:
        self.changeset_summary = heavy_bot.chat(
            prompts.render_summarize_changeset(self)
        ).message
