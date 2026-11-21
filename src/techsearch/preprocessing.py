"""Original token positions and lexical identifier aliases."""
from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN = re.compile(
    r"</?[A-Za-z][\w:-]*\s*/?>|[A-Za-z][\w]*(?:\+\+|#)(?!\w)|"
    r"--[\w-]+|===|!==|=>|\.\.\.|(?:>>>|<<|>>|\?\?|\*\*|&&|\|\|)=?|"
    r"(?:\?\.|==|!=|<=|>=|\+\+|--|[+\-*/%^&|]=)|"
    r"[$@\w][\w$]*(?:-[\w$]+)*(?:\.[$\w][\w$]*(?:-[\w$]+)*)*|[=<>+*/!%&|~^?-]",
    re.UNICODE,
)
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@dataclass(frozen=True)
class Token:
    term: str
    start: int
    end: int
    aliases: tuple[str, ...]


def analyze(text):
    for match in TOKEN.finditer(text):
        form = match.group()
        primary = form.casefold()
        aliases = set()
        if form[0].isalnum() or form.startswith(("--", "<", "$", "@")):
            for piece in re.split(r"[._-]", form.strip("<>/ $@-")):
                if piece:
                    aliases.add(piece.casefold())
                    if piece.isidentifier():
                        aliases.update(part.casefold() for part in CAMEL.split(piece))
        yield Token(primary, match.start(), match.end(), tuple(sorted(aliases - {primary, ""})))
