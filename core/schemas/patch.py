import re

from box import Box
from pydantic import BaseModel


class Patch(BaseModel):
    start_line: int
    end_line: int
    patch_str: str

    def __str__(self) -> str:
        return "\n".join([f"{line}" for line in self.patch_str.split("\n")])


# TODO do the functions part of the class


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
