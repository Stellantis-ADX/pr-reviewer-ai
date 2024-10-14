from github_action_utils import notice as info
from github_action_utils import notice as warning

from core.bot import Bot
from core.commenter import Commenter
from core.consts import BOT_NAME
from core.github.context import GITHUB_ACTION_CONTEXT
from core.github.github import GITHUB_API
from core.schemas.inputs import Inputs
from core.schemas.options import Options
from core.schemas.prompts import Prompts
from core.templates.tags import COMMENT_REPLY_TAG, COMMENT_TAG, SUMMARIZE_TAG
from core.tokenizer import get_token_count
from core.utils import git_diff_from_discussion

context = GITHUB_ACTION_CONTEXT
repo = GITHUB_API.get_repo(context.payload.repository.full_name)


def handle_review_comment(heavy_bot: Bot, options: Options, prompts: Prompts):
    commenter = Commenter(context)
    inputs = Inputs()
    if context.event_name != "pull_request_review_comment":
        warning(
            f"Skipped: {context.event_name} is not a pull_request_review_comment event"
        )
        return

    if not context.payload:
        warning(f"Skipped: {context.event_name} event is missing payload.")
        return

    comment = context.payload.get("comment")
    if comment is None:
        warning(f"Skipped: {context.event_name} event is missing comment")
        return
    pull_request = context.payload.get("pull_request")
    repository = context.payload.get("repository")
    if pull_request is None or repository is None:
        print(f"Skipped: {context.event_name} event is missing pull_request")
        return
    inputs.title = pull_request.title
    if pull_request.body:
        inputs.description = commenter.get_description(pull_request.body)

    if context.payload.get("action") != "created":
        warning(f"Skipped: {context.event_name} event is not created")
        return
    if COMMENT_TAG not in comment.body and COMMENT_REPLY_TAG not in comment.body:
        pull_number = pull_request.number

        inputs.comment = f"{comment.user.login}: {comment.body}"

        inputs.diff = git_diff_from_discussion(
            comment.diff_hunk,
            start_line=comment.start_line,
            end_line=comment.original_line,
            html_url=comment.html_url,
        )
        inputs.filename = comment.path
        comment_chain, top_level_comment = commenter.get_comment_chain(
            pull_number, comment
        )

        if top_level_comment is None:
            warning("Failed to find the top-level comment to reply to")
            return

        inputs.comment_chain = comment_chain
        inputs.print()

        if (
            COMMENT_TAG in comment_chain
            or COMMENT_REPLY_TAG in comment_chain
            or BOT_NAME in comment.body.lower()
        ):
            file_diff = ""
            try:
                diff_all = repo.compare(
                    pull_request.base.sha,
                    pull_request.head.sha,
                )
                files = diff_all.files
                if files is not None:
                    file = next((f for f in files if f.filename == comment.path), None)
                    if file is not None and file.patch is not None:
                        file_diff = file.patch
            except Exception as error:
                warning(f"Failed to get file diff: {error}, skipping.")

            if len(inputs.diff) == 0:
                if len(file_diff) > 0:
                    inputs.diff = file_diff
                    file_diff = ""
                else:
                    commenter.review_comment_reply(
                        pull_number,
                        top_level_comment,
                        "Cannot reply to this comment as diff could not be found.",
                    )
                    return

            tokens = get_token_count(prompts.render_comment(inputs))

            if tokens > options.heavy_token_limits.request_tokens:
                print(
                    f"TOKENS: {tokens} vs {options.heavy_token_limits.request_tokens}"
                )
                commenter.review_comment_reply(
                    pull_number,
                    top_level_comment,
                    "Cannot reply to this comment as diff being commented is too large and"
                    " exceeds the token limit.",
                )
                return

            if len(file_diff) > 0:
                file_diff_count = prompts.comment.template.count("$file_diff")
                file_diff_tokens = get_token_count(file_diff)
                if (
                    file_diff_count > 0
                    and tokens + file_diff_tokens * file_diff_count
                    <= options.heavy_token_limits.request_tokens
                ):
                    tokens += file_diff_tokens * file_diff_count
                    inputs.file_diff = file_diff

            summary = commenter.find_issue_comment_with_tag(SUMMARIZE_TAG, pull_number)
            if summary:
                short_summary = commenter.get_short_summary(summary.body)
                short_summary_tokens = get_token_count(short_summary)
                if (
                    tokens + short_summary_tokens
                    <= options.heavy_token_limits.request_tokens
                ):
                    tokens += short_summary_tokens
                    inputs.short_summary = short_summary

            inputs.print()
            reply = heavy_bot.chat(prompts.render_comment(inputs), {})

            commenter.review_comment_reply(
                pull_number, top_level_comment, reply.message
            )
    else:
        info(f"Skipped: {context.event_name} event is from the bot itself")
