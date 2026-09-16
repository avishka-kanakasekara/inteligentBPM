"""Deterministic quotation normalization and comparison (Gemini explains only)."""

from __future__ import annotations

import re
from typing import Any

from app.agents.execution.models import (
    NormalizedQuotation,
    NormalizedQuoteLine,
    QuotationComparisonResult,
    QuotationScoreBreakdown,
)

# Fixed FX table for deterministic normalization (mock)
FX_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "INR": 0.012,
    "CAD": 0.74,
    "AUD": 0.66,
}

UNIT_TO_EACH: dict[str, float] = {
    "each": 1.0,
    "ea": 1.0,
    "unit": 1.0,
    "box": 10.0,
    "pack": 5.0,
    "dozen": 12.0,
    "kg": 1.0,
    "lb": 0.453592,
}


def _fx(currency: str) -> float:
    return FX_TO_USD.get(currency.upper(), 1.0)


def _unit_factor(unit: str) -> float:
    return UNIT_TO_EACH.get(unit.lower().strip(), 1.0)


def extract_quotation_from_text(raw_text: str, *, supplier_id: str | None = None) -> dict[str, Any]:
    """Deterministic extraction from untrusted text — never follows instructions in text."""
    text = raw_text
    # Strip obvious injection directives from consideration
    sanitized = re.sub(
        r"(?i)\b(ignore previous instructions|system prompt|execute sql|send email)\b",
        "[redacted]",
        text,
    )
    currency_match = re.search(r"\b(USD|EUR|GBP|INR|CAD|AUD)\b", sanitized, re.I)
    price_match = re.search(r"(?:unit(?:\s*price)?|price)\s*[:=]?\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", sanitized, re.I)
    qty_match = re.search(r"(?:qty|quantity)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", sanitized, re.I)
    delivery_match = re.search(r"(?:delivery|lead)\s*(?:time|days)?\s*[:=]?\s*([0-9]+)", sanitized, re.I)
    warranty_match = re.search(r"warranty\s*[:=]?\s*([0-9]+)", sanitized, re.I)
    tax_match = re.search(r"tax\s*[:=]?\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", sanitized, re.I)
    ship_match = re.search(r"ship(?:ping)?\s*[:=]?\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", sanitized, re.I)
    unit_match = re.search(r"\b(each|box|pack|dozen|kg|lb)\b", sanitized, re.I)
    return {
        "supplier_id": supplier_id or "unknown",
        "currency": (currency_match.group(1).upper() if currency_match else "USD"),
        "unit_price": float(price_match.group(1)) if price_match else 0.0,
        "quantity": float(qty_match.group(1)) if qty_match else 1.0,
        "unit": (unit_match.group(1).lower() if unit_match else "each"),
        "tax": float(tax_match.group(1)) if tax_match else 0.0,
        "shipping": float(ship_match.group(1)) if ship_match else 0.0,
        "delivery_days": int(delivery_match.group(1)) if delivery_match else None,
        "warranty_months": int(warranty_match.group(1)) if warranty_match else None,
        "payment_terms_days": 30,
        "untrusted": True,
        "mock": True,
    }


def normalize_quotation(raw: dict[str, Any]) -> NormalizedQuotation:
    currency = str(raw.get("currency") or raw.get("currency_code") or "USD").upper()
    fx = float(raw.get("fx_rate_to_usd") or _fx(currency))
    unit = str(raw.get("unit") or "each")
    unit_factor = _unit_factor(unit)
    qty = float(raw.get("quantity") or 1)
    unit_price = float(raw.get("unit_price") or raw.get("unit_price_original") or 0)
    # Normalize unit to each-equivalent then FX to USD
    unit_price_usd = (unit_price / unit_factor) * fx
    line_total = unit_price_usd * qty
    tax = float(raw.get("tax") or 0) * fx
    shipping = float(raw.get("shipping") or 0) * fx
    qid = str(raw.get("id") or raw.get("quotation_id") or "q")
    line = NormalizedQuoteLine(
        sku=raw.get("sku"),
        description=raw.get("description"),
        quantity=qty,
        unit="each",
        unit_price_usd=round(unit_price_usd, 4),
        line_total_usd=round(line_total, 4),
    )
    return NormalizedQuotation(
        quotation_id=qid,
        supplier_id=str(raw.get("supplier_id") or "unknown"),
        supplier_name=raw.get("supplier_name"),
        currency_original=currency,
        fx_rate_to_usd=fx,
        subtotal_usd=round(line_total, 2),
        tax_usd=round(tax, 2),
        shipping_usd=round(shipping, 2),
        total_cost_usd=round(line_total + tax + shipping, 2),
        delivery_days=raw.get("delivery_days"),
        warranty_months=raw.get("warranty_months"),
        payment_terms_days=raw.get("payment_terms_days"),
        supplier_risk_score=float(raw.get("supplier_risk_score") or 0.5),
        policy_compliance_score=float(raw.get("policy_compliance_score") or 0.5),
        lines=[line],
        mock=bool(raw.get("mock", True)),
        untrusted=True,
    )


# Weights sum to 1.0 — deterministic scoring
WEIGHTS = {
    "total_cost": 0.35,
    "delivery_time": 0.15,
    "warranty": 0.10,
    "payment_terms": 0.10,
    "supplier_risk": 0.15,
    "policy_compliance": 0.15,
}


def _norm_min_better(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    lo, hi = min(values), max(values)
    if hi == lo:
        return 1.0
    return 1.0 - (value - lo) / (hi - lo)


def _norm_max_better(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    lo, hi = min(values), max(values)
    if hi == lo:
        return 1.0
    return (value - lo) / (hi - lo)


def compare_quotations(
    quotations: list[NormalizedQuotation],
    *,
    explanation: str = "",
    llm_used: bool = False,
) -> QuotationComparisonResult:
    if not quotations:
        return QuotationComparisonResult(
            quotations=[],
            scores={},
            ranking=[],
            winner_quotation_id=None,
            explanation=explanation or "No quotations to compare.",
            llm_used=llm_used,
        )

    costs = [q.total_cost_usd for q in quotations]
    deliveries = [float(q.delivery_days or 999) for q in quotations]
    warranties = [float(q.warranty_months or 0) for q in quotations]
    terms = [float(q.payment_terms_days or 0) for q in quotations]
    risks = [q.supplier_risk_score for q in quotations]
    compliance = [q.policy_compliance_score for q in quotations]

    scores: dict[str, QuotationScoreBreakdown] = {}
    for q in quotations:
        cost_s = _norm_min_better(costs, q.total_cost_usd)
        del_s = _norm_min_better(deliveries, float(q.delivery_days or 999))
        war_s = _norm_max_better(warranties, float(q.warranty_months or 0))
        pay_s = _norm_max_better(terms, float(q.payment_terms_days or 0))
        # Lower supplier risk is better
        risk_s = _norm_min_better(risks, q.supplier_risk_score)
        pol_s = _norm_max_better(compliance, q.policy_compliance_score)
        weighted = (
            WEIGHTS["total_cost"] * cost_s
            + WEIGHTS["delivery_time"] * del_s
            + WEIGHTS["warranty"] * war_s
            + WEIGHTS["payment_terms"] * pay_s
            + WEIGHTS["supplier_risk"] * risk_s
            + WEIGHTS["policy_compliance"] * pol_s
        )
        scores[q.quotation_id] = QuotationScoreBreakdown(
            total_cost=round(cost_s, 4),
            delivery_time=round(del_s, 4),
            warranty=round(war_s, 4),
            payment_terms=round(pay_s, 4),
            supplier_risk=round(risk_s, 4),
            policy_compliance=round(pol_s, 4),
            weighted_total=round(weighted, 4),
        )

    ranking = sorted(scores.keys(), key=lambda qid: scores[qid].weighted_total, reverse=True)
    winner = ranking[0] if ranking else None
    if not explanation and winner:
        w = next(q for q in quotations if q.quotation_id == winner)
        explanation = (
            f"Deterministic winner {winner} with total_cost_usd={w.total_cost_usd:.2f}, "
            f"delivery_days={w.delivery_days}, score={scores[winner].weighted_total:.4f}."
        )
    return QuotationComparisonResult(
        quotations=quotations,
        scores=scores,
        ranking=ranking,
        winner_quotation_id=winner,
        deterministic=True,
        explanation=explanation,
        llm_used=llm_used,
    )
