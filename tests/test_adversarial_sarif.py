from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Any

from impactguard.sarif import generate_sarif


def _tmpjson(data: Any) -> str:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, f)
    f.close()
    return f.name


def _rm(*paths: str) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


def _sample_report() -> list[dict[str, Any]]:
    return [
        {
            "function": "src/module.py:delete_user",
            "risk": "HIGH",
            "change": "REMOVED",
            "exposure": 0.85,
            "confidence": 0.92,
            "details": "called 42 times",
        },
        {
            "function": "src/module.py:get_user",
            "risk": "MEDIUM",
            "change": "TYPE_CHANGED",
            "exposure": 0.45,
            "confidence": 0.60,
            "details": "called 15 times",
        },
        {
            "function": "src/utils.py:helper",
            "risk": "LOW",
            "change": "OPTIONAL",
            "exposure": 0.05,
            "confidence": 0.30,
            "details": "called 3 times",
        },
        {
            "function": "src/module.py:unknown_fn",
            "risk": "UNKNOWN",
            "change": "UNKNOWN_CHANGE",
            "exposure": 0.0,
            "confidence": 0.0,
            "details": "not observed",
        },
    ]


class TestBoundaryEdgeCases:
    def test_large_number_of_items(self):
        items = [
            {
                "function": f"f{i}",
                "risk": "HIGH" if i % 2 == 0 else "LOW",
                "change": "REMOVED" if i % 2 == 0 else "ADDED",
                "exposure": 0.5,
                "confidence": 0.5,
            }
            for i in range(1000)
        ]
        result = generate_sarif(items)
        assert len(result["runs"][0]["results"]) == 1000

    def test_empty_function_name(self):
        items = [
            {
                "function": "",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            }
        ]
        result = generate_sarif(items)
        uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == ""

    def test_infinity_exposure_confidence(self):
        items = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": math.inf,
                "confidence": math.inf,
            },
        ]
        result = generate_sarif(items)
        props = result["runs"][0]["results"][0]["properties"]
        assert props["exposure"] == math.inf
        assert props["confidence"] == math.inf

    def test_negative_exposure(self):
        items = [
            {
                "function": "f1",
                "risk": "MEDIUM",
                "change": "TYPE_CHANGED",
                "exposure": -1.0,
                "confidence": -0.5,
            },
        ]
        result = generate_sarif(items)
        props = result["runs"][0]["results"][0]["properties"]
        assert props["exposure"] == -1.0
        assert props["confidence"] == -0.5

    def test_all_fields_empty_strings(self):
        items = [
            {
                "function": "",
                "risk": "",
                "change": "",
                "exposure": 0,
                "confidence": 0,
            },
        ]
        result = generate_sarif(items)
        assert len(result["runs"][0]["results"]) == 1

    def test_single_item_single_rule(self):
        items = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(items)
        assert len(result["runs"][0]["tool"]["driver"]["rules"]) == 1
        assert len(result["runs"][0]["results"]) == 1


class TestSemanticPerturbation:
    def test_same_data_different_key_order(self):
        a = [
            {
                "change": "REMOVED",
                "function": "f1",
                "risk": "HIGH",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        b = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "confidence": 0.5,
                "exposure": 0.5,
            },
        ]
        r1 = generate_sarif(a)
        r2 = generate_sarif(b)
        assert r1["runs"][0]["results"] == r2["runs"][0]["results"]

    def test_details_field_empty_string_vs_omitted(self):
        with_details = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
                "details": "",
            },
        ]
        without_details = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        r1 = generate_sarif(with_details)
        r2 = generate_sarif(without_details)
        assert "details" not in r1["runs"][0]["results"][0]["properties"]
        assert "details" not in r2["runs"][0]["results"][0]["properties"]

    def test_details_field_none_vs_omitted(self):
        with_none = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
                "details": None,
            },
        ]
        without = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        r1 = generate_sarif(with_none)
        r2 = generate_sarif(without)
        p1 = r1["runs"][0]["results"][0]["properties"]
        p2 = r2["runs"][0]["results"][0]["properties"]
        assert p1.get("details") is None or "details" not in p1
        assert "details" not in p2

    def test_same_change_different_risk(self):
        items = [
            {
                "function": "a",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
            {
                "function": "b",
                "risk": "LOW",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(items)
        rules = result["runs"][0]["tool"]["driver"]["rules"]
        assert len(rules) == 1
        levels = {r["level"] for r in result["runs"][0]["results"]}
        assert "error" in levels
        assert "note" in levels

    def test_equivalent_risk_names_produce_same_structure(self):
        items = _sample_report()
        r1 = generate_sarif(items)
        r2 = generate_sarif(items)
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


class TestEvasionObfuscation:
    def test_sql_injection_in_function_name(self):
        items = [
            {
                "function": "'; DROP TABLE risks; --",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(items)
        uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == "'; DROP TABLE risks; --"

    def test_newlines_in_function_name(self):
        items = [
            {
                "function": "f1\nf2\nf3",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(items)
        uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == "f1\nf2\nf3"

    def test_control_characters_in_function_name(self):
        items = [
            {
                "function": "f\x00n\x01l",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(items)
        uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert "\x00" in uri

    def test_unicode_bidi_override(self):
        items = [
            {
                "function": "src/\u202efn.py",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(items)
        uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert "\u202e" in uri

    def test_html_injection_in_details(self):
        items = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
                "details": "<script>alert('xss')</script>",
            },
        ]
        result = generate_sarif(items)
        details = result["runs"][0]["results"][0]["properties"]["details"]
        assert details == "<script>alert('xss')</script>"

    def test_json_injection_via_details(self):
        items = [
            {
                "function": "f1",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
                "details": '", "extra": "injected"}',
            },
        ]
        result = generate_sarif(items)
        props = result["runs"][0]["results"][0]["properties"]
        assert props["details"] == '", "extra": "injected"}'
        roundtrip = json.dumps(result)
        assert '"extra"' not in roundtrip or roundtrip.count('"extra"') == 0

    def test_extremely_long_function_name(self):
        items = [
            {
                "function": "a" * 10000,
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(items)
        uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert len(uri) == 10000


class TestCompositionalAttacks:
    def test_sarif_roundtrip_through_json(self):
        sarif = generate_sarif(_sample_report())
        serialized = json.dumps(sarif)
        deserialized = json.loads(serialized)
        rebuilt = generate_sarif(deserialized["runs"][0]["results"])
        assert rebuilt["version"] == "2.1.0"
        assert len(rebuilt["runs"][0]["results"]) == 4

    def test_report_sarif_command_roundtrip(self):
        p = _tmpjson(_sample_report())
        out = p.replace(".json", ".sarif")
        try:
            import sys

            from impactguard.__main__ import main

            test_args = ["impactguard", "report-sarif", p, "-o", out]
            with __import__("pytest").MonkeyPatch.context() as mp:
                mp.setattr(sys, "argv", test_args)
                rc = main()
                assert rc == 0
                assert os.path.exists(out)
                loaded = json.loads(open(out).read())
                assert loaded["version"] == "2.1.0"
                assert len(loaded["runs"][0]["results"]) == 4
        finally:
            _rm(p, out)

    def test_sarif_via_check_no_risk_skips_file(self):
        p = _tmpjson(_sample_report())
        out = p.replace(".json", ".sarif")
        try:
            from impactguard.__main__ import _write_sarif_output

            result = {"comparison": {"breaking": []}, "risk": []}
            _write_sarif_output(result, out)
            assert not os.path.exists(out)
        finally:
            _rm(p, out)

    def test_sarif_through_pipeline_result(self):
        out = tempfile.mktemp(suffix=".sarif")
        try:
            from impactguard.__main__ import _write_sarif_output

            result = {
                "risk": _sample_report(),
                "comparison": {"breaking": [], "nonbreaking": []},
                "semver": {"bump": "patch", "reason": "test"},
            }
            _write_sarif_output(result, out)
            assert os.path.exists(out)
            loaded = json.loads(open(out).read())
            assert "runs" in loaded
            assert len(loaded["runs"][0]["results"]) == 4
        finally:
            _rm(out)
