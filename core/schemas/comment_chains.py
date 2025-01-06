from pydantic import BaseModel, computed_field, model_validator
from typing_extensions import Self

from core.tokenizer import get_token_count


class CommentChain(BaseModel):
    start_line: int | None
    end_line: int
    top_level_comment_id: int
    comment: str = ""

    @model_validator(mode='after')
    def check_one_line_comment(self) -> Self:
        # If the comment is only one line, set the start_line to the end_line
        if self.start_line is None:
            self.start_line = self.end_line
        return self

    def __str__(self) -> str:
        lines = "\n".join([f"  {line}" for line in self.comment.split("\n")])
        return (
            f"start_line: {self.start_line}, end_line: {self.end_line}\n"
            f"comment: {lines}"
        )


class CommentChains(BaseModel):
    items: list[CommentChain]

    @computed_field
    @property
    def tokens(self) -> int:
        return get_token_count(str(self))

    def __len__(self) -> int:
        return len(self.items)

    def __str__(self) -> str:
        all_chains = ""
        for chain_num, chain in enumerate(self.items, 1):
            all_chains += f"Conversation Chain {chain_num}:\n{chain}\n---\n"
        return all_chains
