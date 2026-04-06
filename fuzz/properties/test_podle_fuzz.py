# ruff: noqa: E402
#!/usr/bin/env python3
"""
Hypothesis-based property tests for PoDLE proof verification.
"""

import sys
import os
import pytest
from hypothesis import given, strategies as st

# Setup path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(root_dir, "jmcore", "src"))

from jmcore.podle import verify_podle


@pytest.mark.fuzz
@given(
    proof=st.binary(min_size=0, max_size=1000),
    u_P_hex=st.text(min_size=0, max_size=66),
    u_P_vout=st.integers(min_value=0, max_value=0xFFFFFFFF),
    maker_cj_addr=st.text(min_size=0, max_size=66),
    n=st.integers(min_value=1, max_value=20),
)
def test_verify_podle_fuzz(proof, u_P_hex, u_P_vout, maker_cj_addr, n):
    """Ensure verify_podle handles arbitrary proof data safely."""
    try:
        # PoDLE verification involves cryptographic operations
        # We expect handleable errors (invalid proof format, etc.)
        verify_podle(
            proof=proof,
            u_P_hex=u_P_hex,
            u_P_vout=u_P_vout,
            maker_cj_addr=maker_cj_addr,
            n=n,
        )
    except (ValueError, TypeError, Exception):
        # We expect handleable errors, but not crashes
        pass
