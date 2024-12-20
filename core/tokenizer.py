import tiktoken


def encode(input_str: str) -> list[int]:
    encoding = tiktoken.get_encoding("cl100k_base")
    return encoding.encode(input_str)


def get_token_count(input_str: str) -> int:
    input_str = input_str.replace("<|endoftext|>", "")
    return len(encode(input_str))
