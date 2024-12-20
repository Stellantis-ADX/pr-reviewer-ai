from dotenv import load_dotenv

load_dotenv(dotenv_path="test/pull_request_review_comment.env")

from main import debug_context, run

if __name__ == "__main__":
    debug_context()
    run()
