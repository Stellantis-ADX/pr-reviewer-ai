import json
import os
import time
from typing import Optional

from github_action_utils import notice as info
from openai import OpenAI, OpenAIError
from tenacity import retry, stop_after_attempt, wait_fixed

from core.bots.bot import SYSTEM_MESSAGE, AiResponse, ModelOptions
from core.schemas.limits import TokenLimits
from core.schemas.options import Options


class OpenAIOptions(ModelOptions):
    def __init__(
        self, model: str = "gpt-3.5-turbo", token_limits: Optional[TokenLimits] = None
    ):
        super().__init__(model, token_limits)


class OpenAiBot:
    def __init__(self, options: Options, openai_options: OpenAIOptions):
        self.api = None
        self.options = options

        if os.getenv("OPENAI_API_KEY"):
            current_date = time.strftime("%Y-%m-%d")
            system_message = SYSTEM_MESSAGE.format(
                system_message=options.system_message,
                knowledge_cut_off=openai_options.token_limits.knowledge_cut_off,
                current_date=current_date,
                language=options.language,
            )

            # TODO: The 'openai.api_base' option isn't read in the client API. You will need to pass it when you instantiate the client, e.g. 'OpenAI(base_url=options.api_base_url)'
            # openai.api_base = options.api_base_url
            self.api = {
                "system_message": system_message,
                "api_key": os.getenv("OPENAI_API_KEY"),
                "api_org": os.getenv("OPENAI_API_ORG", None),
                "debug": options.debug,
                "max_model_tokens": openai_options.token_limits.max_tokens,
                "max_response_tokens": openai_options.token_limits.response_tokens,
                "temperature": options.model_temperature,
                "model": openai_options.model,
            }
            self.client = OpenAI()
        else:
            raise ValueError(
                "Unable to initialize the OpenAI API, 'OPENAI_API_KEY' environment variable is not available"
            )

    def chat(self, message, ids):  # TODO make chat async
        res = ["", {}]
        try:
            res = self.chat_(message, ids)
            return AiResponse.model_validate({"message": res[0], "ids": res[1]})
        except OpenAIError as e:
            info(f"Failed to chat: {e}, backtrace: {e}")
            return AiResponse.model_validate({"message": res[0], "ids": res[1]})

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def chat_(self, message, ids):
        start = time.time()
        if not message:
            return ["", {}]

        response = None
        if self.api:
            opts = {"timeout": self.options.timeout_ms}
            if "parentMessageId" in ids:
                opts["parentMessageId"] = ids["parentMessageId"]
            try:
                response = self.client.chat.completions.create(
                    model=self.api["model"],
                    messages=[
                        {"role": "system", "content": self.api["system_message"]},
                        {"role": "user", "content": message},
                    ],
                    temperature=self.api["temperature"],
                    max_tokens=self.api["max_model_tokens"],
                    n=1,
                    stop=None,
                    **opts,
                )
            except OpenAIError as e:
                info(f"Failed to send message to OpenAI: {e}, backtrace: {e}")

            end = time.time()
            info(f"response: {json.dumps(response)}")
            info(
                f"OpenAI sendMessage (including retries) response time: {end - start} ms"
            )
        else:
            raise RuntimeError("The OpenAI API is not initialized")

        response_text = ""
        if response is not None:
            response_text = response.choices[0].message.content
        else:
            info("OpenAI response is null")

        if response_text.startswith("with "):
            response_text = response_text[5:]

        if self.options.debug:
            info(f"OpenAI responses: {response_text}")

        # TODO check it doesnt work because openai doesnt keep history
        new_ids = {
            "parentMessageId": response.id if response else None,
            "conversationId": response.id if response else None,
        }

        return [response_text, new_ids]
