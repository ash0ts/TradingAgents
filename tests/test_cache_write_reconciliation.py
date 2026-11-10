"""List-price fixtures: cache creation, cache reads and long-context premiums."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("reconcile_cache_write_costs", SCRIPTS / "reconcile_cache_write_costs.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("model,expected", [("gpt-6-luna", 23500), ("gpt-6-sol", 470000)])
def test_mixed_input_categories_and_output(model, expected):
    # 100k cache writes + 100k cache reads, and 20k output.
    # This fixture is below the long-context threshold.
    usage = {"input_tokens": 200000, "output_tokens": 20000,
             "input_token_details": {"cache_creation": 100000, "cache_read": 100000}}
    # Luna: 12,500 write + 1,000 read + 10,000 output = 23,500 micros.
    assert module.charge(model, usage) == expected


def test_long_context_and_unknown_category_rejection():
    usage = {"input_tokens": 400000, "output_tokens": 20000,
             "input_token_details": {"cache_creation": 100000, "cache_read": 200000}}
    # Luna: (10,000 + 12,500 + 2,000)*2 + 10,000*1.5.
    assert module.charge("gpt-6-luna", usage) == 64000
    with pytest.raises(AssertionError):
        module.charge("gpt-6-luna", {**usage, "input_tokens": 299999})
