from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from github.File import File
from pydantic import BaseModel

from core.bots.bot import AiResponse
from core.schemas.files import FilteredFile
from core.schemas.options import Options
from core.schemas.prompts import StatusMessagePrompt
from core.templates.tags import TAGS
from core.utils import sanitize_response


class Review(BaseModel):
    path: str
    start_line: int
    end_line: int
    comment: str = ""

    def __str__(self) -> str:
        lines = "\n".join([f"  {line}" for line in self.comment.split("\n")])
        return (
            f"path: {self.path}\n"
            f"start_line: {self.start_line}, end_line: {self.end_line}\n"
            f"comment: {lines}"
        )

    def generate_comment_data(self) -> dict[str, Any]:
        comment_data = {"path": self.path, "body": self.comment, "line": self.end_line}

        if self.start_line != self.end_line:
            comment_data["start_line"] = self.start_line
            comment_data["start_side"] = "RIGHT"

        return comment_data

    def add_greeting(self) -> None:
        self.comment = (
            f"{TAGS.COMMENT_GREETING}\n\n{self.comment}\n\n{TAGS.COMMENT_TAG}"
        )


@dataclass
class ReviewState:
    current_start_line: int | None = None
    current_end_line: int | None = None
    current_comment: str | None = ""

    def reset(self) -> None:
        self.current_start_line = None
        self.current_end_line = None
        self.current_comment = ""

    def accumulate_comment(self, line: str) -> None:
        if self.current_start_line is not None and self.current_end_line is not None:
            self.current_comment += f"{line}\n"


@dataclass
class ReviewSummary:
    buffer: list[Review] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    lgtm: list[int] = field(default_factory=list)
    done: list[int] = field(default_factory=list)

    def get_status_message_finished_review(
        self,
        highest_reviewed_commit_id: str,
        filtered_files: list[FilteredFile],
        ignored_files: list[File],
        skipped_files: list[str],
        summaries_failed: list[str],
    ) -> str:
        init_msg = StatusMessagePrompt().init(
            highest_reviewed_commit_id,
            filtered_files,
            ignored_files,
        )
        return init_msg.finished_review(
            skipped_files=skipped_files,
            summaries_failed=summaries_failed,
            reviews_failed=self.failed,
            reviews_skipped=self.skipped,
            review_count=self.lgtm_count,
            lgtm_count=self.done_count,
        )

    @property
    def lgtm_count(self) -> int:
        return sum(self.lgtm)

    @property
    def done_count(self) -> int:
        return sum(self.done)

    def add_review_to_buffer(self, review: Review | None):
        if review is not None:
            self.done.append(1)
            review.add_greeting()
            self.buffer.append(review)

    def filter_lgtm_reviews(self, options: Options):
        lgtm_reviews = [
            review
            for review in self.buffer
            if options.review_comment_lgtm
            and ("LGTM" in review.comment or "looks good to me" in review.comment)
        ]
        lgtm_count = len(lgtm_reviews)
        self.lgtm.extend([1] * lgtm_count)
        self.buffer = [review for review in self.buffer if review not in lgtm_reviews]
        self.done = [1] * (len(self.done) - lgtm_count)

    def parse_ai_review(
        self, response: AiResponse, file: FilteredFile, debug: bool = False
    ) -> None:
        response = sanitize_response(response.message.strip())
        lines = response.split("\n")
        # Expected format:
        # 1-10:
        # 5-15:
        # \n20-30:
        # \t100-200:
        line_number_range_regex = r"(?:^|\s)(\d+)-(\d+):\s*$"
        comment_separator = "---"

        state = ReviewState()

        for line in lines:
            if self.is_line_number_range(line, line_number_range_regex):
                self.process_line_number_range(
                    line=line, file=file, state=state, debug=debug
                )
            elif self.is_comment_separator(line, comment_separator):
                self.process_comment_separator(file=file, state=state, debug=debug)
            else:
                state.accumulate_comment(line)

        self.finalize_reviews(file, state, debug)

    def is_line_number_range(self, line: str, regex: str) -> bool:
        return bool(re.search(regex, line))

    def is_comment_separator(self, line: str, separator: str) -> bool:
        return line.strip() == separator

    def process_line_number_range(
        self, line: str, file: FilteredFile, state: ReviewState, debug: bool
    ):
        review = self.generate_review_wrt_patches_overlap(
            file,
            state.current_start_line,
            state.current_end_line,
            state.current_comment,
            debug,
        )
        self.add_review_to_buffer(review)

        match = re.search(r"(?:^|\s)(\d+)-(\d+):\s*$", line)
        state.current_start_line = int(match.group(1))
        state.current_end_line = int(match.group(2))
        state.current_comment = ""
        if debug:
            print(
                f"Found line number range: {state.current_start_line}-{state.current_end_line}"
            )

    def process_comment_separator(
        self, file: FilteredFile, state: ReviewState, debug: bool
    ):

        review = self.generate_review_wrt_patches_overlap(
            file,
            state.current_start_line,
            state.current_end_line,
            state.current_comment,
            debug,
        )
        self.add_review_to_buffer(review)

        state.reset()

        if debug:
            print("Found comment separator")

    def finalize_reviews(self, file: FilteredFile, state: ReviewState, debug: bool):
        review = self.generate_review_wrt_patches_overlap(
            file,
            state.current_start_line,
            state.current_end_line,
            state.current_comment,
            debug,
        )

        self.add_review_to_buffer(review)

    def generate_review_wrt_patches_overlap(
        self,
        file: FilteredFile,
        current_start_line: int | None,
        current_end_line: int | None,
        current_comment: str,
        debug: bool = False,
    ) -> Review | None:

        review = None

        if current_start_line is not None and current_end_line is not None:
            review = Review(
                path=file.filename,
                start_line=current_start_line,
                end_line=current_end_line,
                comment=current_comment,
            )

            best_patch = None
            max_intersection = 0

            for patch in file.patches:
                intersection_length = max(
                    0,
                    min(review.end_line, patch.end_line)
                    - max(review.start_line, patch.start_line)
                    + 1,
                )

                if intersection_length > max_intersection:
                    max_intersection = intersection_length
                    best_patch = patch

                    if intersection_length == review.end_line - review.start_line + 1:
                        break

            if best_patch:
                if max_intersection < review.end_line - review.start_line + 1:
                    review.comment = (
                        f"> Note: This review was outside of the patch, so it was mapped to the patch with the greatest overlap. "
                        f"Original lines [{review.start_line}-{review.end_line}]\n\n{review.comment}"
                    )
                    review.start_line = best_patch.start_line
                    review.end_line = best_patch.end_line
            else:
                review.comment = (
                    f"> Note: This review was outside of the patch, but no patch was found that overlapped with it. "
                    f"Original lines [{review.start_line}-{review.end_line}]\n\n{review.comment}"
                )
                review.start_line = file.patches[0].start_line
                review.end_line = file.patches[0].end_line

            if debug:
                print(
                    f"Stored comment for line range {current_start_line}-{current_end_line}: {current_comment.strip()}"
                )

        return review
