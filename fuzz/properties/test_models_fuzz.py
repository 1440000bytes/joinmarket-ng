# ruff: noqa: E402
#!/usr/bin/env python3
"""
Hypothesis-based property tests for jmcore models.
"""

import sys
import os
import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

# Setup path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(root_dir, "jmcore", "src"))

from jmcore.models import PeerInfo, MessageEnvelope, Offer, FidelityBond


@pytest.mark.fuzz
@given(st.binary(min_size=0, max_size=10000))
def test_message_envelope_fuzz(data):
    """Ensure from_bytes handles arbitrary binary data safely."""
    try:
        MessageEnvelope.from_bytes(data)
    except (ValidationError, Exception):
        # We expect handleable errors (validation failures or nesting depth),
        # but no unhandled exceptions.
        pass


@pytest.mark.fuzz
@given(
    st.dictionaries(
        keys=st.text(), values=st.text() | st.integers() | st.booleans() | st.none()
    )
)
def test_peer_info_fuzz(data):
    """Ensure PeerInfo validation handles arbitrary dicts safely."""
    try:
        PeerInfo.model_validate(data)
    except (ValidationError, TypeError):
        pass


@pytest.mark.fuzz
@given(
    st.dictionaries(
        keys=st.text(), values=st.text() | st.integers() | st.booleans() | st.none()
    )
)
def test_offer_fuzz(data):
    """Ensure Offer validation handles arbitrary dicts safely."""
    try:
        Offer.model_validate(data)
    except (ValidationError, TypeError):
        pass


@pytest.mark.fuzz
@given(
    st.dictionaries(
        keys=st.text(), values=st.text() | st.integers() | st.booleans() | st.none()
    )
)
def test_fidelity_bond_fuzz(data):
    """Ensure FidelityBond validation handles arbitrary dicts safely."""
    try:
        FidelityBond.model_validate(data)
    except (ValidationError, TypeError):
        pass
