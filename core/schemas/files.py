from __future__ import annotations

from typing import List

from box import Box
from github.Comparison import Comparison
from github.File import File
from pydantic import BaseModel

from core.github import REPO, github_context
from core.schemas.options import Options
from core.schemas.patch import Patch, parse_patch, patch_start_end_line, split_patch


class FilteredFile(BaseModel):
    filename: str
    file_content: str
    file_diff: str
    patches: list[Patch]

    @classmethod
    def get_file_contents(cls, file: File) -> str:
        try:
            contents = REPO.get_contents(
                file.filename, ref=github_context.payload.pull_request.base.sha
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
        cls, files: List[File], options: Options, incremental_diff: Comparison
    ) -> List[FilteredFile]:
        """Filter files based on options and extract relevant information."""
        filter_selected_files = [
            file for file in files if options.check_path(file.filename)
        ]
        if not filter_selected_files:
            print("Skipped: filter_selected_files is None")
            return []

        commits = incremental_diff.commits
        if not commits.totalCount:
            print("Skipped: commits is None")
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
                        patches=patches,
                    )
                )
        return filtered_files


class FileSummary(BaseModel):
    filename: str
    summary: str
    needs_review: bool
