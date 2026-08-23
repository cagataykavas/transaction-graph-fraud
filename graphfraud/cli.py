from __future__ import annotations

import argparse
import json
from pathlib import Path

from .domain import Transaction
from .engine import GraphFraudEngine
from .report import render_html_report
from .synthetic import synthetic_transactions


def load_jsonl(path: Path) -> list[Transaction]:
    rows: list[Transaction] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(Transaction(**json.loads(line)))
        except Exception as exc:
            raise ValueError(f"invalid transaction at line {line_number}: {exc}") from exc
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Graph-based transaction fraud reference project")
    parser.add_argument("--input", type=Path, help="optional JSONL transaction file")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-output", type=Path, default=Path("artifacts/analysis.json"))
    parser.add_argument("--html-output", type=Path, default=Path("artifacts/report.html"))
    args = parser.parse_args(argv)

    transactions = load_jsonl(args.input) if args.input else synthetic_transactions(seed=args.seed)
    result = GraphFraudEngine().analyze(transactions)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    render_html_report(result, args.html_output)
    print(json.dumps({
        "transactions": result["transaction_count"],
        "entities": result["entity_count"],
        "findings": len(result["findings"]),
        "json": str(args.json_output),
        "html": str(args.html_output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
