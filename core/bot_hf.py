import json
import time
from typing import Optional

import requests
from github_action_utils import notice as info
from huggingface_hub import InferenceClient

from core.bot import SYSTEM_MESSAGE, AiResponse, Bot, ModelOptions
from core.schemas.limits import TokenLimits
from core.schemas.options import Options
from core.tokenizer import get_token_count
from core.utils import no_ssl_verification


class HFOptions(ModelOptions):
    def __init__(self, model: str, token_limits: Optional[TokenLimits] = None):
        super().__init__(model, token_limits)


def start_pr_reviewer(
    hf_options: HFOptions, options: Options, timeout_start_application: int = 60
) -> dict[str, bool]:
    urls_available = {url: False for url in options.api_base_urls}
    with no_ssl_verification():
        for url in urls_available.keys():
            url_state = (
                f"https://{url}/cmd/state?application=pr-reviewer-{hf_options.model}"
            )
            url_start = (
                f"https://{url}/cmd/start?application=pr-reviewer-{hf_options.model}"
            )
            print("url_state: ", url_state)
            try:
                for retry_number in range(options.retries):
                    response = requests.get(url_state)
                    if response.status_code == 200 and response.json() == "ONLINE":
                        print(f"PR reviewer {hf_options.model} is online")
                        urls_available[url] = True
                        return urls_available
                    # TODO Remove UNKNOWN status when the PR reviewer big will be deployed
                    elif response.json() == "ERROR" or response.json() == "UNKNOWN":
                        print(
                            f"PR reviewer {hf_options.model} is not online (current status is {response.json()}. "
                            f"No available resources to start the application on the cluster. "
                            f"See cluster load: https://atlas.intra.chrysler.com/clusters/metrics_popup"
                        )
                        urls_available[url] = False
                        break  # Break the loop to try the next URL
                    else:
                        print(
                            f"PR reviewer {hf_options.model} is not online (current status is {response.json()},"
                            f" trying to start it (attempt {retry_number+1}/{options.retries})"
                        )
                        requests.get(url_start)
                        print(
                            f"Waiting {timeout_start_application} seconds before checking again"
                        )
                        time.sleep(timeout_start_application)
            except Exception as e:
                print(f"Failed to start PR reviewer {hf_options.model}: {e}")
                urls_available[url] = False

            print(
                f"Failed to start PR reviewer {hf_options.model} after {options.retries} attempts"
            )
            urls_available[url] = False

    return urls_available


class HFBot(Bot):
    def __init__(
        self, options: Options, hf_options: HFOptions, back_up_bot: Optional[Bot] = None
    ):
        super().__init__(options, hf_options)
        self.api = {}
        # TODO temporary solution to not start big model (it's not deployed yet)
        urls_available = (
            {} if hf_options.model == "big" else start_pr_reviewer(hf_options, options)
        )
        api_url = next((k for k, v in urls_available.items() if v), "fake_host")
        # TODO I'll find a way to do it better with backup bot option
        # Right now let's allow api_url be fake_host sometimes
        # It will be handled by the backup bot
        # if api_url is not None:
        current_date = time.strftime("%Y-%m-%d")
        system_message = SYSTEM_MESSAGE.format(
            system_message=options.system_message,
            knowledge_cut_off=hf_options.token_limits.knowledge_cut_off,
            current_date=current_date,
            language=options.language,
        )

        self.api = {
            "system_message": system_message,
            "debug": options.debug,
            "max_model_tokens": hf_options.token_limits.max_tokens,
            "max_response_tokens": hf_options.token_limits.response_tokens,
            "temperature": options.model_temperature,
            "model": hf_options.model,
            "base_url": api_url,
            "light_model_port": options.light_model_port,
            "heavy_model_port": options.heavy_model_port,
        }
        self.back_up_bot = back_up_bot
        # else:
        #     raise ValueError(
        #         "Unable to initialize the HF API. PR reviewer is not online:"
        #         f"See frontend of applications here: https://{api_url} "
        #     )

    def chat(self, message: str, ids: dict[str, dict]) -> AiResponse:
        start = time.time()
        if not message:
            return AiResponse(message="", ids={})

        response = None

        port = (
            self.api["light_model_port"]
            if self.api["model"] == "small"
            else self.api["heavy_model_port"]
        )
        # It could contain port, so we need to remove it
        inference_url = self.api["base_url"].split(":")[0]
        inference_url = f"http://{inference_url}:{port}"
        self.client = InferenceClient(
            inference_url,
            timeout=120,
        )
        print(f"Prompt: {get_token_count(message)} tokens")
        print(f"System_message: {get_token_count(self.api['system_message'])} tokens")
        max_tokens = (
            self.api["max_model_tokens"]
            - get_token_count(message)
            - get_token_count(self.api["system_message"])
        )

        if self.api:
            for attempt in range(1, self.options.retries + 1):
                try:
                    response = self.client.chat_completion(
                        model=inference_url,
                        messages=[
                            {"role": "user", "content": message},
                            {
                                "role": "assistant",
                                "content": self.api["system_message"],
                            },
                        ],
                        temperature=self.api["temperature"],
                        max_tokens=max_tokens,
                        n=1,
                        stop=None,
                    )
                    break

                except requests.exceptions.RequestException as e:
                    if e.response is not None:
                        if e.response.status_code == 504:
                            backoff = 2**attempt
                            info(
                                f"Received 504 Server Error: Gateway Time-out on {inference_url}, "
                                f"retrying in {backoff} seconds\n"
                                f"Retrying...attempt {attempt}/{self.options.retries}"
                            )
                            time.sleep(backoff)
                        else:
                            info(
                                f"Failed to send message to {inference_url}: {e}, backtrace: {e}"
                            )
                            info(f"Retrying...attempt {attempt}/{self.options.retries}")
                except Exception as e:
                    info(
                        f"Failed to send message to {inference_url}: {e}, backtrace: {e}"
                    )

            end = time.time()
            info(f"response: {json.dumps(response)}")
            info(f"AI sendMessage (including retries) response time: {end - start} ms")
        else:
            raise RuntimeError("Cannot chat, the AI API is not initialized")

        response_text = ""
        if response is not None:
            response_text = response.choices[0].message.content
        else:
            info("AI response is null")
        info(
            f"response_text: {response_text};\n "
            f"response_text tokens: {get_token_count(response_text)}"
        )

        if response_text.startswith("with "):
            response_text = response_text[5:]

        new_ids = {
            "parentMessageId": None,
            "conversationId": None,
        }

        if self.back_up_bot is not None and not response_text:
            info(
                f"Using backup bot from Azure -> {self.back_up_bot.model_options.model}"
            )
            return self.back_up_bot.chat(message, ids)

        return AiResponse(message=response_text, ids=new_ids)
