"""The budget kill switch: a pre-call gate, not a post-hoc tally.

The spec places this in M4 (PROJECT_SPEC.md §M4: "the runner refuses to
start a call that would exceed it"), but it lives in the shared call path
from M2 onward — see the M2 implementation note — so every provider is
covered from the moment providers exist, and M4's runner only has to supply
the ceiling.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from sul.models import ModelCall, Run
from sul.providers.base import ProviderError


class BudgetExceeded(ProviderError):
    """Raised before dispatch when spend-so-far + this call's worst-case
    estimate would exceed `max_cost_usd`. The provider is never invoked.
    """

    def __init__(
        self, study_id: int, spent: float, estimate: float, max_cost_usd: float
    ) -> None:
        self.study_id = study_id
        self.spent = spent
        self.estimate = estimate
        self.max_cost_usd = max_cost_usd
        super().__init__(
            f"Study {study_id}: spent ${spent:.6f} + estimated ${estimate:.6f} "
            f"would exceed budget ${max_cost_usd:.6f}; call blocked before dispatch."
        )


class BudgetGuard:
    """Pre-call budget gate for one study.

    `check()` must be called, and must raise, *before* the provider is
    dispatched — never after. See `sul.providers.client.ModelClient`, the
    only place this is called from.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        study_id: int,
        max_cost_usd: float,
    ) -> None:
        self._session_factory = session_factory
        self.study_id = study_id
        self.max_cost_usd = max_cost_usd

    def spent(self) -> float:
        """Sum of `ModelCall.cost_usd` attributed to this study via `Run.study_id`.

        `ModelCall.run_id` is nullable (the Analyst writes calls with no
        `Turn`), but the Analyst always sets `run_id` — see the M1
        implementation note on `ModelCall.run_id` / `.agent` — so this join
        never silently drops Analyst spend.
        """
        with self._session_factory() as session:
            total = session.execute(
                select(func.coalesce(func.sum(ModelCall.cost_usd), 0.0))
                .select_from(ModelCall)
                .join(Run, Run.id == ModelCall.run_id)
                .where(Run.study_id == self.study_id)
            ).scalar_one()
        return float(total)

    def check(self, estimate: float) -> None:
        """Raise `BudgetExceeded` if `spent() + estimate` would exceed the ceiling."""
        spent = self.spent()
        if spent + estimate > self.max_cost_usd:
            raise BudgetExceeded(self.study_id, spent, estimate, self.max_cost_usd)


__all__ = ["BudgetExceeded", "BudgetGuard"]
