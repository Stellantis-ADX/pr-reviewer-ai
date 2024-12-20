from core.github.context import GithubActionContext
from core.github.github import GITHUB_API

GITHUB_CONTEXT = GithubActionContext()
REPO = GITHUB_API.get_repo(GITHUB_CONTEXT.full_name)


__all__ = ["GITHUB_CONTEXT", "REPO"]
