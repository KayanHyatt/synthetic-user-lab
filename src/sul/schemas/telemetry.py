"""ModelCall boundary schemas."""

from __future__ import annotations

from datetime import datetime

from sul import models
from sul.enums import AgentRole
from sul.schemas.base import ORMModel


class ModelCallCreate(ORMModel):
    run_id: int | None = None
    agent: AgentRole
    provider: str
    model: str
    prompt_hash: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    seed: int | None = None
    cached: bool = False
    template_version: str | None = None

    def to_orm(self) -> models.ModelCall:
        return models.ModelCall(
            run_id=self.run_id,
            agent=self.agent,
            provider=self.provider,
            model=self.model,
            prompt_hash=self.prompt_hash,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            cost_usd=self.cost_usd,
            latency_ms=self.latency_ms,
            seed=self.seed,
            cached=self.cached,
            template_version=self.template_version,
        )


class ModelCallRead(ORMModel):
    id: int
    run_id: int | None
    agent: AgentRole
    provider: str
    model: str
    prompt_hash: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    seed: int | None
    cached: bool
    template_version: str | None
    created_at: datetime
