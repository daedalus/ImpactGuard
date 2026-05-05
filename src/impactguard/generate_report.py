import json
from typing import Any


def color(level: str) -> str:
    return {
        "HIGH": "#ff4d4f",
        "MEDIUM": "#faad14",
        "LOW": "#52c41a",
        "UNKNOWN": "#d9d9d9",
    }.get(level, "#d9d9d9")


def _summary_stats(report_data: list[dict[str, Any]]) -> dict[str, int]:
    """Count items by risk level."""
    stats: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for item in report_data:
        risk_level = item.get("risk", "UNKNOWN")
        stats[risk_level] = stats.get(risk_level, 0) + 1
    return stats


def generate_html(report_data: list[dict[str, Any]]) -> str:
    stats = _summary_stats(report_data)
    total = len(report_data)

    html: list[str] = []
    html.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>API Risk Report</title>
    <style>
        body { font-family: sans-serif; margin: 20px; background: #f5f5f5; }
        h1 { color: #333; }
        .summary { display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }
        .badge {
            padding: 8px 18px; border-radius: 6px; font-weight: bold;
            color: #fff; cursor: pointer; user-select: none;
        }
        .badge.HIGH   { background: #ff4d4f; }
        .badge.MEDIUM { background: #faad14; }
        .badge.LOW    { background: #52c41a; }
        .badge.UNKNOWN{ background: #999; }
        .badge.ALL    { background: #1890ff; }
        .badge.active { outline: 3px solid #000; }
        .controls { margin: 12px 0; display: flex; gap: 12px; align-items: center; }
        .controls input {
            padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px;
            font-size: 14px; width: 260px;
        }
        table {
            width: 100%; border-collapse: collapse; background: #fff;
            box-shadow: 0 1px 4px rgba(0,0,0,.1);
        }
        th {
            background: #333; color: #fff; padding: 10px 14px;
            text-align: left; cursor: pointer; white-space: nowrap;
        }
        th:hover { background: #555; }
        th .sort-indicator { margin-left: 4px; opacity: .6; }
        td { padding: 8px 14px; border-bottom: 1px solid #eee; vertical-align: top; }
        tr:hover td { background: #fafafa; }
        .risk-HIGH    { color: #cf1322; font-weight: bold; }
        .risk-MEDIUM  { color: #d46b08; font-weight: bold; }
        .risk-LOW     { color: #389e0d; font-weight: bold; }
        .risk-UNKNOWN { color: #666; font-weight: bold; }
        .tag-transitive { font-size: 11px; color: #888; margin-left: 6px; }
        pre { background: #111; color: #eee; padding: 10px; font-size: 12px;
              overflow: auto; max-height: 200px; }
        .no-results { padding: 20px; text-align: center; color: #888; }
    </style>
</head>
<body>
    <h1>API Risk Report</h1>
""")

    # Summary badges
    html.append('<div class="summary">')
    html.append(
        f'<span class="badge ALL active" onclick="filterLevel(\'ALL\')">All ({total})</span>'
    )
    for level in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        count = stats.get(level, 0)
        html.append(
            f'<span class="badge {level}" onclick="filterLevel(\'{level}\')">'
            f'{level} ({count})</span>'
        )
    html.append("</div>")

    # Search box
    html.append("""
    <div class="controls">
        <input id="search" type="text" placeholder="Search function name or change type…"
               oninput="applyFilters()">
    </div>
""")

    # Table
    html.append("""
    <table id="report-table">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Risk<span class="sort-indicator">⇅</span></th>
                <th onclick="sortTable(1)">Function<span class="sort-indicator">⇅</span></th>
                <th onclick="sortTable(2)">Change<span class="sort-indicator">⇅</span></th>
                <th onclick="sortTable(3)">Exposure<span class="sort-indicator">⇅</span></th>
                <th onclick="sortTable(4)">Confidence<span class="sort-indicator">⇅</span></th>
                <th>Details / Fixes</th>
            </tr>
        </thead>
        <tbody id="report-body">
""")

    for item in report_data:
        level = item.get("risk", "UNKNOWN")
        func = item.get("function", "unknown")
        change = item.get("change", "")
        exp = item.get("exposure", 0)
        conf = item.get("confidence", 0)
        details = item.get("details", "")
        fixes = item.get("fixes", [])
        patches = item.get("patches", [])
        is_transitive = item.get("transitive", False)
        transitive_tag = (
            '<span class="tag-transitive">(indirect)</span>' if is_transitive else ""
        )

        details_html = details or ""
        if fixes:
            details_html += "<ul>" + "".join(f"<li>{f}</li>" for f in fixes) + "</ul>"
        if patches:
            for p in patches:
                details_html += f"<pre>{p}</pre>"

        html.append(
            f"""        <tr data-risk="{level}" data-text="{func.lower()} {change.lower()}">
            <td><span class="risk-{level}">{level}</span></td>
            <td>{func}{transitive_tag}</td>
            <td>{change}</td>
            <td>{exp:.2%}</td>
            <td>{conf:.2f}</td>
            <td>{details_html}</td>
        </tr>"""
        )

    html.append("""
        </tbody>
    </table>
    <p id="no-results" class="no-results" style="display:none">No matching entries.</p>

    <script>
    let activeLevel = 'ALL';
    let sortCol = -1, sortAsc = true;

    function filterLevel(level) {
        activeLevel = level;
        document.querySelectorAll('.badge').forEach(b => b.classList.remove('active'));
        const el = document.querySelector(`.badge.${level === 'ALL' ? 'ALL' : level}`);
        if (el) el.classList.add('active');
        applyFilters();
    }

    function applyFilters() {
        const query = document.getElementById('search').value.toLowerCase();
        let visible = 0;
        document.querySelectorAll('#report-body tr').forEach(row => {
            const risk = row.dataset.risk;
            const text = row.dataset.text || '';
            const levelOk = activeLevel === 'ALL' || risk === activeLevel;
            const textOk  = !query || text.includes(query);
            row.style.display = (levelOk && textOk) ? '' : 'none';
            if (levelOk && textOk) visible++;
        });
        document.getElementById('no-results').style.display = visible === 0 ? '' : 'none';
    }

    function sortTable(col) {
        if (sortCol === col) { sortAsc = !sortAsc; } else { sortCol = col; sortAsc = true; }
        const tbody = document.getElementById('report-body');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {
            const aText = a.cells[col]?.innerText || '';
            const bText = b.cells[col]?.innerText || '';
            return sortAsc ? aText.localeCompare(bText) : bText.localeCompare(aText);
        });
        rows.forEach(r => tbody.appendChild(r));
    }
    </script>
</body></html>""")

    return "\n".join(html)


def generate_html_from_file(
    risk_json_path: str, output_path: str | None = None
) -> str:
    """Generate HTML report from JSON file path (matches SPEC file-based API).

    Args:
        risk_json_path: Path to risk report JSON file.
        output_path: Optional path to write HTML output.

    Returns:
        HTML content as string.
    """
    import json

    report = json.load(open(risk_json_path))
    html = generate_html(report)

    if output_path:
        with open(output_path, "w") as f:
            f.write(html)

    return html


def main(report_path: str, output_path: str | None = None) -> None:
    report = json.load(open(report_path))
    html = generate_html(report)

    if output_path is None:
        output_path = "api_report.html"
    with open(output_path, "w") as f:
        f.write(html)

    print(f"Report written to {output_path}")
