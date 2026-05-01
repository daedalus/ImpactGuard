"""
Simple test to verify ImpactGuard components work correctly.
"""

import json
import subprocess
import tempfile
import os

def test_signature_extraction():
    """Test that extract_signatures.py works."""
    result = subprocess.run(
        ["python3", "extract_signatures.py", "extract_signatures.py"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Signature extraction failed: {result.stderr}"
    
    data = json.loads(result.stdout)
    assert len(data) > 0, "No signatures extracted"
    assert any(f["name"] == "serialize_function" for f in data)
    print("✓ Signature extraction works")

def test_compare_signatures():
    """Test that compare_signatures.py works."""
    sigs1 = '[{"fqname": "test.py:foo", "name": "foo", "positional": [{"name": "x", "has_default": false}], "kwonly": [], "vararg": false, "kwarg": false}]'
    sigs2 = '[{"fqname": "test.py:foo", "name": "foo", "positional": [{"name": "x", "has_default": false}, {"name": "y", "has_default": true}], "kwonly": [], "vararg": false, "kwarg": false}]'
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f1:
        f1.write(sigs1)
        f1_name = f1.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f2:
        f2.write(sigs2)
        f2_name = f2.name
    
    result = subprocess.run(
        ["python3", "compare_signatures.py", f1_name, f2_name],
        capture_output=True,
        text=True
    )
    
    os.unlink(f1_name)
    os.unlink(f2_name)
    
    assert "OPTIONAL POSITIONAL ADDED" in result.stdout
    print("✓ Signature comparison works")

def test_call_extraction():
    """Test that extract_calls.py works."""
    result = subprocess.run(
        ["python3", "extract_calls.py", "test_impactguard.py"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Call extraction failed: {result.stderr}"
    
    data = json.loads(result.stdout)
    # This file makes subprocess calls, so there should be calls
    assert len(data) > 0, "No calls extracted"
    print("✓ Call extraction works")

if __name__ == "__main__":
    test_signature_extraction()
    test_compare_signatures()
    test_call_extraction()
    print("\n✓ All ImpactGuard tests passed!")
