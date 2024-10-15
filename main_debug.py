import asyncio

from dotenv import load_dotenv

from main import debug_context, run

load_dotenv(dotenv_path="test/pull_request.env")

if __name__ == "__main__":
    debug_context()
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()
