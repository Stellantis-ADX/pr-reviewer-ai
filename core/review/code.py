from __future__ import annotations

import concurrent.futures
import re
import traceback
from typing import Tuple

from github.File import File

from core.bots.bot import Bot
from core.commenter import CommentMode, GithubCommentManager
from core.github import GITHUB_CONTEXT
from core.schemas.files import AiSummary, FileSummary, FilteredFile
from core.schemas.options import Options
from core.schemas.patch import pack_patches_with_associated_comments_chains
from core.schemas.pr_common import PRDescription, PRInfo, ReviewedCommitIds
from core.schemas.prompts import ExistingSummarizedComment, Prompts
from core.schemas.review import ReviewSummary
from core.templates.tags import SUMMARIZE_TAG, TAGS
from core.tokenizer import get_token_count


def do_summary(
    file: FilteredFile,
    options: Options,
    prompts: Prompts,
    light_bot: Bot,
    summaries_failed: list[str],
) -> FileSummary | None:
    print(f"summarize: {file.filename}")
    if not file.file_diff:
        print(f"summarize: file_diff is empty, skip {file.filename}")
        summaries_failed.append(f"{file.filename} (empty diff)")
        return None

    summarize_prompt = prompts.render_summarize_file_diff(
        file, options.review_simple_changes
    )
    tokens = get_token_count(summarize_prompt)

    if tokens > options.light_token_limits.request_tokens:
        print(f"summarize: diff tokens exceeds limit, skip {file.filename}")
        summaries_failed.append(f"{file.filename} (diff tokens exceeds limit)")
        return None

    try:
        summarize_response = light_bot.chat(summarize_prompt)
        summary = summarize_response.message
        if summary == "":
            print(f"summarize: nothing obtained from {options.light_model_name} model")
            summaries_failed.append(
                f"{file.filename} (nothing obtained from {options.light_model_name} model)"
            )
            return None

        if options.review_simple_changes:
            return FileSummary(
                filename=file.filename, summary=summary, needs_review=True
            )

        triage_regex = r"\[TRIAGE\]:\s*(NEEDS_REVIEW|APPROVED)"
        triage_match = re.search(triage_regex, summary)

        if triage_match is not None:
            triage = triage_match.group(1)
            needs_review = triage == "NEEDS_REVIEW"
            summary = re.sub(triage_regex, "", summary).strip()
            print(f"filename: {file.filename}, triage: {triage}")
            return FileSummary(
                filename=file.filename, summary=summary, needs_review=needs_review
            )

    except Exception as e:
        error_message = f"summarize: error from {options.light_model_name}: {str(e)}"
        print(error_message)
        summaries_failed.append(f"{file.filename} ({error_message})")
        return None


def generate_summaries_on_filtered_files(
    filtered_files: list[FilteredFile],
    options: Options,
    prompts: Prompts,
    light_bot: Bot,
) -> Tuple[list[FileSummary], list[str], list[str]]:
    summaries_failed = []
    summary_promises = []
    skipped_files = []

    for filtered_file in filtered_files:
        #  Less than or equal to 0 means no limit.
        if options.max_files <= 0 or len(summary_promises) < options.max_files:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=options.concurrency_limit
            ) as executor:
                summary_promises.append(
                    executor.submit(
                        do_summary,
                        filtered_file,
                        options,
                        prompts,
                        light_bot,
                        summaries_failed,
                    )
                )
        else:
            skipped_files.append(filtered_file.filename)

    summaries: list[FileSummary] = []
    for future in concurrent.futures.as_completed(summary_promises):
        # Use result to get the result of the future
        summary = future.result()
        if summary is not None:
            summaries.append(summary)

    return summaries, summaries_failed, skipped_files


def generate_reviews_on_filtered_files(
    filtered_files: list[FilteredFile],
    skipped_files: list[str],
    summaries: list[FileSummary],
    ai_summary: AiSummary,
    options: Options,
    prompts: Prompts,
    pr_description: PRDescription,
    commenter: GithubCommentManager,
    heavy_bot: Bot,
) -> Tuple[ReviewSummary, list[str]]:
    #  Perform review on filtered files that need review.
    files_need_review = [
        filtered_file
        for filtered_file in filtered_files
        for file_summary in summaries
        if filtered_file.filename == file_summary.filename and file_summary.needs_review
    ]
    reviews_skipped = [
        filtered_file.filename
        for filtered_file in filtered_files
        if filtered_file.filename not in [f.filename for f in files_need_review]
    ]

    review_summary = ReviewSummary()
    review_summary.skipped.extend(reviews_skipped)

    review_futures = []
    for file in files_need_review:
        if options.max_files <= 0 or len(review_futures) < options.max_files:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=options.concurrency_limit
            ) as executor:
                # Add the Future object to the list
                review_futures.append(
                    executor.submit(
                        do_review,
                        file,
                        ai_summary,
                        options,
                        prompts,
                        pr_description,
                        commenter,
                        heavy_bot,
                        review_summary,
                    )
                )
        else:
            skipped_files.append(file.filename)

    reviews = []
    for future in concurrent.futures.as_completed(review_futures):
        # Use result to get the result of the future
        review = future.result()
        if review is not None:
            reviews.append(review)

    return review_summary, skipped_files


def process_review_response(
    heavy_bot: Bot,
    prompts: Prompts,
    file: FilteredFile,
    ai_summary: AiSummary,
    pr_description: PRDescription,
    review_summary: ReviewSummary,
    options: Options,
):
    try:
        response = heavy_bot.chat(
            prompts.render_review_file_diff(
                file=file, ai_summary=ai_summary, pr_description=pr_description
            )
        )
        if not response.message:
            print(f"review: nothing obtained from {options.heavy_model_name} model")
            review_summary.failed.append(f"{file.filename} (no response)")
            return

        review_summary.parse_ai_review(response, file, options.debug)
        review_summary.filter_lgtm_reviews(options)

    except Exception as e:
        print(
            f"Failed to review: {str(e)}, skipping. backtrace: {traceback.format_exc()}"
        )
        review_summary.failed.append(f"{file.filename} ({str(e)})")


def do_review(
    file: FilteredFile,
    ai_summary: AiSummary,
    options: Options,
    prompts: Prompts,
    pr_description: PRDescription,
    commenter: GithubCommentManager,
    heavy_bot: Bot,
    review_summary: ReviewSummary,
):
    print(f"reviewing {file.filename}")
    tokens = get_token_count(
        prompts.render_review_file_diff(
            file=file, ai_summary=ai_summary, pr_description=pr_description
        )
    )
    patch_packing_limit = file.patches.compute_patch_packing_limit(tokens, options)
    tokens += file.patches.tokens_count_wrt_packing_limit(patch_packing_limit)
    # Here we pack patches with associated comments chains from bot
    # TODO do we want to pack comments chains from users?
    file.patches.items_str = pack_patches_with_associated_comments_chains(
        file=file,
        patch_packing_limit=patch_packing_limit,
        commenter=commenter,
        tokens=tokens,
        options=options,
    )

    if options.debug:
        print(
            f"prompt so far: {prompts.render_review_file_diff(file=file,ai_summary=ai_summary,pr_description=pr_description)}"
        )

    # We do review only if we have patches to review
    if file.patches.items_str:
        process_review_response(
            heavy_bot=heavy_bot,
            prompts=prompts,
            file=file,
            ai_summary=ai_summary,
            pr_description=pr_description,
            review_summary=review_summary,
            options=options,
        )


def generate_filtered_ignored_files(
    pr_info: PRInfo, options: Options
) -> Tuple[list[FilteredFile], list[File]]:

    incremental_files: list[File] = pr_info.incremental_diff.files
    target_branch_files: list[File] = pr_info.target_branch_diff.files

    if incremental_files is None or target_branch_files is None:
        return [], []

    files = [
        target_branch_file
        for target_branch_file in target_branch_files
        if any(
            incremental_file.filename == target_branch_file.filename
            for incremental_file in incremental_files
        )
    ]

    filter_selected_files: list[File] = []
    filter_ignored_files: list[File] = []
    for file in files:
        if not options.check_path(file.filename):
            filter_ignored_files.append(file)
        else:
            filter_selected_files.append(file)

    filtered_files = FilteredFile.get_filtered_files(filter_selected_files, options)

    return filtered_files, filter_ignored_files


def code_review(light_bot: Bot, heavy_bot: Bot, options: Options, prompts: Prompts):
    if not GITHUB_CONTEXT.is_context_valid(
        event_names=("pull_request", "pull_request_target")
    ):
        return

    commenter = GithubCommentManager()
    pr_info = PRInfo()
    pr_description = PRDescription()

    if pr_description.user_ask_to_ignore:
        print("Skipped: description contains ignore_keyword")
        return

    existing_summarize_comment = ExistingSummarizedComment(commenter=commenter)
    existing_summarize_comment.update_reviewed_commit_ids(
        ReviewedCommitIds.from_summarized_comment(
            body=existing_summarize_comment.body, pr_info=pr_info
        )
    )

    pr_info.fetch_commits(
        existing_summarize_comment.reviewed_commits_ids.highest_reviewed_commit_id
    )

    if pr_info.commits.totalCount == 0:
        print("Skipped: commits is None")
        return

    filtered_files, ignored_files = generate_filtered_ignored_files(
        pr_info=pr_info, options=options
    )

    if not filtered_files:
        print("Skipped: no files to review")
        return

    commenter.comment(
        message=existing_summarize_comment.status_message_in_progress(
            filtered_files=filtered_files, ignored_files=ignored_files
        ),
        pr_number=pr_info.number,
        tag=TAGS.SUMMARIZE_TAG,
        mode=CommentMode.REPLACE,
    )

    summaries, summaries_failed, skipped_files = generate_summaries_on_filtered_files(
        filtered_files=filtered_files,
        options=options,
        prompts=prompts,
        light_bot=light_bot,
    )

    ai_summary = existing_summarize_comment.ai_summary.model_copy()
    ai_summary.generate_new_raw_summary(
        heavy_bot, prompts, summaries, options, batch_size=10
    )
    # To generate short summary,changeset summary we need to regenerate the raw summary
    ai_summary.generate_new_short_summary(heavy_bot, prompts)
    ai_summary.generate_new_changeset_summary(heavy_bot, prompts)
    existing_summarize_comment.update_ai_summary(ai_summary)
    if ai_summary.changeset_summary == "":
        print(f"summarize: nothing obtained from {options.heavy_model_name} model")

    pr_description.update_description_with_release_notes(
        heavy_bot=heavy_bot,
        prompts=prompts,
        ai_summary=ai_summary,
        options=options,
        pr_info=pr_info,
    )

    if not options.disable_review:

        review_summary, skipped_files = generate_reviews_on_filtered_files(
            filtered_files=filtered_files,
            skipped_files=skipped_files,
            summaries=summaries,
            ai_summary=ai_summary,
            options=options,
            prompts=prompts,
            pr_description=pr_description,
            commenter=commenter,
            heavy_bot=heavy_bot,
        )

        # Before we need to fetch all review done, remove all from bot, and create a new one
        # Let it be a less spammy review option

        if options.less_spammy:
            commenter.dismiss_review_and_remove_comments(pr_info.number)

        status_message_finished_review = review_summary.get_status_message_finished_review(
            existing_summarize_comment.reviewed_commits_ids.highest_reviewed_commit_id,
            filtered_files,
            ignored_files,
            skipped_files,
            summaries_failed,
        )

        commenter.submit_review(
            pull_number=pr_info.number,
            commit=pr_info.last_commit,
            review_summary=review_summary,
            status_msg=status_message_finished_review,
            allow_empty_review=options.allow_empty_review,
        )

    print(
        "[DEBUG]--------------------------BEFORE END COMMENT------------------------------------"
    )
    commenter.comment(
        message=f"{existing_summarize_comment.render(disable_review=options.disable_review)}",
        pr_number=pr_info.number,
        tag=SUMMARIZE_TAG,
        mode=CommentMode.REPLACE,
    )
