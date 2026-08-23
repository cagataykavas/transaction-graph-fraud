from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from graphfraud.domain import Transaction
from graphfraud.engine import GraphFraudEngine
from graphfraud.synthetic import synthetic_transactions

app = FastAPI(title="Transaction Graph Fraud", version="1.0.0")
ENGINE = GraphFraudEngine()


class TransactionPayload(BaseModel):
    transaction_id: str
    src: str
    dst: str
    amount: float = Field(ge=0)
    timestamp: float
    currency: str = "USD"
    channel: str = "bank_transfer"
    country_src: str = "US"
    country_dst: str = "US"

    def to_domain(self) -> Transaction:
        return Transaction(**self.model_dump())


class AnalysisRequest(BaseModel):
    transactions: list[TransactionPayload] = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/demo")
def demo(seed: int = 42) -> dict[str, object]:
    return ENGINE.analyze(synthetic_transactions(seed=seed))


@app.post("/analyze")
def analyze(payload: AnalysisRequest) -> dict[str, object]:
    return ENGINE.analyze([row.to_domain() for row in payload.transactions])
