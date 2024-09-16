from fnmatch import fnmatch
from typing import List, Optional, Tuple

from github_action_utils import notice as info

from core.schemas.limits import TokenLimits


class Options:
    def __init__(
        self,
        debug: bool,
        disable_review: bool,
        disable_release_notes: bool,
        max_files: str = "0",
        review_simple_changes: bool = False,
        review_comment_lgtm: bool = False,
        path_filters: Optional[str] = None,
        system_message: str = "",
        light_model_name: str = "small",
        light_model_port: str = "44901",
        heavy_model_port: str = "44902",
        heavy_model_name: str = "big",
        model_temperature: str = "0.0",
        retries: str = "3",
        timeout_ms: str = "120000",
        concurrency_limit: str = "6",
        github_concurrency_limit: str = "6",
        api_base_urls: list[str] | str = None,
        language: str = "en-US",
        allow_empty_review: bool = False,
        less_spammy: bool = False,
        api_base_url_azure: str = "",
        light_model_name_azure: str = "",
        light_model_token_azure: str = "",
        heavy_model_name_azure: str = "",
        heavy_model_token_azure: str = "",
    ):
        self.debug = debug
        self.disable_review = disable_review
        self.disable_release_notes = disable_release_notes
        self.max_files = int(max_files)
        self.review_simple_changes = review_simple_changes
        self.review_comment_lgtm = review_comment_lgtm
        self.path_filters = PathFilter(path_filters)
        self.system_message = system_message
        self.light_model_name = light_model_name
        self.heavy_model_name = heavy_model_name
        self.model_temperature = float(model_temperature)
        self.retries = int(retries)
        self.timeout_ms = int(timeout_ms)
        self.concurrency_limit = int(concurrency_limit)
        self.github_concurrency_limit = int(github_concurrency_limit)
        self.light_token_limits = TokenLimits(light_model_name)
        self.heavy_token_limits = TokenLimits(heavy_model_name)
        self.api_base_urls = (
            [""]
            if api_base_urls is None
            else api_base_urls.split("\n")[:-1]  # remove last empty string
        )
        self.language = language
        self.light_model_port = light_model_port
        self.heavy_model_port = heavy_model_port
        self.allow_empty_review = allow_empty_review
        self.less_spammy = less_spammy
        # Azure
        self.api_base_url_azure = (
            [""]
            if api_base_url_azure is None
            else api_base_url_azure.split("\n")[:-1]  # remove last empty string
        )
        self.light_model_name_azure = light_model_name_azure
        self.light_model_token_azure = light_model_token_azure
        self.heavy_model_name_azure = heavy_model_name_azure
        self.heavy_model_token_azure = heavy_model_token_azure
        self.light_token_limits_azure = TokenLimits(light_model_name_azure)
        self.heavy_token_limits_azure = TokenLimits(heavy_model_name_azure)

    def print(self) -> None:
        info(f"debug: {self.debug}")
        info(f"disable_review: {self.disable_review}")
        info(f"disable_release_notes: {self.disable_release_notes}")
        info(f"max_files: {self.max_files}")
        info(f"review_simple_changes: {self.review_simple_changes}")
        info(f"review_comment_lgtm: {self.review_comment_lgtm}")
        info(f"path_filters: {self.path_filters}")
        info(f"system_message: {self.system_message}")
        info(f"light_model_name: {self.light_model_name}")
        info(f"heavy_model_name: {self.heavy_model_name}")
        info(f"model_temperature: {self.model_temperature}")
        info(f"retries: {self.retries}")
        info(f"timeout_ms: {self.timeout_ms}")
        info(f"concurrency_limit: {self.concurrency_limit}")
        info(f"github_concurrency_limit: {self.github_concurrency_limit}")
        info(f"summary_token_limits: {self.light_token_limits}")
        info(f"review_token_limits: {self.heavy_token_limits}")
        info(f"api_base_urls: {self.api_base_urls}")
        info(f"language: {self.language}")
        info(f"light_model_port: {self.light_model_port}")
        info(f"heavy_model_port: {self.heavy_model_port}")
        info(f"allow_empty_review: {self.allow_empty_review}")
        info(f"less_spammy: {self.less_spammy}")
        info(f"api_base_url_azure: {self.api_base_url_azure}")
        info(f"light_model_name_azure: {self.light_model_name_azure}")
        if self.light_model_token_azure:
            info(f"light_model_token_azure: token: ****************")
        else:
            info(f"heavy_model_token_azure: {self.light_model_token_azure}")
        info(f"heavy_model_name_azure: {self.heavy_model_name_azure}")
        if self.heavy_model_token_azure:
            info(f"heavy_model_token_azure: token: ****************")
        else:
            info(f"heavy_model_token_azure: {self.heavy_model_token_azure}")

    def check_path(self, path: str) -> bool:
        ok = self.path_filters.check(path)
        info(f"checking path: {path} => {ok}")
        return ok


class PathFilter:
    def __init__(self, rules: str | None = None):
        self.rules: List[Tuple[str, bool]] = []
        if rules is not None:
            for rule in rules.split("\n"):
                rule = rule.strip()  # check if need
                if rule:
                    if rule.startswith("!"):
                        self.rules.append((rule[1:], True))  # Exclusion rule
                    else:
                        self.rules.append((rule, False))  # Inclusion rule

    def check(self, path: str) -> bool:
        if not self.rules:
            return True

        included = False
        excluded = False
        inclusion_rule_exists = False

        for rule, exclude in self.rules:
            if fnmatch(path, rule):
                if exclude:
                    excluded = True
                else:
                    included = True
            if not exclude:
                inclusion_rule_exists = True

        return (not inclusion_rule_exists or included) and not excluded
