"""Per-model USD pricing, loaded from `configs/pricing.yaml`.

Cost is never hardcoded at the call site (CLAUDE.md: "Cost comes from a
per-model price table in code" would be the wrong reading here — the spec
names `configs/pricing.yaml` explicitly, see the M2 implementation note in
PROJECT_SPEC.md). `price_for` raises rather than defaulting to zero: a
missing price must be loud, because a silent `$0.00` is indistinguishable
from a correctly-priced free call.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

DEFAULT_PRICING_PATH = Path(__file__).resolve().parents[2] / "configs" / "pricing.yaml"


class ModelPrice(BaseModel):
    """USD price per token, input and output priced separately."""

    input: float
    output: float


class UnknownModelError(LookupError):
    """Raised when `(provider, model)` has no entry in the price table.

    Never caught to fall back to a zero cost — an unpriced model must block
    the call, not silently bill nothing.
    """

    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        super().__init__(
            f"No price entry for provider={provider!r} model={model!r} in "
            f"{DEFAULT_PRICING_PATH}. Add one rather than assuming a cost."
        )


@lru_cache(maxsize=8)
def load_pricing(path: Path | None = None) -> dict[str, dict[str, ModelPrice]]:
    """Load and cache the pricing table at `path` (default: `configs/pricing.yaml`).

    Cached by path so repeated calls (every `ModelClient` dispatch) don't
    re-read and re-parse the YAML file each time.
    """
    resolved = path or DEFAULT_PRICING_PATH
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return {
        provider: {model: ModelPrice(**fields) for model, fields in models.items()}
        for provider, models in raw.items()
    }


def price_for(provider: str, model: str, *, path: Path | None = None) -> ModelPrice:
    """Look up the price for `(provider, model)`.

    Raises `UnknownModelError` if absent.
    """
    table = load_pricing(path)
    try:
        return table[provider][model]
    except KeyError as exc:
        raise UnknownModelError(provider, model) from exc


def cost_for(price: ModelPrice, tokens_in: int, tokens_out: int) -> float:
    """Actual USD cost of a completed call, given its real token counts."""
    return price.input * tokens_in + price.output * tokens_out


def estimate_cost(
    price: ModelPrice, estimated_tokens_in: int, max_tokens: int
) -> float:
    """Worst-case USD cost of a call *before* it is dispatched.

    Prices the output side at `max_tokens` (not an average or a guess) so the
    budget gate in `sul.providers.client` never under-estimates what a call
    could cost.
    """
    return price.input * estimated_tokens_in + price.output * max_tokens
