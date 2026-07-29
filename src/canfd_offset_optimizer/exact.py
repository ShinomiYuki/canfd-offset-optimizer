"""Exact numeric normalization shared by core-facing adapters."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import TypeAlias

RhoInput: TypeAlias = Fraction | Decimal | int | float | str


def normalize_rho(value: RhoInput) -> Fraction:
    """Normalize rho without expanding binary floating-point representation."""
    if isinstance(value, bool):
        raise TypeError("rho must be a positive real number, not bool")
    if isinstance(value, Fraction):
        normalized = value
    elif isinstance(value, int):
        normalized = Fraction(value, 1)
    elif isinstance(value, (Decimal, float, str)):
        try:
            normalized = Fraction(str(value))
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("rho must be a finite positive real number") from exc
    else:
        raise TypeError("rho must be int, float, str, Decimal, or Fraction")
    if normalized <= 0:
        raise ValueError("rho must be positive")
    return normalized
