"""Tests for SARIF output support."""

from __future__ import annotations

import json

import pytest


def _sample_report():
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


class TestGenerateSarif:
    def test_generate_sarif_basic_structure(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())

        assert result["$schema"].endswith("sarif-schema-2.1.0.json")
        assert result["version"] == "2.1.0"
        assert "runs" in result
        assert len(result["runs"]) == 1

    def test_generate_sarif_tool_info(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        driver = result["runs"][0]["tool"]["driver"]

        assert driver["name"] == "ImpactGuard"
        assert "version" in driver
        assert "informationUri" in driver

    def test_generate_sarif_rules(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        rules = result["runs"][0]["tool"]["driver"]["rules"]

        rule_ids = {r["id"] for r in rules}
        assert "REMOVED" in rule_ids
        assert "TYPE_CHANGED" in rule_ids
        assert "OPTIONAL" in rule_ids
        assert "UNKNOWN_CHANGE" in rule_ids

    def test_generate_sarif_results(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        results = result["runs"][0]["results"]

        assert len(results) == 4

    def test_generate_sarif_level_mapping(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        results = result["runs"][0]["results"]

        levels = {r["level"] for r in results}
        assert "error" in levels
        assert "warning" in levels
        assert "note" in levels
        assert "none" in levels

    def test_generate_sarif_result_message(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        results = result["runs"][0]["results"]

        high_results = [r for r in results if r["level"] == "error"]
        assert len(high_results) == 1
        assert "delete_user" in high_results[0]["message"]["text"]

    def test_generate_sarif_properties(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        results = result["runs"][0]["results"]

        for r in results:
            assert "exposure" in r["properties"]
            assert "confidence" in r["properties"]

    def test_generate_sarif_empty_report(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif([])
        assert result["version"] == "2.1.0"
        assert len(result["runs"][0]["results"]) == 0
        assert len(result["runs"][0]["tool"]["driver"]["rules"]) == 0

    def test_generate_sarif_roundtrip_json(self):
        from impactguard.sarif import generate_sarif

        sarif = generate_sarif(_sample_report())
        serialized = json.dumps(sarif)
        deserialized = json.loads(serialized)

        assert deserialized["version"] == "2.1.0"
        assert len(deserialized["runs"][0]["results"]) == 4

    def test_generate_sarif_deduplicates_rules(self):
        from impactguard.sarif import generate_sarif

        data = [
            {
                "function": "a",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
            {
                "function": "b",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
        ]
        result = generate_sarif(data)
        rules = result["runs"][0]["tool"]["driver"]["rules"]
        assert len(rules) == 1

    def test_generate_sarif_non_dict_items_skipped(self):
        from impactguard.sarif import generate_sarif

        data = [
            {
                "function": "a",
                "risk": "HIGH",
                "change": "REMOVED",
                "exposure": 0.5,
                "confidence": 0.5,
            },
            "not a dict",
            42,
        ]
        result = generate_sarif(data)
        assert len(result["runs"][0]["results"]) == 1

    def test_generate_sarif_location_uri(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        loc = result["runs"][0]["results"][0]["locations"][0]
        assert (
            loc["physicalLocation"]["artifactLocation"]["uri"]
            == "src/module.py:delete_user"
        )

    def test_generate_sarif_rule_reference(self):
        from impactguard.sarif import generate_sarif

        result = generate_sarif(_sample_report())
        first = result["runs"][0]["results"][0]
        assert "ruleId" in first
        assert "ruleIndex" in first


class TestGenerateSarifFromFile:
    def test_generate_sarif_from_file(self, tmp_path):
        from impactguard.sarif import generate_sarif_from_file

        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_sample_report()))

        output_path = tmp_path / "output.sarif"
        sarif = generate_sarif_from_file(str(report_path), str(output_path))

        assert sarif["version"] == "2.1.0"
        assert output_path.exists()
        loaded = json.loads(output_path.read_text())
        assert loaded["version"] == "2.1.0"

    def test_generate_sarif_from_file_no_output(self, tmp_path):
        from impactguard.sarif import generate_sarif_from_file

        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_sample_report()))

        sarif = generate_sarif_from_file(str(report_path))
        assert sarif["version"] == "2.1.0"

    def test_generate_sarif_from_file_invalid_json(self, tmp_path):
        from impactguard.sarif import generate_sarif_from_file

        report_path = tmp_path / "bad.json"
        report_path.write_text("not json")

        with pytest.raises(ValueError, match="Invalid JSON"):
            generate_sarif_from_file(str(report_path))

    def test_generate_sarif_from_file_not_a_list(self, tmp_path):
        from impactguard.sarif import generate_sarif_from_file

        report_path = tmp_path / "obj.json"
        report_path.write_text(json.dumps({"not": "a list"}))

        with pytest.raises(ValueError, match="expected a JSON array"):
            generate_sarif_from_file(str(report_path))

    def test_generate_sarif_from_file_empty_list(self, tmp_path):
        from impactguard.sarif import generate_sarif_from_file

        report_path = tmp_path / "empty.json"
        report_path.write_text("[]")

        sarif = generate_sarif_from_file(str(report_path))
        assert len(sarif["runs"][0]["results"]) == 0


class TestCli:
    def test_cli_report_sarif(self, tmp_path):
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_sample_report()))

        output_path = tmp_path / "out.sarif"

        import sys

        from impactguard.__main__ import main

        test_args = [
            "impactguard",
            "report-sarif",
            str(report_path),
            "-o",
            str(output_path),
        ]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", test_args)
            result = main()
            assert result == 0
            assert output_path.exists()
            loaded = json.loads(output_path.read_text())
            assert loaded["version"] == "2.1.0"
            assert len(loaded["runs"][0]["results"]) == 4

    def test_cli_report_sarif_stdout(self, tmp_path, capsys):
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_sample_report()))

        import sys

        from impactguard.__main__ import main

        test_args = [
            "impactguard",
            "report-sarif",
            str(report_path),
        ]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", test_args)
            result = main()
            assert result == 0
            captured = capsys.readouterr()
            loaded = json.loads(captured.out)
            assert loaded["version"] == "2.1.0"

    def test_cli_report_sarif_bad_input(self, tmp_path, capsys):
        report_path = tmp_path / "bad.json"
        report_path.write_text("not json")

        import sys

        from impactguard.__main__ import main

        test_args = [
            "impactguard",
            "report-sarif",
            str(report_path),
        ]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", test_args)
            result = main()
            assert result == 1
