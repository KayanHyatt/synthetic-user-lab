"""FakeProvider: deterministic synthesis, never disk, never network.

Discriminates rather than recites: `(model, messages, response_schema, seed)`
maps to a stable sha256 digest (via `sul.hashing.config_hash`, which
canonicalises with `json.dumps(sort_keys=True, ...)` — never Python's builtin
`hash()`, never set iteration order), and that digest seeds a `random.Random`
that drives a schema-shaped synthesiser. Same inputs -> byte-identical output;
change any one of them -> a different output.

This is deliberately a leaf, not a cassette. Recording/replaying real
provider traffic is `sul.providers.cassette.CassetteTransport`'s job — a
decorator over a *real* provider, not something FakeProvider does. Fusing
the two would mean one key (`sha256(model+prompt+seed)`) trying to serve two
different purposes: a synthesis seed, and a wire-level cache lookup that must
match on the literal HTTP request. See the M2 implementation note in
PROJECT_SPEC.md for why they were split.
"""

from __future__ import annotations

import enum
import random
import string
import types
from typing import Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from sul.hashing import config_hash
from sul.providers.base import Completion, Message, Usage

_WORD_ALPHABET = string.ascii_lowercase


def _seed_rng(
    model: str,
    messages: list[Message],
    schema: type[BaseModel] | None,
    seed: int | None,
) -> random.Random:
    payload = {
        "model": model,
        "messages": [m.model_dump() for m in messages],
        "schema": schema.model_json_schema() if schema is not None else None,
        "seed": seed,
    }
    digest = config_hash(payload)
    return random.Random(digest)


def _numeric_bounds(field: FieldInfo) -> tuple[float | None, float | None]:
    lo: float | None = None
    hi: float | None = None
    for constraint in field.metadata:
        if hasattr(constraint, "ge"):
            lo = constraint.ge
        elif hasattr(constraint, "gt"):
            lo = constraint.gt + 1
        elif hasattr(constraint, "le"):
            hi = constraint.le
        elif hasattr(constraint, "lt"):
            hi = constraint.lt - 1
    return lo, hi


def _string_length(field: FieldInfo) -> tuple[int, int]:
    min_len, max_len = 4, 12
    for constraint in field.metadata:
        if hasattr(constraint, "min_length") and constraint.min_length is not None:
            min_len = constraint.min_length
        if hasattr(constraint, "max_length") and constraint.max_length is not None:
            max_len = constraint.max_length
    if max_len < min_len:
        max_len = min_len
    return min_len, max_len


def _synthesize_word(rng: random.Random, length: int) -> str:
    return "".join(rng.choices(_WORD_ALPHABET, k=length))


def _synthesize(
    annotation: object, rng: random.Random, field: FieldInfo | None = None
) -> object:
    origin = get_origin(annotation)

    if origin is Literal:
        choices = get_args(annotation)
        return rng.choice(choices)

    if origin is Union or origin is types.UnionType:
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if not non_none:
            return None
        return _synthesize(non_none[0], rng, field)

    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return rng.choice(list(annotation)).value

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _synthesize_model(annotation, rng).model_dump(mode="json")

    if origin in (list, set, frozenset):
        args = get_args(annotation)
        item_type = args[0] if args else str
        n = rng.randint(1, 3)
        return [_synthesize(item_type, rng) for _ in range(n)]

    if origin is dict:
        args = get_args(annotation)
        val_type = args[1] if len(args) > 1 else str
        n = rng.randint(1, 2)
        return {f"key_{i}": _synthesize(val_type, rng) for i in range(n)}

    if origin is tuple:
        args = get_args(annotation)
        return [_synthesize(a, rng) for a in args] if args else []

    if annotation is str:
        min_len, max_len = _string_length(field) if field is not None else (4, 12)
        return _synthesize_word(rng, rng.randint(min_len, max_len))

    if annotation is int:
        lo, hi = _numeric_bounds(field) if field is not None else (None, None)
        return rng.randint(
            int(lo) if lo is not None else 0, int(hi) if hi is not None else 1000
        )

    if annotation is float:
        lo, hi = _numeric_bounds(field) if field is not None else (None, None)
        return round(
            rng.uniform(lo if lo is not None else 0.0, hi if hi is not None else 100.0),
            4,
        )

    if annotation is bool:
        return rng.choice([True, False])

    # Unknown/unsupported annotation: fall back to a stable placeholder word
    # rather than raising — a downstream repair turn (see providers.client)
    # is the mechanism for genuinely malformed output, not this synthesiser.
    return _synthesize_word(rng, 8)


def _synthesize_model(model_cls: type[BaseModel], rng: random.Random) -> BaseModel:
    data: dict[str, object] = {}
    for name, field in model_cls.model_fields.items():
        annotation = field.annotation
        data[name] = _synthesize(annotation, rng, field)
    return model_cls(**data)


class FakeProvider:
    """Deterministic, offline LLMProvider.

    Implements `sul.providers.base.LLMProvider`.
    """

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[BaseModel] | None = None,
    ) -> Completion:
        rng = _seed_rng(model, messages, response_schema, seed)

        if response_schema is not None:
            instance = _synthesize_model(response_schema, rng)
            text = instance.model_dump_json()
        else:
            text = "fake-response-" + _synthesize_word(rng, 16)

        tokens_in = sum(len(m.content) for m in messages) // 4 + len(messages) * 4
        # Deterministic, bounded "generation" length: a function of the seed
        # digest, not of wall-clock or randomness outside `rng`.
        tokens_out = min(max_tokens, max(1, len(text) // 4))

        return Completion(
            text=text,
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out),
            model=model,
            stop_reason="end_turn",
        )


__all__ = ["FakeProvider"]
