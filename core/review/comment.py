from __future__ import annotations

from box import Box
from github_action_utils import notice

from core.bots.bot import Bot
from core.commenter import GithubCommentManager
from core.github import GITHUB_CONTEXT
from core.schemas.comment_reply import CommentReply
from core.schemas.options import Options
from core.schemas.pr_common import PRDescription, PRInfo
from core.schemas.prompts import ExistingSummarizedComment, Prompts
from core.templates.tags import TAGS
from core.tokenizer import get_token_count


def bot_call_itself(comment: Box) -> bool:
    if TAGS.COMMENT_REPLY_TAG in comment.body:
        notice(f"Skipped: {GITHUB_CONTEXT.event_name} event is from the bot itself")
        return True

    return False


def is_token_limit_exceeded(tokens: int, token_limits: int) -> bool:
    return tokens > token_limits


def handle_review_comment(heavy_bot: Bot, options: Options, prompts: Prompts):
    if not GITHUB_CONTEXT.is_context_valid(
        event_names=("pull_request_review_comment",)
    ):
        return

    pr_description = PRDescription()
    pr_info = PRInfo()

    comment = GITHUB_CONTEXT.payload.comment
    if bot_call_itself(comment):
        return

    commenter = GithubCommentManager()
    comment_reply = CommentReply().init_with(
        comment=comment, comment_manager=commenter, pr_info=pr_info
    )

    if not comment_reply.is_top_level_comment_found:
        return

    if not comment_reply.is_bot_mentioned_in_comment_chain:
        return

    if not comment_reply.diff:
        # TODO verify if file_diff is needed, only once we don't have a diff,
        # when we call the bot on comment without diff
        commenter.review_comment_reply(
            pr_info.number,
            comment_reply.top_level_comment,
            message="Cannot reply to this comment as diff could not be found.",
        )
        return

    final_prompt = prompts.render_comment(
        comment_reply=comment_reply,
        pr_description=pr_description,
        ai_summary=None,
        exclude="file_content",
    )

    tokens_prompt = get_token_count(final_prompt)

    if is_token_limit_exceeded(
        tokens_prompt, token_limits=options.heavy_token_limits.request_tokens
    ):
        print(f"TOKENS: {tokens_prompt} vs {options.heavy_token_limits.request_tokens}")
        commenter.review_comment_reply(
            pr_info.number,
            comment_reply.top_level_comment,
            message="Cannot reply to this comment as diff being commented is too large and"
            " exceeds the token limit.",
        )
        return

    if not is_token_limit_exceeded(
        tokens_prompt + comment_reply.file.content_tokens,
        token_limits=options.heavy_token_limits.request_tokens,
    ):
        final_prompt = prompts.render_comment(
            comment_reply=comment_reply,
            pr_description=pr_description,
            ai_summary=None,
        )
        tokens_prompt = get_token_count(final_prompt)

    existing_ai_summary = ExistingSummarizedComment(commenter=commenter).ai_summary

    if not is_token_limit_exceeded(
        tokens_prompt + existing_ai_summary.short_summary_tokens,
        token_limits=options.heavy_token_limits.request_tokens,
    ):
        final_prompt = prompts.render_comment(
            comment_reply=comment_reply,
            pr_description=pr_description,
            ai_summary=existing_ai_summary,
        )

    reply = heavy_bot.chat(final_prompt)
    commenter.review_comment_reply(
        pr_info.number, comment_reply.top_level_comment, reply.message
    )
