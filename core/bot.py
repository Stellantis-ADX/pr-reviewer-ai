from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from core.schemas.limits import TokenLimits
from core.schemas.options import Options

SYSTEM_MESSAGE = (
    "{system_message} Knowledge cutoff: {knowledge_cut_off} "
    "Current date: {current_date} "
    "IMPORTANT: Entire response must be in the language with ISO code: {language}"
)


class Ids(BaseModel):
    conversationId: Optional[str]
    parentMessageId: Optional[str]

    def __str__(self) -> str:
        return f"conversationId: {self.conversationId}, parentMessageId: {self.parentMessageId} \n"


class AiResponse(BaseModel):
    message: str
    ids: Ids

    def __str__(self) -> str:
        return str(self.ids) + "\n".join(
            [f"{line}" for line in self.message.split("\n")]
        )


class ModelOptions(ABC):
    @abstractmethod
    def __init__(self, model: str, token_limits: Optional[TokenLimits]):
        self.model = model
        if token_limits is not None:
            self.token_limits = token_limits
        else:
            self.token_limits = TokenLimits(model)


class Bot(ABC):
    def __init__(self, options: Options, model_options: ModelOptions):
        self.options = options
        self.model_options = model_options

    @abstractmethod
    def chat(self, message, ids):
        pass
