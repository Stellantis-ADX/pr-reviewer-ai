from typing import Any, Optional

from pydantic import BaseModel


class Ids:
    def __init__(
        self,
        parent_message_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ):
        self.parent_message_id = parent_message_id
        self.conversation_id = conversation_id


class Review(BaseModel):
    start_line: int
    end_line: int
    comment: str = ""

    def __str__(self) -> str:
        lines = "\n".join([f"  {line}" for line in self.comment.split("\n")])
        return (
            f"start_line: {self.start_line}, end_line: {self.end_line}\n"
            f"comment: {lines}"
        )


class ReviewComment(BaseModel):
    path: str
    start_line: int
    end_line: int
    message: str

    def generate_comment_data(self) -> dict[str, Any]:
        comment_data = {"path": self.path, "body": self.message, "line": self.end_line}

        if self.start_line != self.end_line:
            comment_data["start_line"] = self.start_line
            comment_data["start_side"] = "RIGHT"

        return comment_data
