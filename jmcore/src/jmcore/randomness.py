"""Cryptographically secure randomness for adversary-relevant choices."""

from __future__ import annotations

import secrets

secure_random = secrets.SystemRandom()
