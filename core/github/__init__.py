from core.github.context import GITHUB_ACTION_CONTEXT
from core.github.github import GITHUB_API

github_context = GITHUB_ACTION_CONTEXT
REPO = GITHUB_API.get_repo(github_context.payload.repository.full_name)


__all__ = ["github_context", "REPO"]
