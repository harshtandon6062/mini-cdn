"""Access policy: which roles may reach which paths. Default deny.

Rules come from a JSON file (policy.json), for example:
    {"path": "/api/*", "roles": ["engineer", "admin"]}  prefix rule (ends with "*")
    {"path": "/about", "roles": ["*"]}                  exact rule; role "*" = any logged-in user

For a request we pick the most specific (longest) matching rule. If no rule
matches, the request is denied: anything not explicitly allowed is blocked.
"""

import json
from dataclasses import dataclass
from pathlib import Path

ANY_ROLE = "*"


@dataclass(frozen=True)
class Rule:
    path: str
    roles: frozenset[str]

    def matches(self, path: str) -> bool:
        """Prefix match for rules ending in "*" (e.g. /api/*), exact match otherwise."""
        if self.path.endswith("*"):
            return path.startswith(self.path[:-1])
        return path == self.path


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class AccessPolicy:
    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules

    @classmethod
    def from_file(cls, path: str | Path) -> "AccessPolicy":
        """Load rules from a JSON policy file."""
        data = json.loads(Path(path).read_text())
        return cls([Rule(r["path"], frozenset(r["roles"])) for r in data["rules"]])

    def check(self, path: str, role: str) -> Decision:
        """Decide if `role` may access `path`, and say why."""
        if any(segment in (".", "..") for segment in path.split("/")):
            return Decision(False, "path traversal is not allowed")
        matching = [rule for rule in self.rules if rule.matches(path)]
        if not matching:
            return Decision(False, "no policy rule matches (default deny)")
        rule = max(matching, key=lambda r: len(r.path))  # most specific rule wins
        if ANY_ROLE in rule.roles or role in rule.roles:
            return Decision(True, f"rule {rule.path} allows role {role}")
        return Decision(False, f"rule {rule.path} does not allow role {role}")
