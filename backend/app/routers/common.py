from __future__ import annotations

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from .. import repository as repo
from ..database import get_db
from ..services import engine
from ..services.domain import Params


def scenario(demand: float = Query(0.0, ge=0.0, le=0.5, description="demand increase, 0..0.5"),
             weather: float = Query(0.0, ge=0.0, le=1.0, description="weather severity, 0..1"),
             road: float = Query(0.0, ge=0.0, le=1.0, description="road degradation, 0..1"),
             vehicles: float = Query(1.0, ge=0.5, le=1.0, description="vehicle availability, 0.5..1")) -> Params:
    return Params(demand, weather, road, vehicles)


class Ctx:
    """Per-request context: DB snapshot + scenario-aware engine result."""

    def __init__(self, db: Session = Depends(get_db), p: Params = Depends(scenario)):
        self.db, self.p = db, p
        self.snap = repo.load_snapshot(db)
        self.res = engine.compute(self.snap, p)
