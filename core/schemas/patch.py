from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterator, Tuple

from box import Box
from pydantic import BaseModel, Field, computed_field

if TYPE_CHECKING:  # a hack to avoid circular imports, when we ONLY want to type hint
    # https://peps.python.org/pep-0563/#runtime-annotation-resolution-and-type-checking
    from core.commenter import GithubCommentManager
    from core.schemas.comment_chains import CommentChains
    from core.schemas.files import FilteredFile

from core.schemas.options import Options
from core.tokenizer import get_token_count


class Patch(BaseModel):
    start_line: int
    end_line: int
    patch_str: str

    @computed_field
    @property
    def tokens(self) -> int:
        return get_token_count(self.patch_str)

    def __str__(self) -> str:
        return "\n".join([f"{line}" for line in self.patch_str.split("\n")])


class Patches(BaseModel):
    items: list[Patch]
    items_str: str = Field(serialization_alias="patches", default="")

    class Config:
        arbitrary_types_allowed = True

    @computed_field
    @property
    def items_tokens(self) -> list[int]:
        return [patch.tokens for patch in self.items]

    def __str__(self) -> str:
        return "\n".join([f"{patch}" for patch in self.items])

    def compute_patch_packing_limit(self, tokens: int, options: Options) -> int:
        patches_to_pack = 0
        for item_token in self.items_tokens:
            if tokens + item_token > options.heavy_token_limits.request_tokens:
                print(
                    f"only packing {patches_to_pack} / {len(self.items)} patches,"
                    f" tokens: {tokens} / {options.heavy_token_limits.request_tokens}"
                )
                break
            tokens += item_token
            patches_to_pack += 1
        return patches_to_pack

    def tokens_count_wrt_packing_limit(self, patch_packing_limit: int) -> int:
        return sum(self.items_tokens[:patch_packing_limit])

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[Patch]:
        return iter(self.items)

    def __getitem__(self, index: int) -> Patch:
        return self.items[index]


def pack_patches_with_associated_comments_chains(
    file: FilteredFile,
    patch_packing_limit: int,
    commenter: GithubCommentManager,
    tokens: int,
    options: Options,
) -> str:
    patches_packed = 0
    patches_comments_chains: list[Tuple[Patch, CommentChains | str]] = (
        file.compute_patch_associated_comment_chains(commenter)
    )
    patches_str = ""

    for patch, comment_chains in patches_comments_chains:
        if patches_packed >= patch_packing_limit:
            print(
                f"unable to pack more patches into this request, packed: {patches_packed},"
                f" total patches: {len(file.patches)}, skipping."
            )
            break

        patches_packed += 1

        if comment_chains is None:
            patches_str += f"\n{patch.patch_str}\n"
            continue

        if tokens + comment_chains.tokens < options.heavy_token_limits.request_tokens:
            patches_str += f"\n---comment_chains---\n```\n{comment_chains}\n```\n"
            patches_str += f"\n{patch.patch_str}\n"
            tokens += comment_chains.tokens

        patches_str += "\n---end_change_section---\n"

    return patches_str


def split_patch(patch: str) -> list[str]:
    if patch is None:
        return []
    # TODO verify if this function is correct
    pattern = re.compile(r"(^@@ -(\d+),(\d+) \+(\d+),(\d+) @@).*$", re.MULTILINE)

    result = []
    last = -1
    match = pattern.search(patch)
    while match is not None:
        if last == -1:
            last = match.start()
        else:
            result.append(patch[last : match.start()])
            last = match.start()
        match = pattern.search(patch, match.end())

    if last != -1:
        result.append(patch[last:])

    return result


def patch_start_end_line(patch: str) -> dict[str, dict[str, int]] | None:
    pattern = r"(^@@ -(\d+),(\d+) \+(\d+),(\d+) @@)"
    match = re.search(pattern, patch, re.MULTILINE)
    if match:
        old_begin = int(match.group(2))
        old_diff = int(match.group(3))
        new_begin = int(match.group(4))
        new_diff = int(match.group(5))
        return {
            "old_hunk": {"start_line": old_begin, "end_line": old_begin + old_diff - 1},
            "new_hunk": {"start_line": new_begin, "end_line": new_begin + new_diff - 1},
        }
    else:
        return None


def parse_patch(patch: str, patch_lines: Box):

    old_hunk_lines = []
    new_hunk_lines = []

    new_line = patch_lines.new_hunk.start_line

    lines = patch.split("\n")[1:]  # Skip the @@ line

    # Remove the last line if it's empty
    if lines and lines[-1] == "":
        lines.pop()

    # Skip annotations for the first 3 and last 3 lines, it's a context line which provided by Github
    skip_start = 3
    skip_end = 3

    current_line = 0

    removal_only = not any(line.startswith("+") for line in lines)

    for line in lines:
        current_line += 1
        if line.startswith("-"):
            old_hunk_lines.append(line[1:])
        elif line.startswith("+"):
            new_hunk_lines.append(f"{new_line}: {line[1:]}")
            new_line += 1
        else:
            # context line
            old_hunk_lines.append(line)
            if removal_only or (skip_start < current_line <= len(lines) - skip_end):
                new_hunk_lines.append(f"{new_line}: {line}")
            else:
                new_hunk_lines.append(line)
            new_line += 1

    return {
        "old_hunk": "\n".join(old_hunk_lines),
        "new_hunk": "\n".join(new_hunk_lines),
    }
