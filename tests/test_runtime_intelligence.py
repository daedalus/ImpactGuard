import json


def test_normalize_runtime_payload_accepts_multiple_shapes():
    from impactguard.runtime_intelligence import normalize_runtime_payload

    observations = normalize_runtime_payload(
        {
            "runtime": [
                {"symbol": "src::lib::Api::call", "hits": 7, "argc": 2},
                {
                    "function": "pkg/module.py:helper",
                    "count": 3,
                    "kwargs": {"debug": True},
                },
            ]
        }
    )

    assert [item["count"] for item in observations] == [7, 3]
    assert observations[0]["canonical"] == "src.lib.Api.call"
    assert observations[0]["args_count"] == 2
    assert observations[1]["canonical"] == "pkg.module.helper"
    assert observations[1]["kwargs"] == ["debug"]

    mapped = normalize_runtime_payload({"src::lib::Api::call": 5})
    assert mapped == [
        {
            "function": "src::lib::Api::call",
            "count": 5,
            "canonical": "src.lib.Api.call",
            "aliases": ["Api.call", "call", "src.lib.Api.call", "src::lib::Api::call"],
        }
    ]


def test_runtime_callsite_entries_skip_count_only_observations():
    from impactguard.runtime_intelligence import (
        normalize_runtime_payload,
        runtime_callsite_entries,
    )

    observations = normalize_runtime_payload(
        [
            {"function": "src::lib::Api::call", "count": 7},
            {"function": "pkg/module.py:helper", "count": 3, "args_count": 1},
            {
                "function": "pkg/module.py:debug",
                "count": 2,
                "kwargs": {"verbose": True},
            },
        ]
    )

    assert runtime_callsite_entries(observations) == [
        {
            "fqname": "pkg.module.helper",
            "file": "runtime",
            "lineno": 0,
            "args": 1,
            "kwargs": [],
            "has_starargs": False,
            "has_kwargs": False,
        },
        {
            "fqname": "pkg.module.debug",
            "file": "runtime",
            "lineno": 0,
            "args": 0,
            "kwargs": ["verbose"],
            "has_starargs": False,
            "has_kwargs": False,
        },
    ]


def test_risk_gate_uses_canonical_runtime_aliases(tmp_path):
    from impactguard.risk_gate import run

    diff_path = tmp_path / "diff.txt"
    diff_path.write_text("REMOVED: src/lib.rs:Api.call\n")

    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps({"src::lib::Api::call": 42}))

    report = run(str(diff_path), str(runtime_path))

    assert report[0]["function"] == "src/lib.rs:Api.call"
    assert report[0]["risk"] == "HIGH"
    assert report[0]["details"] == "called 42 times"


def test_impact_analysis_uses_canonical_runtime_aliases(tmp_path):
    from impactguard.impact_analysis import analyze

    sigs_path = tmp_path / "sigs.json"
    sigs_path.write_text(
        json.dumps(
            [
                {
                    "fqname": "src/lib.rs:Api.call",
                    "name": "Api.call",
                    "positional": [
                        {"name": "value", "has_default": False},
                        {"name": "mode", "has_default": False},
                    ],
                    "kwonly": [],
                    "vararg": False,
                    "kwarg": False,
                }
            ]
        )
    )

    calls_path = tmp_path / "calls.json"
    calls_path.write_text(
        json.dumps(
            [
                {
                    "fqname": "src.lib.Api.call",
                    "file": "caller.rs",
                    "lineno": 12,
                    "args": 1,
                    "kwargs": [],
                    "has_starargs": False,
                    "has_kwargs": False,
                }
            ]
        )
    )

    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps({"src::lib::Api::call": 9}))

    issues = analyze(str(sigs_path), str(calls_path), str(runtime_path))

    assert len(issues) == 1
    assert issues[0]["function"] == "src/lib.rs:Api.call"
    assert issues[0]["count"] == 9
    assert issues[0]["confidence"] == 0.09
