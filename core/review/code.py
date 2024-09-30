from __future__ import annotations

import concurrent.futures
import re
import traceback
from typing import List, Optional, Tuple

from github import IssueComment
from github.Commit import Commit
from github.Comparison import Comparison
from github.File import File
from github.PaginatedList import PaginatedList

from core.bot import AiResponse, Bot
from core.commenter import Commenter, CommentMode
from core.consts import AVATAR_URL, BOT_NAME, BOT_NAME_NO_TAG, IGNORE_KEYWORD
from core.github import REPO, github_context
from core.schemas.common import Review
from core.schemas.files import FileSummary, FilteredFile, Patch
from core.schemas.inputs import Inputs
from core.schemas.options import Options
from core.schemas.prompts import Prompts, StatusMessagePrompt, SummarizeComment
from core.templates.tags import SUMMARIZE_TAG, TAGS
from core.tokenizer import get_token_count


def do_summary(
    filename: str,
    file_diff: str,
    options: Options,
    prompts: Prompts,
    inputs: Inputs,
    light_bot: Bot,
    summaries_failed: List[str],
) -> Optional[FileSummary]:
    print(f"summarize: {filename}")
    ins = inputs.clone()
    if len(file_diff) == 0:
        print(f"summarize: file_diff is empty, skip {filename}")
        summaries_failed.append(f"{filename} (empty diff)")
        return None

    ins.filename = filename
    ins.file_diff = file_diff

    summarize_prompt = prompts.render_summarize_file_diff(
        ins, options.review_simple_changes
    )
    tokens = get_token_count(summarize_prompt)

    print("DEBUG tokens", tokens)
    print("DEBUG options.light_token_limits", options.light_token_limits)

    if tokens > options.light_token_limits.request_tokens:
        print(f"summarize: diff tokens exceeds limit, skip {filename}")
        summaries_failed.append(f"{filename} (diff tokens exceeds limit)")
        return None

    try:
        summarize_resp = light_bot.chat(summarize_prompt, {})

        if summarize_resp.message == "":
            print(f"summarize: nothing obtained from {options.light_model_name} model")
            summaries_failed.append(
                f"{filename} (nothing obtained from {options.light_model_name} model)"
            )
            return None
        else:
            if not options.review_simple_changes:
                triage_regex = r"\[TRIAGE\]:\s*(NEEDS_REVIEW|APPROVED)"
                triage_match = re.search(triage_regex, summarize_resp.message)

                if triage_match is not None:
                    triage = triage_match.group(1)
                    needs_review = triage == "NEEDS_REVIEW"
                    summary = re.sub(triage_regex, "", summarize_resp.message).strip()
                    print(f"filename: {filename}, triage: {triage}")
                    return FileSummary(
                        filename=filename, summary=summary, needs_review=needs_review
                    )

            return FileSummary(
                filename=filename, summary=summarize_resp.message, needs_review=True
            )
    except Exception as e:
        print(f"summarize: error from {options.light_model_name}: {str(e)}")
        summaries_failed.append(
            f"{filename} (error from {options.light_model_name}: {str(e)})"
        )
        return None


def generate_summaries_on_filtered_files(
    filtered_files: List[FilteredFile],
    options: Options,
    prompts: Prompts,
    inputs: Inputs,
    light_bot: Bot,
) -> Tuple[List[FileSummary], List[str], List[str]]:
    """
    Process filtered files and return summaries, failed files, and skipped files.
    """
    summaries_failed = []
    summary_promises = []
    skipped_files = []

    for filtered_file in filtered_files:
        if options.max_files <= 0 or len(summary_promises) < options.max_files:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=options.concurrency_limit
            ) as executor:
                summary_promises.append(
                    executor.submit(
                        do_summary,
                        filtered_file.filename,
                        filtered_file.file_diff,
                        options,
                        prompts,
                        inputs,
                        light_bot,
                        summaries_failed,
                    )
                )
        else:
            skipped_files.append(filtered_file.filename)

    summaries: List[FileSummary] = []
    for future in concurrent.futures.as_completed(summary_promises):
        # Use result to get the result of the future
        summary = future.result()
        if summary is not None:
            summaries.append(summary)

    return summaries, summaries_failed, skipped_files


def generate_reviews_on_filtered_files(
    filtered_files: List[FilteredFile],
    summaries: List[FileSummary],
    options: Options,
    prompts: Prompts,
    inputs: Inputs,
    commenter: Commenter,
    heavy_bot: Bot,
) -> Tuple[List[str], List[str], int, int]:
    """Perform review on filtered files that need review."""
    files_and_changes_review = [
        (filtered_file.filename, filtered_file.file_content, filtered_file.patches)
        for filtered_file in filtered_files
        for file_summary in summaries
        if filtered_file.filename == file_summary.filename and file_summary.needs_review
    ]
    reviews_skipped = [
        filtered_file.filename
        for filtered_file in filtered_files
        if filtered_file.filename not in [f[0] for f in files_and_changes_review]
    ]
    skipped_files = []
    review_promises = []
    reviews_failed = []
    lgtm_count = []
    review_count = []

    for filename, file_content, patches in files_and_changes_review:
        if options.max_files <= 0 or len(review_promises) < options.max_files:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=options.concurrency_limit
            ) as executor:
                # Add the Future object to the list
                review_promises.append(
                    executor.submit(
                        do_review,
                        filename,
                        patches,
                        options,
                        prompts,
                        inputs,
                        commenter,
                        heavy_bot,
                        reviews_failed,
                        lgtm_count,
                        review_count,
                    )
                )
        else:
            skipped_files.append(filename)

    lgtm_count = sum(lgtm_count)
    review_count = sum(review_count)
    reviews = []
    for future in concurrent.futures.as_completed(review_promises):
        # Use result to get the result of the future
        review = future.result()
        if review is not None:
            reviews.append(review)

    return reviews_skipped, reviews_failed, lgtm_count, review_count


def generate_changes_summary(
    summaries: List[FileSummary],
    heavy_bot: Bot,
    prompts: Prompts,
    inputs: Inputs,
    options: Options,
    batch_size: int = 10,
) -> AiResponse:
    if len(summaries) > 0:
        for i in range(0, len(summaries), batch_size):
            summaries_batch: List[FileSummary] = summaries[i : i + batch_size]
            for file_summary in summaries_batch:
                inputs.raw_summary += (
                    f"---\n{file_summary.filename}: {file_summary.summary}\n"
                )

            summarize_resp = heavy_bot.chat(
                prompts.render_summarize_changesets(inputs), {}
            )
            if summarize_resp.message == "":
                print(
                    f"summarize: nothing obtained from {options.heavy_model_name} model"
                )
            else:
                inputs.raw_summary = summarize_resp.message

    return heavy_bot.chat(prompts.render_summarize(inputs), {})


def update_release_notes(
    heavy_bot: Bot,
    prompts: Prompts,
    inputs: Inputs,
    options: Options,
    commenter: Commenter,
) -> None:
    release_notes_response = heavy_bot.chat(
        prompts.render_summarize_release_notes(inputs), {}
    )
    if release_notes_response.message == "":
        print(f"release notes: nothing obtained from {options.heavy_model_name} model")
    else:
        message = (
            f"### Summary by {BOT_NAME_NO_TAG}\n\n" + release_notes_response.message
        )
        try:
            commenter.update_description(
                github_context.payload.pull_request.number, message
            )
        except Exception as e:
            print(f"release notes: error from github: {str(e)}")


def generate_short_summary(heavy_bot: Bot, prompts: Prompts, inputs: Inputs) -> None:
    summarize_short_response = heavy_bot.chat(
        prompts.render_summarize_short(inputs), {}
    )
    inputs.short_summary = summarize_short_response.message


def do_review(
    filename: str,
    patches: list[Patch],
    options: Options,
    prompts: Prompts,
    inputs: Inputs,
    commenter: Commenter,
    heavy_bot: Bot,
    reviews_failed: list[str],
    lgtm_count: list[int],
    review_count: list[int],
):

    print(f"reviewing {filename}")
    ins = inputs.clone()
    ins.filename = filename

    tokens = get_token_count(prompts.render_review_file_diff(ins))
    patches_to_pack = 0
    for patch in patches:
        patch_tokens = get_token_count(patch.patch_str)
        if tokens + patch_tokens > options.heavy_token_limits.request_tokens:
            print(
                f"only packing {patches_to_pack} / {len(patches)} patches, tokens: {tokens} / {options.heavy_token_limits.request_tokens}"
            )
            break
        tokens += patch_tokens
        patches_to_pack += 1

    patches_packed = 0
    for patch in patches:
        if github_context.payload.pull_request is None:
            print("No pull request found, skipping.")
            continue

        if patches_packed >= patches_to_pack:
            print(
                f"unable to pack more patches into this request, packed: {patches_packed}, total patches: {len(patches)}, skipping."
            )
            if options.debug:
                print(f"prompt so far: {prompts.render_review_file_diff(ins)}")
            break

        patches_packed += 1

        comment_chain = ""
        try:
            all_chains = commenter.get_comment_chains_within_range(
                github_context.payload.pull_request.number,
                filename,
                patch.start_line,
                patch.end_line,
                TAGS.COMMENT_REPLY_TAG,
            )
            if len(all_chains) > 0:
                print(f"Found comment chains: {all_chains} for {filename}")
                comment_chain = all_chains
        except Exception as e:
            print(
                f"Failed to get comments: {str(e)}, skipping. backtrace: {traceback.format_exc()}"
            )

        comment_chain_tokens = get_token_count(comment_chain)
        if tokens + comment_chain_tokens > options.heavy_token_limits.request_tokens:
            comment_chain = ""
        else:
            tokens += comment_chain_tokens

        ins.patches += f"\n{patch.patch_str}\n"
        if comment_chain != "":
            ins.patches += f"\n---comment_chains---\n```\n{comment_chain}\n```\n"

        ins.patches += "\n---end_change_section---\n"

    if patches_packed > 0:
        try:
            response = heavy_bot.chat(prompts.render_review_file_diff(ins), {})
            if response == "":
                print(f"review: nothing obtained from {options.heavy_model_name} model")
                reviews_failed.append(f"{filename} (no response)")
                return

            reviews = parse_review(response, patches, options.debug)
            for review in reviews:
                if not options.review_comment_lgtm and (
                    "LGTM" in review.comment or "looks good to me" in review.comment
                ):
                    lgtm_count.append(1)
                    continue

                if github_context.payload.pull_request is None:
                    print("No pull request found, skipping.")
                    continue

                try:
                    review_count.append(1)
                    commenter.buffer_review_comment(
                        filename,
                        review.start_line,
                        review.end_line,
                        f"{review.comment}",
                    )
                except Exception as e:
                    reviews_failed.append(f"{filename} comment failed ({str(e)})")
        except Exception as e:
            print(
                f"Failed to review: {str(e)}, skipping. backtrace: {traceback.format_exc()}"
            )
            reviews_failed.append(f"{filename} ({str(e)})")


def code_review(light_bot: Bot, heavy_bot: Bot, options: Options, prompts: Prompts):
    commenter = Commenter(github_context=github_context)

    print("Context from review: ", github_context)

    if github_context.event_name not in ("pull_request", "pull_request_target"):
        print(
            f"Skipped: current event is {github_context.event_name}, only support pull_request event"
        )
        return

    if github_context.payload.pull_request is None:
        print("Skipped: github_context.payload.pull_request is None")
        return

    inputs = Inputs()
    inputs.title = github_context.payload.pull_request.title
    if github_context.payload.pull_request.body is not None:
        inputs.description = commenter.get_description(
            github_context.payload.pull_request.body
        )

    if IGNORE_KEYWORD in inputs.description:
        print("Skipped: description contains ignore_keyword")
        return

    inputs.system_message = options.system_message

    existing_summarize_cmt: IssueComment = commenter.find_issue_comment_with_tag(
        TAGS.SUMMARIZE_TAG, pr_number=github_context.payload.pull_request.number
    )
    existing_commit_ids_block = ""
    existing_summarize_cmt_body = ""
    if existing_summarize_cmt is not None:
        existing_summarize_cmt_body = existing_summarize_cmt.body
        inputs.raw_summary = commenter.get_raw_summary(existing_summarize_cmt_body)
        inputs.short_summary = commenter.get_short_summary(existing_summarize_cmt_body)
        existing_commit_ids_block = commenter.get_reviewed_commit_ids_block(
            existing_summarize_cmt_body
        )

    all_commit_ids = commenter.get_all_commit_ids()
    highest_reviewed_commit_id = ""
    if existing_commit_ids_block != "":
        highest_reviewed_commit_id = commenter.get_highest_reviewed_commit_id(
            all_commit_ids, commenter.get_reviewed_commit_ids(existing_commit_ids_block)
        )

    if (
        highest_reviewed_commit_id == ""
        or highest_reviewed_commit_id == github_context.payload.pull_request.head.sha
    ):
        print(
            f"Will review from the base commit: {github_context.payload.pull_request.base.sha}"
        )
        highest_reviewed_commit_id = github_context.payload.pull_request.base.sha
    else:
        print(f"Will review from commit: {highest_reviewed_commit_id}")

    incremental_diff: Comparison = REPO.compare(
        highest_reviewed_commit_id, github_context.payload.pull_request.head.sha
    )

    target_branch_diff: Comparison = REPO.compare(
        github_context.payload.pull_request.base.sha,
        github_context.payload.pull_request.head.sha,
    )

    incremental_files: List[File] = incremental_diff.files
    target_branch_files: List[File] = target_branch_diff.files

    if incremental_files is None or target_branch_files is None:
        print("Skipped: files data is missing")
        return

    files = [
        target_branch_file
        for target_branch_file in target_branch_files
        if any(
            incremental_file.filename == target_branch_file.filename
            for incremental_file in incremental_files
        )
    ]

    if len(files) == 0:
        print("Skipped: files is None")
        return

    filter_selected_files: list[File] = []
    filter_ignored_files: list[File] = []
    for file in files:
        if not options.check_path(file.filename):
            print(f"skip for excluded path: {file.filename}")
            filter_ignored_files.append(file)
        else:
            filter_selected_files.append(file)

    if len(filter_selected_files) == 0:
        print("Skipped: filter_selected_files is None")
        return

    commits: PaginatedList[Commit] = incremental_diff.commits

    if commits.totalCount == 0:
        print("Skipped: commits is None")
        return

    filtered_files = FilteredFile.get_filtered_files(files, options, incremental_diff)

    if len(filtered_files) == 0:
        print("Skipped: no files to review")
        return

    status_message_prompt = StatusMessagePrompt()
    status_message_prompt.render_commits_summary(
        highest_reviewed_commit_id, github_context.payload.pull_request.head.sha
    )
    status_message_prompt.render_files_selected(filtered_files)

    status_message_prompt.render_files_ignored(filter_ignored_files)

    in_progress_summarize_cmt = commenter.add_in_progress_status(
        existing_summarize_cmt_body, status_message_prompt.summary_message
    )
    commenter.comment(
        f"{in_progress_summarize_cmt}", TAGS.SUMMARIZE_TAG, mode=CommentMode.REPLACE
    )

    summaries, summaries_failed, skipped_files = generate_summaries_on_filtered_files(
        filtered_files, options, prompts, inputs, light_bot
    )

    summary_changes = generate_changes_summary(
        summaries, heavy_bot, prompts, inputs, options
    )
    if summary_changes.message == "":
        print(f"summarize: nothing obtained from {options.heavy_model_name} model")

    if not options.disable_release_notes:
        update_release_notes(heavy_bot, prompts, inputs, options, commenter)

    generate_short_summary(heavy_bot, prompts, inputs)

    summarize_comment = SummarizeComment(summary_changes, inputs)

    status_message_prompt.render_skipped_files(skipped_files)
    status_message_prompt.render_summaries_failed(summaries_failed)

    if not options.disable_review:
        reviews_skipped, reviews_failed, lgtm_count, review_count = (
            generate_reviews_on_filtered_files(
                filtered_files,
                summaries,
                options,
                prompts,
                inputs,
                commenter,
                heavy_bot,
            )
        )

        status_message_prompt.render_reviews_failed(reviews_failed)
        status_message_prompt.render_reviews_skipped(reviews_skipped)

        status_message_prompt.render_review_comments_generated(review_count, lgtm_count)
        status_message_prompt.render_tips()

        summarize_comment.reviewed_commit_id = commenter.add_reviewed_commit_id(
            existing_commit_ids_block, github_context.payload.pull_request.head.sha
        )
        # Before we need to fetch all review done, remove all from bot, and create a new one
        # Let's it be a less spammy review option
        # PullRequestReview

        if options.less_spammy:
            commenter.dismiss_review_and_remove_comments(
                github_context.payload.pull_request.number
            )

        commenter.submit_review(
            github_context.payload.pull_request.number,
            commits[-1],
            status_message_prompt.summary_message,
            allow_empty_review=options.allow_empty_review,
        )

    print(
        "[DEBUG]--------------------------BEFORE END COMMENT------------------------------------"
    )
    commenter.comment(f"{summarize_comment.render()}", SUMMARIZE_TAG, "replace")


def sanitize_code_block(comment: str, code_block_label: str) -> str:
    code_block_start = f"```{code_block_label}"
    code_block_end = "```"
    line_number_regex = r"^ *(\d+): "

    code_block_start_index = comment.find(code_block_start)

    while code_block_start_index != -1:
        code_block_end_index = comment.find(
            code_block_end, code_block_start_index + len(code_block_start)
        )

        if code_block_end_index == -1:
            break

        code_block = comment[
            code_block_start_index + len(code_block_start) : code_block_end_index
        ]
        sanitized_block = re.sub(line_number_regex, "", code_block, flags=re.MULTILINE)

        comment = (
            comment[: code_block_start_index + len(code_block_start)]
            + sanitized_block
            + comment[code_block_end_index:]
        )

        code_block_start_index = comment.find(
            code_block_start,
            code_block_start_index
            + len(code_block_start)
            + len(sanitized_block)
            + len(code_block_end),
        )

    return comment


def sanitize_response(comment: str) -> str:
    comment = sanitize_code_block(comment, "suggestion")
    comment = sanitize_code_block(comment, "diff")
    return comment


def store_review(
    current_start_line: int | None,
    current_end_line: int | None,
    current_comment: str,
    patches: list[Patch],
    debug: bool = False,
) -> list[Review]:
    reviews = []

    if current_start_line is not None and current_end_line is not None:
        review = Review(
            start_line=current_start_line,
            end_line=current_end_line,
            comment=current_comment,
        )

        within_patch = False
        best_patch_start_line = -1
        best_patch_end_line = -1
        max_intersection = 0

        for patch in patches:
            start_line = patch.start_line
            end_line = patch.end_line
            intersection_start = max(review.start_line, start_line)
            intersection_end = min(review.end_line, end_line)
            intersection_length = max(0, intersection_end - intersection_start + 1)

            if intersection_length > max_intersection:
                max_intersection = intersection_length
                best_patch_start_line = start_line
                best_patch_end_line = end_line
                within_patch = (
                    intersection_length == review.end_line - review.start_line + 1
                )

            if within_patch:
                break

        if not within_patch:
            if best_patch_start_line != -1 and best_patch_end_line != -1:
                review.comment = (
                    f"> Note: This review was outside of the patch, so it was mapped to the patch with the greatest overlap. "
                    f"Original lines [{review.start_line}-{review.end_line}]\n\n{review.comment}"
                )
                review.start_line = best_patch_start_line
                review.end_line = best_patch_end_line
            else:
                review.comment = (
                    f"> Note: This review was outside of the patch, but no patch was found that overlapped with it. "
                    f"Original lines [{review.start_line}-{review.end_line}]\n\n{review.comment}"
                )
                review.start_line = patches[0].start_line
                review.end_line = patches[0].end_line

        reviews.append(review)

        if debug:
            print(
                f"Stored comment for line range {current_start_line}-{current_end_line}: {current_comment.strip()}"
            )

    return reviews


def parse_review(
    response: AiResponse, patches: list[Patch], debug: bool = False
) -> list[Review]:
    reviews = []

    response = sanitize_response(response.message.strip())

    lines = response.split("\n")
    line_number_range_regex = r"(?:^|\s)(\d+)-(\d+):\s*$"
    comment_separator = "---"

    current_start_line = None
    current_end_line = None
    current_comment = ""

    for line in lines:
        line_number_range_match = re.search(line_number_range_regex, line)

        if line_number_range_match:
            reviews.extend(
                store_review(
                    current_start_line,
                    current_end_line,
                    current_comment,
                    patches,
                    debug,
                )
            )
            current_start_line = int(line_number_range_match.group(1))
            current_end_line = int(line_number_range_match.group(2))
            current_comment = ""
            if debug:
                print(
                    f"Found line number range: {current_start_line}-{current_end_line}"
                )
            continue

        if line.strip() == comment_separator:
            reviews.extend(
                store_review(
                    current_start_line,
                    current_end_line,
                    current_comment,
                    patches,
                    debug,
                )
            )
            current_start_line = None
            current_end_line = None
            current_comment = ""
            if debug:
                print("Found comment separator")
            continue

        if current_start_line is not None and current_end_line is not None:
            current_comment += f"{line}\n"

    reviews.extend(
        store_review(
            current_start_line, current_end_line, current_comment, patches, debug
        )
    )

    return reviews
