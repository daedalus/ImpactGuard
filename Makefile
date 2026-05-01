.PHONY: signatures calls analyze compare test clean risk report

# Extract function signatures from all tracked Python files
signatures:
	python3 extract_signatures.py $(git ls-files '*.py') > .signatures.txt

# Extract call sites from all tracked Python files
calls:
	python3 extract_calls.py $(git ls-files '*.py') > .calls.json

# Run static impact analysis (requires .signatures.json and .calls.json)
analyze: signatures calls
	python3 impact_analysis.py .signatures.json .calls.json

# Compare two signature files
compare:
	@if [ -z "$(OLD)" ] || [ -z "$(NEW)" ]; then \
		echo "Usage: make compare OLD=old.json NEW=new.json"; \
		exit 1; \
	fi
	python3 compare_signatures.py $(OLD) $(NEW)

# Run risk analysis pipeline
risk: signatures calls
	python3 risk_gate.py diff.txt runtime.json report.json

# Generate HTML report from risk JSON
report: risk
	python3 generate_report.py report.json

# Run runtime tracing during tests
runtime:
	python3 -c "import trace_calls; import mypackage; trace_calls.install_tracer(mypackage); import pytest; pytest.main()" || true
	trace_calls.dump(.runtime_calls.json)
	python3 runtime_impact.py .signatures.json .runtime_calls.json

# Clean generated files
clean:
	rm -f .signatures.txt .signatures.json .calls.json .runtime_calls.json api_report.html report.json diff.txt

# Install in development mode
install:
	pip install -e .

# Run all checks
check: signatures
	git diff --quiet -- .signatures.txt || (echo "Signatures out of date"; exit 1)

# Run tests
test:
	python3 test_impactguard.py
