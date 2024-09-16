import json
import os
import time
from typing import Optional

from github_action_utils import notice as info
from mistralai.client import MistralClient

from core.bot import SYSTEM_MESSAGE, AiResponse, Bot, ModelOptions
from core.schemas.limits import TokenLimits
from core.schemas.options import Options


class MistralOptions(ModelOptions):
    def __init__(
        self, model: str = "mistral-small", token_limits: Optional[TokenLimits] = None
    ):
        super().__init__(model, token_limits)


class MistralBot(Bot):
    def __init__(
        self,
        options: Options,
        mistral_options: MistralOptions,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        super().__init__(options, mistral_options)
        if api_key is not None and base_url is not None:
            current_date = time.strftime("%Y-%m-%d")
            system_message = SYSTEM_MESSAGE.format(
                system_message=options.system_message,
                knowledge_cut_off=mistral_options.token_limits.knowledge_cut_off,
                current_date=current_date,
                language=options.language,
            )

            self.api = {
                "system_message": system_message,
                "api_key": api_key,
                "api_org": os.getenv("OPENAI_API_ORG", None),
                "debug": options.debug,
                "max_model_tokens": mistral_options.token_limits.max_tokens,
                "max_response_tokens": mistral_options.token_limits.response_tokens,
                "temperature": options.model_temperature,
                "model": mistral_options.model,
            }
            self.client = MistralClient(
                endpoint=f"https://{base_url}", api_key=self.api["api_key"]
            )
            self.api = {
                "system_message": system_message,
                "api_key": os.getenv("MISTRAL_API_KEY"),
                "debug": options.debug,
                "max_model_tokens": mistral_options.token_limits.max_tokens,
                "max_response_tokens": mistral_options.token_limits.response_tokens,
                "temperature": options.model_temperature,
                "model": mistral_options.model,
            }
        else:
            raise ValueError(
                "Unable to initialize the Mistral API." "Please provide url and api_key"
            )

    def chat(self, message: str, ids: dict[str, dict]) -> AiResponse:
        start = time.time()
        if not message:
            return AiResponse(message="", ids={})

        response = None
        try:
            response = self.client.chat(
                model=self.model_options.model,
                messages=[
                    {"role": "system", "content": self.api["system_message"]},
                    {"role": "user", "content": message},
                ],
                temperature=self.api["temperature"],
                max_tokens=self.api["max_model_tokens"],
                # n=1,
                # stop=None,
                # timeout=self.options.timeout_ms,
                # parent_message_id=ids.get("parentMessageId"),
            )
        except Exception as e:
            info(f"Failed to send message to Mistral AI: {e}, backtrace: {e}")

        end = time.time()
        # TODO check why it's not JSON serializable
        # info(f"response: {json.dumps(response)}")

        info(
            f"Mistral AI sendMessage (including retries) response time: {end - start} ms"
        )

        response_text = ""
        if response is not None:
            info(f"response: {response.choices[0].message.content}")
            response_text = response.choices[0].message.content
        else:
            info("Mistral AI response is null")

        if response_text.startswith("with "):
            response_text = response_text[5:]

        if self.options.debug:
            info(f"Mistral AI responses: {response_text}")

        new_ids = {
            "parentMessageId": response.id if response else None,
            "conversationId": response.id if response else None,
        }

        return AiResponse(message=response_text, ids=new_ids)
