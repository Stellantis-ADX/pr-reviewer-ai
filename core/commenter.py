from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

from box import Box
from github import Issue
from github.Commit import Commit
from github.IssueComment import IssueComment
from github.PullRequestComment import PullRequestComment
from github_action_utils import notice as info
from github_action_utils import warning

from core.consts import DISMISSAL_MESSAGE
from core.github import GITHUB_CONTEXT, REPO

if TYPE_CHECKING:  # a hack to avoid circular imports, when we ONLY want to type hint
    # https://peps.python.org/pep-0563/#runtime-annotation-resolution-and-type-checking
    from core.schemas.review import ReviewSummary

from core.schemas.comment_chains import CommentChain, CommentChains
from core.templates.tags import TAGS


class CommentMode(str, Enum):
    CREATE = "create"
    REPLACE = "replace"


class GithubCommentManager:

    def __init__(self):
        self.issue_comments_cache = {}
        self.review_comments_cache = {}

    def comment(
        self,
        message: str,
        pr_number: int,
        tag: TAGS = "",
        mode: str = CommentMode.REPLACE,
    ):
        if not tag:
            tag = TAGS.COMMENT_TAG

        comment_body = f"{TAGS.COMMENT_GREETING}\n\n{message}\n\n{tag}"

        if mode == CommentMode.CREATE:
            self.create(comment_body, pr_number)
        elif mode == CommentMode.REPLACE:
            self.replace(comment_body, tag, pr_number)
        else:
            print(f"Unknown mode: {mode}, use {CommentMode.REPLACE} instead")
            self.replace(comment_body, tag, pr_number)

    def dismiss_review_and_remove_comments(self, pull_number: int):
        pr = REPO.get_pull(pull_number)
        # TODO try to find out if commit was resolved. Couldn't be done with the current API Rest,
        # Only with GraphQL API
        pull_request_review = sorted(
            [
                review
                for review in pr.get_reviews()
                if review.user.type == "Bot"
                and review.body
                and review.body != DISMISSAL_MESSAGE
            ],
            key=lambda x: x.submitted_at,
        )

        if not pull_request_review:
            print("No reviews found")
            return

        last_pull_request_review = pull_request_review[-1]
        review_comments = [
            review_comment for review_comment in pr.get_review_comments()
        ]
        review_comments_wrt_pull_request_review = [
            review_comment
            for review_comment in review_comments
            if review_comment.pull_request_review_id == last_pull_request_review.id
        ]
        review_comments_wrt_pull_request_review_ids = [
            review_comment.id
            for review_comment in review_comments_wrt_pull_request_review
        ]

        ids_to_keep = set()
        for review_comment in review_comments:
            if (
                review_comment.in_reply_to_id
                in review_comments_wrt_pull_request_review_ids
            ):
                ids_to_keep.add(review_comment.id)
                ids_to_keep.add(review_comment.in_reply_to_id)

        try:
            # we cannot delete review
            # so let's change it to dismissed
            last_pull_request_review.edit(body=DISMISSAL_MESSAGE)
            info(
                f"Dismiss review for PR #{pull_number} id: {last_pull_request_review.id}"
            )
        except Exception as e:
            print(f"Failed to dismiss review: {e}")

        try:
            # delete comments
            for review_comment in review_comments_wrt_pull_request_review:
                if review_comment.id not in ids_to_keep:
                    review_comment.delete()
                    info(
                        f"Deleting review comment for PR #{pull_number} id: {review_comment.id}"
                    )
        except Exception as e:
            print(f"Failed to delete review comments: {e}")

        return

    def delete_pending_review(self, pull_number: int):
        try:
            pull_request = REPO.get_pull(pull_number)
            reviews = pull_request.get_reviews()
            # TODO check if we even need check PENDING
            pending_review = next(
                (review for review in reviews if review.state == "PENDING"), None
            )
            if pending_review:
                info(
                    f"Deleting pending review for PR #{pull_number} id: {pending_review.id}"
                )
                try:
                    pending_review.delete()
                except Exception as e:
                    warning(f"Failed to delete pending review: {e}")
        except Exception as e:
            warning(f"Failed to list reviews: {e}")

    def submit_review(
        self,
        pull_number: int,
        commit: Commit,
        status_msg: str,
        allow_empty_review: bool,
        review_summary: ReviewSummary,
    ):
        body = f"{TAGS.COMMENT_GREETING}\n\n{status_msg}\n"

        if len(review_summary.buffer) == 0:
            info(
                f"Submitting empty review for PR #{pull_number}"
                if allow_empty_review
                else f"Submitting empty review is disabled for PR #{pull_number}"
            )
            if allow_empty_review:
                try:
                    pull_request = REPO.get_pull(pull_number)
                    pull_request.create_review(body=body, event="COMMENT")
                except Exception as e:
                    warning(f"Failed to submit empty review: {e}")
            return

        for review_comment in review_summary.buffer:
            comments = self.get_comments_at_range(
                pull_number,
                review_comment.path,
                review_comment.start_line,
                review_comment.end_line,
            )
            for comment in comments:
                if TAGS.COMMENT_TAG in comment.body:
                    info(
                        f"Deleting review comment for "
                        f"{review_comment.path}:{review_comment.start_line}-{review_comment.end_line}: "
                        f"{review_comment.comment}"
                    )
                    try:
                        comment.delete()
                    except Exception as e:
                        warning(f"Failed to delete review comment: {e}")

        try:
            pull_request = REPO.get_pull(pull_number)
            review = pull_request.create_review(
                body=body,
                commit=commit,
                event="COMMENT",
                comments=[
                    comment.generate_comment_data() for comment in review_summary.buffer
                ],
            )

            info(
                f"Submitting review for PR #{pull_number}, "
                f"total comments: {len(review_summary.buffer)}, review id: {review.id}"
            )

        except Exception as e:
            warning(
                f"Failed to create review: {e}. Falling back to individual comments."
            )
            self.delete_pending_review(pull_number)
            comment_counter = 0
            for review_comment in review_summary.buffer:
                info(
                    f"Creating new review comment for "
                    f"{review_comment.path}:{review_comment.start_line}-{review_comment.end_line}:"
                    f" {review_comment.comment}"
                )
                comment_data = review_comment.generate_comment_data()

                try:
                    pull_request = REPO.get_pull(pull_number)
                    # TODO explore create_review_comment it could set as suggestion
                    pull_request.create_comment(
                        body=comment_data["body"],
                        commit=commit,
                        path=comment_data["path"],
                        position=comment_data["line"],
                    )
                except Exception as ee:
                    warning(f"Failed to create review comment: {ee}")

                comment_counter += 1
                info(f"Comment {comment_counter}/{len(review_summary.buffer)} posted")

    def review_comment_reply(
        self, pull_number: int, top_level_comment: PullRequestComment, message: str
    ):
        reply = f"{TAGS.COMMENT_GREETING}\n\n{message}\n\n{TAGS.COMMENT_REPLY_TAG}\n"
        try:
            # Post the reply to the user comment
            pull_request = REPO.get_pull(pull_number)
            pull_request.create_review_comment_reply(top_level_comment.id, reply)
        except Exception as error:
            warning(f"Failed to reply to the top-level comment {error}")
            try:
                pull_request = REPO.get_pull(pull_number)
                pull_request.create_review_comment_reply(
                    top_level_comment.id,
                    f"Could not post the reply to the top-level comment due to the following error: {error}",
                )
            except Exception as e:
                warning(f"Failed to reply to the top-level comment {e}")

        try:
            if TAGS.COMMENT_TAG in top_level_comment.body:
                # replace COMMENT_TAG with COMMENT_REPLY_TAG in top_level_comment
                new_body = top_level_comment.body.replace(
                    TAGS.COMMENT_TAG, TAGS.COMMENT_REPLY_TAG
                )
                top_level_comment.edit(new_body)
        except Exception as error:
            warning(f"Failed to update the top-level comment {error}")

    def get_review_comments_within_range(
        self, pull_number: int, path: str, start_line: int, end_line: int
    ) -> list[PullRequestComment]:
        comments = self.list_review_comments(pull_number)
        return [
            comment
            for comment in comments
            if comment.path == path
            and comment.body != ""
            and (
                (
                    comment.raw_data.get("start_line") is not None
                    and comment.raw_data.get("start_line") >= start_line
                    and comment.raw_data.get("line") <= end_line
                )
                or (start_line == end_line and comment.raw_data.get("line") == end_line)
            )
        ]

    def get_comments_at_range(
        self, pull_number: int, path: str, start_line: int, end_line: int
    ) -> list[PullRequestComment]:
        comments = self.list_review_comments(pull_number)
        return [
            comment
            for comment in comments
            if comment.path == path
            and comment.body != ""
            and (
                (
                    comment.raw_data.get("start_line") is not None
                    and comment.raw_data.get("start_line") == start_line
                    and comment.raw_data.get("line") == end_line
                )
                or (start_line == end_line and comment.raw_data.get("line") == end_line)
            )
        ]

    def get_comment_chains_within_range(
        self, pull_number: int, path: str, start_line: int, end_line: int, tag: str = ""
    ) -> CommentChains:
        existing_comments = self.get_review_comments_within_range(
            pull_number, path, start_line, end_line
        )
        top_level_comments = [
            comment for comment in existing_comments if not comment.in_reply_to_id
        ]

        all_chains = []

        for top_level_comment in top_level_comments:
            chain = self.compose_comment_chain(existing_comments, top_level_comment)
            if chain and tag in chain:
                all_chains.append(
                    CommentChain(
                        start_line=start_line,
                        end_line=end_line,
                        comment=chain,
                        top_level_comment_id=top_level_comment.id,
                    )
                )

        return CommentChains(items=all_chains)

    def compose_comment_chain(
        self,
        review_comments: list[PullRequestComment],
        top_level_comment: PullRequestComment,
    ) -> str:
        conversation_chain = [
            f"{cmt.user.login}: {cmt.body}"
            for cmt in review_comments
            if cmt.in_reply_to_id == top_level_comment.id
        ]
        conversation_chain.insert(
            0, f"{top_level_comment.user.login}: {top_level_comment.body}"
        )
        return "\n---\n".join(conversation_chain)

    def get_comment_chain(
        self, pull_number: int, comment: Box
    ) -> tuple[str, PullRequestComment | None]:
        try:
            review_comments = self.list_review_comments(pull_number)
            print(f"Review comments: {review_comments}")
            print(f"Comment: {comment}")
            top_level_comment = self.get_top_level_comment(review_comments, comment)
            chain = self.compose_comment_chain(review_comments, top_level_comment)
            return chain, top_level_comment
        except Exception as e:
            print(f"Failed to get conversation chain: {e}")
            return "", None

    def get_top_level_comment(
        self, review_comments: list[PullRequestComment], comment: Box
    ) -> PullRequestComment:
        # TODO try to cast to PullRequestComment
        # If the comment object has an in_reply_to_id attribute
        if comment.get("in_reply_to_id", None) is not None:
            # Find the parent comment in the review_comments list
            parent_comment = next(
                (cmt for cmt in review_comments if cmt.id == comment.in_reply_to_id),
                None,
            )

            # If the parent comment is found, return the parent comment
            if parent_comment:
                return parent_comment

        # If the comment object does not have an in_reply_to_id attribute, return the comment object itself
        return comment

    def list_review_comments(self, pull_number: int) -> list[PullRequestComment]:
        # This only returns review comments (aka discussion comments) and not normal conversation comments
        if pull_number in self.review_comments_cache:
            return self.review_comments_cache[pull_number]

        all_comments = []
        try:
            pull_request = REPO.get_pull(pull_number)
            all_comments = [comment for comment in pull_request.get_comments()]
        except Exception as e:
            print(f"Failed to list review comments: {e}")

        self.review_comments_cache[pull_number] = all_comments
        return all_comments

    def create(self, comment_body: str, pr_number: int):
        try:
            issue = REPO.get_issue(number=pr_number)

            comment = issue.create_comment(comment_body)

            # Add comment to issueCommentsCache
            if pr_number in self.issue_comments_cache:
                self.issue_comments_cache[pr_number].append(comment)
            else:
                self.issue_comments_cache[pr_number] = [comment]
        except Exception as e:
            print(f"Failed to create comment: {e}")

    def replace(self, body: str, tag: TAGS, pr_number: int):
        try:
            comment = self.find_issue_comment_with_tag(tag, pr_number)
            if comment:
                comment.edit(body)
            else:
                self.create(body, pr_number)
        except Exception as e:
            print(f"Failed to replace comment: {e}")

    def find_issue_comment_with_tag(
        self, tag: TAGS, pr_number: int
    ) -> Optional[IssueComment]:
        try:
            comments = self.list_issue_comments(pr_number)
            for comment in comments:
                if comment.body and tag in comment.body:
                    return comment
            return None
        except Exception as e:
            print(f"Failed to find comment with tag: {e}")
            return None

    def list_issue_comments(self, pr_number: int) -> list[IssueComment]:
        # List issue comments
        if pr_number in self.issue_comments_cache:
            return self.issue_comments_cache[pr_number]

        all_comments = []
        try:
            issue: Issue = REPO.get_issue(number=pr_number)
            comments = [comment for comment in issue.get_comments()]
            all_comments.extend(comments)
        except Exception as e:
            print(f"Failed to list comments: {e}")

        self.issue_comments_cache[pr_number] = all_comments
        return all_comments

    def get_reviewed_commit_ids_block(self, comment_body: str) -> str:
        start = comment_body.find(TAGS.COMMIT_ID_START_TAG)
        end = comment_body.find(TAGS.COMMIT_ID_END_TAG)
        if start == -1 or end == -1:
            return ""
        return comment_body[start : end + len(TAGS.COMMIT_ID_END_TAG)]

    def add_reviewed_commit_id(self, comment_body, commit_id):
        start = comment_body.find(TAGS.COMMIT_ID_START_TAG)
        end = comment_body.find(TAGS.COMMIT_ID_END_TAG)

        if start == -1 or end == -1:
            return f"{comment_body}\n{TAGS.COMMIT_ID_START_TAG}\n<!-- {commit_id} -->\n{TAGS.COMMIT_ID_END_TAG}"

        ids = comment_body[start + len(TAGS.COMMIT_ID_START_TAG) : end]
        return f"{comment_body[:start + len(TAGS.COMMIT_ID_START_TAG)]}{ids}<!-- {commit_id} -->\n{comment_body[end:]}"

    def get_highest_reviewed_commit_id(
        self, commit_ids: list[str], reviewed_commit_ids: list[str]
    ) -> str:
        for i in range(len(commit_ids) - 1, -1, -1):
            if commit_ids[i] in reviewed_commit_ids:
                return commit_ids[i]
        return ""

    def get_all_commit_ids(self) -> list[str]:
        all_commits = []
        try:
            pull = REPO.get_pull(GITHUB_CONTEXT.payload.pull_request.number)
            # Get the commits from the pull request:
            commits = pull.get_commits()
            return [commit.sha for commit in commits]
        except Exception as e:
            print(f"Failed to list commits: {e}")

        return all_commits

    def remove_in_progress_status(self, comment_body: str) -> str:
        # TODO it's not using use it! Maybe check for progress status in existing summarize comment
        start = comment_body.find(TAGS.IN_PROGRESS_START_TAG)
        end = comment_body.find(TAGS.IN_PROGRESS_END_TAG)
        # remove the in-progress status if the marker exists
        # otherwise do nothing
        if start != -1 and end != -1:
            return (
                comment_body[:start]
                + comment_body[end + len(TAGS.IN_PROGRESS_END_TAG) :]
            )
        return comment_body
