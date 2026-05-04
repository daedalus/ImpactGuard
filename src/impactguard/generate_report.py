import json
from typing import Any


def color(level: str) -> str:
    return {
        "HIGH": "#ff4d4f",
        "MEDIUM": "#faad14",
        "LOW": "#52c41a",
        "UNKNOWN": "#d9d9d9",
    }.get(level, "#d9d9d9")


def generate_html(report_data: list[dict[str, Any]]) -> str:
    html: list[str] = []
    html.append("""<!DOCTYPE html>
<html>
<head>
    <title>API Risk Report</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        .item { border-left: 6px solid #ccc; padding: 10px; margin: 10px 0; }
        .HIGH { border-color: #ff4d4f; }
        .MEDIUM { border-color: #faad14; }
        .LOW { border-color: #52c41a; }
        .UNKNOWN { border-color: #d9d9d9; }
        pre { background: #111; color: #eee; padding: 10px; }
        ul { margin: 5px 0; }
    </style>
</head>
<body>""")
    html.append("<h1>API Risk Report</h1>")

    for item in report_data:
        level = item.get("risk", "UNKNOWN")
        color(level)  # noqa: F841 - called for side effects (though actually unused)
        func = item.get("function", "unknown")
        change = item.get("change", "")
        exp = item.get("exposure", 0)
        conf = item.get("confidence", 0)
        details = item.get("details", "")
        fixes = item.get("fixes", [])

        html.append(f"""
    <div class="item {level}">
        <h3>{level} — {func}</h3>
        <p><b>Change:</b> {change}</p>
        <p><b>Exposure:</b> {exp:.2%}</p>
        <p><b>Confidence:</b> {conf:.2f}</p>
        <p><b>Details:</b> {details}</p>
""")

        if fixes:
            html.append("        <ul>")
            for fix in fixes:
                html.append(f"            <li>{fix}</li>")
            html.append("        </ul>")

        # Show patch if available
        patches = item.get("patches", [])
        if patches:
            for p in patches:
                html.append(f"        <pre>{p}</pre>")

        html.append("    </div>")

    html.append("</body></html>")

    return "\n".join(html)


def main(report_path: str, output_path: str | None = None) -> None:
    report = json.load(open(report_path))
    html = generate_html(report)

    if output_path is None:
        output_path = "api_report.html"
    with open(output_path, "w") as f:
        f.write(html)

    print(f"Report written to {output_path}")
