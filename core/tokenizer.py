import tiktoken


def encode(input_str):
    encoding = tiktoken.get_encoding("cl100k_base")
    return encoding.encode(input_str)


def get_token_count(input_str):
    input_str = input_str.replace("<|endoftext|>", "")
    return len(encode(input_str))


#
#
# def encode(input_str):
#     # Tokenize the input string
#     tokenizer = AutoTokenizer.from_pretrained("mistralai/Mixtral-8x22B-Instruct-v0.1")
#     tokens = tokenizer.encode(input_str)
#     return tokens
#
# # Function to get the token count of a given input string
# def get_token_count(input_str):
#     # Tokenize the input string and return the number of tokens
#     input_str = input_str.replace("<|endoftext|>", "")
#     tokens = encode(input_str)
#     return len(tokens)
