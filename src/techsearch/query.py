"""Bounded lexer and parser shared by all search modes."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import FIELDS, METADATA
from .indexing import FIELD_ID
from .preprocessing import analyze

MODES = ("keyword", "boolean", "phrase", "prefix", "fuzzy", "semantic", "hybrid", "field")
FIELD = re.compile(r"([A-Za-z]+):")
TAG = re.compile(r"[\w.+#-]{1,45}\Z")
DOTTED_IDENTIFIER = re.compile(r"[\w$]+\.[\w$.]+")
CAMEL_IDENTIFIER = re.compile(r"[a-z][A-Z]")
WORD = re.compile(r"^[\w.-]+$")


class QueryError(ValueError):
    pass


@dataclass(frozen=True)
class Lexeme:
    kind: str
    value: str
    field: str | None = None
    literal: bool = False


@dataclass(frozen=True)
class Atom:
    kind: str
    value: str
    field: str | None = None


@dataclass(frozen=True)
class Operator:
    name: str
    left: Atom | Operator
    right: Atom | Operator | None = None


@dataclass(frozen=True)
class Parsed:
    constraint: Atom | Operator | None
    scoring: tuple[Atom, ...]
    semantic_text: str
    tokens: tuple[Lexeme, ...]


def lex(text, maximum):
    result = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] in "()":
            result.append(Lexeme(text[i], text[i]))
            i += 1
        else:
            field = None
            match = FIELD.match(text, i)
            if match and match[1].lower() in (*FIELDS, *METADATA):
                field = match[1].lower()
                i = match.end()
                if i == len(text) or text[i].isspace() or text[i] in "()":
                    raise QueryError(f"Provide a value for {field}.")
            delimiter = text[i] if text[i] in '"\u0060' else None
            if delimiter:
                i += 1
            pieces = []
            escaped = delimiter is not None
            while i < len(text):
                char = text[i]
                if delimiter and char == delimiter:
                    break
                if not delimiter and (char.isspace() or char in '()"'):
                    break
                if char == "\\":
                    i += 1
                    if i == len(text):
                        raise QueryError("Complete the escaped character.")
                    char = text[i]
                    escaped = True
                pieces.append(char)
                i += 1
            if delimiter:
                if i == len(text):
                    raise QueryError("Close the quoted text.")
                i += 1
            value = "".join(pieces)
            if not value.strip():
                raise QueryError("Provide text between quotes.")
            kind = "phrase" if delimiter == '"' else "word"
            if not escaped and not field and value in {"NOT", "AND", "OR"}:
                kind = value
            elif not escaped and kind == "word" and value.endswith("*") and not value.endswith("**") and len(value) > 1:
                kind, value = "prefix", value[:-1]
            result.append(Lexeme(kind, value, field, escaped))
        if len(result) > maximum:
            raise QueryError(f"Use at most {maximum} query tokens.")
    return tuple(result)


def join(node, op, right):
    return Operator(op, node, right) if node is not None else right


class Parser:
    def __init__(self, tokens, nesting, topics):
        self.tokens = tokens
        self.i = 0
        self.nesting = nesting
        self.topics = topics

    def peek(self):
        return self.tokens[self.i].kind if self.i < len(self.tokens) else None

    def atom(self, token):
        value = token.value
        if token.field in METADATA:
            value = value.casefold()
            if token.field == "source":
                value = {"so": "stackoverflow", "stack-overflow": "stackoverflow", "stack overflow": "stackoverflow"}.get(value, value)
                if value not in {"mdn", "stackoverflow"}:
                    raise QueryError("Source must be mdn or stackoverflow.")
            elif token.field == "topic" and value not in self.topics:
                raise QueryError("Unknown topic. Use the topic names shown in the filter.")
            elif token.field == "tag" and not TAG.fullmatch(value):
                raise QueryError("Provide one valid Stack Overflow tag.")
            if token.kind == "prefix":
                raise QueryError("Use exact values for metadata filters.")
            return Atom("meta", value, token.field)
        terms = list(analyze(value))
        if not terms:
            if token.field or token.kind == "phrase":
                raise QueryError("Provide a searchable token.")
            return Atom("word", value)
        if token.kind == "prefix" and (len(terms) != 1 or len(terms[0].term) < 2 or not WORD.fullmatch(terms[0].term)):
            raise QueryError("A prefix requires at least two word characters and a trailing asterisk.")
        return Atom(token.kind, value, token.field)

    def expression(self, minimum=1, depth=0):
        if depth > self.nesting:
            raise QueryError(f"Use at most {self.nesting} nested expressions.")
        kind = self.peek()
        if kind in (None, "AND", "OR", ")"):
            raise QueryError("Boolean syntax requires a term, NOT, or an opening parenthesis here.")
        token = self.tokens[self.i]
        self.i += 1
        if kind == "NOT":
            left = Operator("NOT", self.expression(3, depth + 1))
        elif kind == "(":
            left = self.expression(1, depth + 1)
            if self.peek() != ")":
                raise QueryError("Close the Boolean parenthesis.")
            self.i += 1
        else:
            left = self.atom(token)
        precedence = {"OR": 1, "AND": 2}
        while precedence.get(self.peek(), 0) >= minimum:
            kind = self.peek()
            self.i += 1
            left = Operator(kind, left, self.expression(precedence[kind] + 1, depth))
        return left


def positives(node, negated=False):
    if isinstance(node, Atom):
        if not negated and node.kind != "meta":
            yield node
    elif node.name == "NOT":
        yield from positives(node.left, not negated)
    else:
        yield from positives(node.left, negated)
        yield from positives(node.right, negated)


def parse(text, mode, settings, topics):
    """Separate hard constraints from the terms used for scoring."""
    if len(text) > settings["query_length"]:
        raise QueryError(f"Use at most {settings['query_length']} characters.")
    tokens = lex(text, settings["query_tokens"])
    parser = Parser(tokens, settings["nesting"], topics)
    if mode == "boolean":
        if not tokens:
            raise QueryError("Enter a Boolean expression.")
        root = parser.expression()
        if parser.peek() is not None:
            raise QueryError("Join Boolean operands with uppercase AND or OR.")
        scoring = tuple(positives(root))
        return Parsed(root, scoring, " ".join(atom.value for atom in scoring), tokens)
    atoms = []
    for token in tokens:
        if token.kind in ("(", ")"):
            continue
        if token.kind in {"AND", "OR", "NOT"}:
            token = Lexeme("word", token.value)
        atoms.append(parser.atom(token))
    if mode == "phrase":
        loose = [atom for atom in atoms if atom.kind == "word" and not atom.field]
        if loose:
            atoms = [atom for atom in atoms if atom not in loose]
            atoms.append(Atom("phrase", " ".join(atom.value for atom in loose)))
    if mode == "prefix" and not any(atom.kind == "prefix" for atom in atoms):
        raise QueryError("Add a trailing asterisk to the prefix, for example querySel*.")
    if mode == "field" and not any(atom.field for atom in atoms):
        raise QueryError("Specify a field, for example title:Promise.all or source:mdn.")
    constraint, scoring = None, []
    for atom in atoms:
        if atom.field or atom.kind in {"phrase", "prefix"}:
            constraint = join(constraint, "AND", atom)
        if atom.kind != "meta":
            scoring.append(atom)
    if not scoring and constraint is None:
        raise QueryError("Enter search text or pick a filter.")
    return Parsed(constraint, tuple(scoring), " ".join(atom.value for atom in scoring), tokens)


def edit_distance(first, second, bound):
    """Find the minimum insertions, deletions and substitutions within a bound."""
    if abs(len(first) - len(second)) > bound:
        return bound + 1
    previous = list(range(len(second) + 1))
    for first_index, first_char in enumerate(first, 1):
        row = [first_index]
        for second_index, second_char in enumerate(second, 1):
            insert = row[second_index - 1] + 1
            delete = previous[second_index] + 1
            replace = previous[second_index - 1] + (first_char != second_char)
            row.append(min(insert, delete, replace))
        if min(row) > bound:
            return bound + 1
        previous = row
    return previous[-1]


class Matcher:
    def __init__(self, index, metadata, eligible, settings):
        self.index = index
        self.metadata = metadata
        self.eligible = eligible
        self.settings = settings
        self.expansions = {}

    def prefix(self, value, field=None):
        term = next(analyze(value)).term
        key = ("prefix", term, field)
        if key not in self.expansions:
            limit = self.settings["expansion"]
            if field is None:
                found = self.index.prefix(term, limit + 1)
            else:
                scan_limit = self.settings["vocabulary_scan"]
                candidates = self.index.prefix(term, scan_limit + 1)
                if len(candidates) > scan_limit:
                    raise QueryError(f"Prefix {value!r} exceeds the vocabulary scan limit. Use a longer prefix.")
                found = []
                for candidate in candidates:
                    if self.docs(candidate, FIELD_ID[field]):
                        found.append(candidate)
                        if len(found) > limit:
                            break
            if len(found) > limit:
                raise QueryError(f"Prefix {value!r} matches more than {limit} terms. Use a longer prefix.")
            self.expansions[key] = [(candidate, 1.0) for candidate in found]
        return self.expansions[key]

    def fuzzy(self, term):
        if ("fuzzy", term, None) in self.expansions:
            return self.expansions["fuzzy", term, None]
        if len(term) < 5 or len(term) > 35 or not term.replace(".", "").isalpha() or self.index.df(term):
            return [(term, 1.0)]
        bound = 1 if len(term) <= 7 else 2
        candidates = []
        budget = self.settings["vocabulary_scan"]
        for candidate, df in self.index.vocabulary(len(term) - bound, len(term) + bound, budget):
            if candidate.count(".") != term.count("."):
                continue
            distance = edit_distance(term, candidate, bound)
            if distance <= bound:
                candidates.append((distance, -df, candidate))
        chosen = sorted(candidates)[:self.settings["expansion"]]
        result = [(term, 1.0)] + [(candidate, 1 / (distance + 2)) for distance, _, candidate in chosen]
        self.expansions["fuzzy", term, None] = result
        return result

    def match(self, node):
        """Return eligible document IDs satisfying a Boolean tree or one constraint."""
        if node is None:
            return set(self.eligible)
        if isinstance(node, Operator):
            left = self.match(node.left)
            if node.name == "NOT":
                return self.eligible - left
            right = self.match(node.right)
            return left & right if node.name == "AND" else left | right
        if node.kind == "meta":
            return self.eligible & self.metadata[node.field].get(node.value, set())
        field = FIELD_ID.get(node.field)
        if node.kind == "prefix":
            documents = set()
            for term, _weight in self.prefix(node.value, node.field):
                documents.update(self.docs(term, field))
            return documents
        terms = [token.term for token in analyze(node.value)]
        if not terms:
            return set()
        if node.kind == "phrase":
            return self.phrase_documents(terms, field)
        return set.intersection(*(self.docs(term, field) for term in terms))

    def phrase_documents(self, terms, requested_field):
        """Match consecutive original tokens within the same field and segment."""
        posting_lists = [self.index.posting(term)[2] for term in terms]
        candidates = self.eligible.intersection(*(set(postings) for postings in posting_lists))
        return {doc for doc in candidates if phrase_starts(posting_lists, doc, requested_field)}

    def docs(self, term, field):
        postings = self.index.posting(term)[2]
        return {document_id for document_id, fields in postings.items()
                if document_id in self.eligible and (field is None or field in fields)}

    def scoring(self, atoms, fuzzy=False):
        """Accumulate weights by term and optional field, expanding supported atoms."""
        terms = {}
        for atom in atoms:
            field = FIELD_ID.get(atom.field)
            if atom.kind == "prefix":
                candidates = self.prefix(atom.value, atom.field)
            else:
                candidates = []
                expand_spelling = fuzzy and not atom.field and atom.kind == "word"
                for token in analyze(atom.value):
                    if expand_spelling:
                        candidates.extend(self.fuzzy(token.term))
                    else:
                        candidates.append((token.term, 1.0))
            for term, weight in candidates:
                terms[term, field] = terms.get((term, field), 0) + weight
        if len(terms) > self.settings["query_tokens"] + 3 * self.settings["expansion"]:
            raise QueryError("Combined expansions exceed the term budget. Use fewer or more specific prefixes or spelling variants.")
        return terms


def phrase_starts(posting_lists, document_id, requested_field):
    """Return the original (field, segment, position) starts of the phrase."""
    common_starts = None
    for offset, postings in enumerate(posting_lists):
        starts = {
            (field, segment, position - offset)
            for field, positions in postings.get(document_id, {}).items()
            if requested_field is None or field == requested_field
            for segment, position, _start, _end, original in positions if original
        }
        if common_starts is None:
            common_starts = starts
        else:
            common_starts.intersection_update(starts)
        if not common_starts:
            break
    return common_starts or set()
