import os

import github

# Get the GitHub token from environment variables or input
token = os.getenv("GITHUB_TOKEN")
GITHUB_API = github.Github(token, base_url=os.getenv("GITHUB_API_URL"))

# Disable debug logging
# github.enable_console_debug_logging()
