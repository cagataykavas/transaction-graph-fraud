from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def render_html_report(result: dict[str, Any], output: str | Path) -> Path:
    findings = result.get("findings", [])
    entities = result.get("entities", [])
    finding_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['severity']))}</td>"
        f"<td>{html.escape(str(item['finding_type']))}</td>"
        f"<td>{float(item['score']):.3f}</td>"
        f"<td>{html.escape(', '.join(item['entities']))}</td>"
        f"<td>{html.escape(str(item['explanation']))}</td>"
        "</tr>"
        for item in findings[:30]
    ) or '<tr><td colspan="5">No findings</td></tr>'
    entity_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['entity_id']))}</td>"
        f"<td>{html.escape(str(item['severity']))}</td>"
        f"<td>{float(item['score']):.3f}</td>"
        f"<td>{html.escape(', '.join(item['reasons']))}</td>"
        "</tr>"
        for item in entities[:30]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transaction Graph Fraud Report</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;background:#0b1020;color:#e8ecf4;margin:0;padding:32px}}
main{{max-width:1180px;margin:auto}} h1,h2{{margin:0 0 12px}} .muted{{color:#9aa7bd}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}}
.card{{background:#121a2d;border:1px solid #26324c;border-radius:14px;padding:18px}} .value{{font-size:28px;font-weight:800}}
table{{width:100%;border-collapse:collapse;background:#121a2d;margin:12px 0 30px;border-radius:12px;overflow:hidden}}
th,td{{padding:11px 12px;text-align:left;border-bottom:1px solid #26324c;vertical-align:top}} th{{color:#9fb8ff}}
code{{color:#c7d5ff}} @media(max-width:800px){{.cards{{grid-template-columns:1fr}} body{{padding:16px}}}}
</style></head><body><main>
<p class="muted">Synthetic/public-data reference project</p><h1>Transaction Graph Fraud</h1>
<p class="muted">Graph topology, movement patterns and explainable case prioritization.</p>
<div class="cards"><div class="card"><div class="value">{result.get('transaction_count',0)}</div><div>Transactions</div></div>
<div class="card"><div class="value">{result.get('entity_count',0)}</div><div>Entities</div></div>
<div class="card"><div class="value">{len(findings)}</div><div>Pattern findings</div></div></div>
<h2>Pattern findings</h2><table><thead><tr><th>Severity</th><th>Type</th><th>Score</th><th>Entities</th><th>Explanation</th></tr></thead><tbody>{finding_rows}</tbody></table>
<h2>Ranked entities</h2><table><thead><tr><th>Entity</th><th>Severity</th><th>Score</th><th>Reasons</th></tr></thead><tbody>{entity_rows}</tbody></table>
</main></body></html>"""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path
