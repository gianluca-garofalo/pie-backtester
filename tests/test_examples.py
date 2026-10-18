import os
import glob
import json
import pytest
from storage import validate_pie, normalize_pie, EXAMPLES_DIR

def test_all_examples_valid():
    example_files = glob.glob(os.path.join(EXAMPLES_DIR, "*.json"))
    assert len(example_files) >= 5, "Should have at least 5 example pies"

    for filepath in example_files:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        is_valid, err_msg = validate_pie(data)
        assert is_valid, f"Example file {filepath} failed validation: {err_msg}"

        norm = normalize_pie(data)
        assert norm["version"] == 1
        assert norm["name"]
        assert len(norm["assets"]) > 0
