from __future__ import annotations

from string import Template

from github_action_utils import notice as info


class Inputs:
    def __init__(
        self,
        system_message: str = "",
        title: str = "no title provided",
        description: str = "no description provided",
        raw_summary: str = "",
        short_summary: str = "",
        filename: str = "",
        file_content: str = "file contents cannot be provided",
        file_diff: str = "file diff cannot be provided",
        patches: str = "",
        diff: str = "no diff",
        comment_chain: str = "no other comments on this patch",
        comment: str = "no comment provided",
    ):
        self.system_message = system_message
        self.title = title
        self.description = description
        self.raw_summary = raw_summary
        self.short_summary = short_summary
        self.filename = filename
        self.file_content = file_content
        self.file_diff = file_diff
        self.patches = patches
        self.diff = diff
        self.comment_chain = comment_chain
        self.comment = comment

    def clone(self) -> Inputs:
        return Inputs(
            self.system_message,
            self.title,
            self.description,
            self.raw_summary,
            self.short_summary,
            self.filename,
            self.file_content,
            self.file_diff,
            self.patches,
            self.diff,
            self.comment_chain,
            self.comment,
        )

    def render(self, content: Template) -> str:
        if not content:
            return ""
        replacements = {
            "system_message": self.system_message,
            "title": self.title,
            "description": self.description,
            "raw_summary": self.raw_summary,
            "short_summary": self.short_summary,
            "filename": self.filename,
            "file_content": self.file_content,
            "file_diff": self.file_diff,
            "patches": self.patches,
            "diff": self.diff,
            "comment_chain": self.comment_chain,
            "comment": self.comment,
        }
        return content.safe_substitute(replacements)

    def print(self) -> None:
        info(f"system_message: {self.system_message}")
        info(f"title: {self.title}")
        info(f"description: {self.description}")
        info(f"raw_summary: {self.raw_summary}")
        info(f"short_summary: {self.short_summary}")
        info(f"filename: {self.filename}")
        info(f"file_content: {self.file_content}")
        info(f"file_diff: {self.file_diff}")
        info(f"patches: {self.patches}")
        info(f"diff: {self.diff}")
        info(f"comment_chain: {self.comment_chain}")
        info(f"comment: {self.comment}")
