#!/usr/bin/env python3
"""
Compute the two-vector exposure scores.

Reads the synthetic dataset, produces one record per business unit containing:

    HRI   Human Risk Index          0..100, higher is worse
    TRI   Technical Risk Index      0..100, higher is worse
    CES   Compound Exposure Score   0..100, geometric mean of the two vectors
    CC    Coverage Confidence       0..1,  how much of the unit is measured
    CES*  Confidence-corrected CES  CES inflated where the data is thin

The formulas live in docs/02-normalization-and-scoring.md. If you change a
weight here, change it there too -- and nowhere else, because those are the
only two places a weight is allowed to appear.

Usage:
    python3 tools/compute_exposure.py --indir data/synthetic --out data/scores.json
"""

import argparse
import csv
import json
import math
import os
from collections import defaultdict

# --- Human vector weights -------------------------------------------------
# Susceptibility and resilience carry the same weight, with opposite signs.
# This is the deliberate core of the model: an organisation that clicks a lot
# but reports a lot is not in the same position as one that clicks a lot and
# reports nothing, and the arithmetic has to say so.
W_SUSCEPTIBILITY = 0.55
W_KNOWLEDGE_GAP = 0.25
W_RESILIENCE = 0.55
H_MAX = W_SUSCEPTIBILITY + W_KNOWLEDGE_GAP  # theoretical worst case, 0.80

# Resilience is a credit, but a bounded one. A population that reports well
# still clicks, and a report does not un-submit a credential. Capping the
# credit at 80% of the positive terms keeps the marginal weight of reporting
# equal to that of susceptibility while preventing a well-drilled unit from
# scoring a perfect zero -- which would then annihilate the compound score
# through the geometric mean and hide a real technical problem.
RESILIENCE_CREDIT_CAP = 0.80

# --- Technical vector weights ---------------------------------------------
W_SEVERITY = 0.70
W_LATENCY = 0.30
MTTR_SATURATION_DAYS = 180  # beyond this, additional delay adds no information
TOP_QUARTILE = 0.25

# --- Confidence correction ------------------------------------------------
# At full coverage the correction is neutral. At zero coverage it inflates the
# score by a factor of two. It never deflates a score: missing data is treated
# as bad news, never as good news.
CC_FLOOR = 0.50


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def human_vector(people):
    """Return (HRI, components) for one unit's in-scope population."""
    measured = [p for p in people if p["in_scope"] == "1"]
    if not measured:
        return None, None

    sent = sum(int(p["phish_sent"]) for p in measured)
    clicked = sum(int(p["phish_clicked"]) for p in measured)
    # Real ingested data carries a graded failure weight: a click and an
    # enabled macro are both failures, and they are not the same failure. When
    # the column is absent -- as in the synthetic dataset -- fall back to the
    # plain count, so both sources run through the same engine.
    graded = sum(float(p.get("failure_weight") or 0) for p in measured) \
        if any("failure_weight" in p for p in measured) else None
    reported = sum(int(p["phish_reported"]) for p in measured)
    submitted = sum(int(p["credential_submitted"]) for p in measured)
    assigned = sum(int(p["training_assigned"]) for p in measured)
    completed = sum(int(p["training_completed"]) for p in measured)

    # s: susceptibility. Severity-weighted failure rate over delivered
    # messages where available, otherwise the plain phish-prone rate.
    if sent:
        s = (graded / sent) if graded is not None else (clicked / sent)
    else:
        s = 0.0
    # r: resilience. Report rate over delivered messages.
    r = reported / sent if sent else 0.0
    # k: knowledge gap. Share of assigned training still not completed.
    k = 1 - (completed / assigned) if assigned else 0.0

    positive = (W_SUSCEPTIBILITY * s) + (W_KNOWLEDGE_GAP * k)
    credit = min(W_RESILIENCE * r, RESILIENCE_CREDIT_CAP * positive)
    raw = positive - credit
    hri = 100 * max(0.0, min(raw, H_MAX)) / H_MAX

    components = {
        "phish_prone_rate": round(100 * s, 2),
        "severity_weighted": graded is not None,
        "report_rate": round(100 * r, 2),
        "training_gap_rate": round(100 * k, 2),
        "credential_conversion_rate": round(100 * submitted / clicked, 2) if clicked else 0.0,
        "measured_people": len(measured),
    }
    return round(hri, 2), components


def technical_vector(assets):
    """Return (TRI, components) for one unit's in-scope assets."""
    measured = [a for a in assets if a["in_scope"] == "1"]
    if not measured:
        return None, None

    # Severity is read off the worst quartile only. A unit is not made safe by
    # owning a large number of uninteresting assets, so the mean over the whole
    # estate is the wrong statistic -- it rewards fleet size.
    ranked = sorted(measured, key=lambda a: int(a["qds_max"]), reverse=True)
    cut = max(1, math.ceil(len(ranked) * TOP_QUARTILE))
    tail = ranked[:cut]

    weight_sum = sum(int(a["asset_criticality"]) for a in tail)
    if weight_sum:
        severity = sum(
            int(a["qds_max"]) * int(a["asset_criticality"]) for a in tail
        ) / (100 * weight_sum)
    else:
        severity = 0.0

    ages = [int(a["oldest_critical_age_days"]) for a in tail]
    mttr = sum(ages) / len(ages)
    latency = min(mttr / MTTR_SATURATION_DAYS, 1.0)

    tri = 100 * ((W_SEVERITY * severity) + (W_LATENCY * latency))

    components = {
        "top_quartile_assets": cut,
        "weighted_severity": round(100 * severity, 2),
        "mean_age_critical_days": round(mttr, 1),
        "kev_findings": sum(int(a["kev_count"]) for a in measured),
        "measured_assets": len(measured),
    }
    return round(tri, 2), components


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indir", default="data/synthetic")
    parser.add_argument("--out", default="data/scores.json")
    args = parser.parse_args()

    units = read_csv(os.path.join(args.indir, "units.csv"))
    people = read_csv(os.path.join(args.indir, "people.csv"))
    assets = read_csv(os.path.join(args.indir, "assets.csv"))

    people_by_unit = defaultdict(list)
    for row in people:
        people_by_unit[row["unit_id"]].append(row)

    assets_by_unit = defaultdict(list)
    for row in assets:
        assets_by_unit[row["unit_id"]].append(row)

    results = []
    for unit in units:
        uid = unit["unit_id"]
        unit_people = people_by_unit[uid]
        unit_assets = assets_by_unit[uid]

        hri, h_parts = human_vector(unit_people)
        tri, t_parts = technical_vector(unit_assets)
        if hri is None or tri is None:
            continue

        # Geometric mean: a unit is compound-exposed only when both vectors are
        # present. A high technical score on a population that does not click
        # is a different problem, and it should not rank alongside.
        ces = math.sqrt(hri * tri)

        person_coverage = h_parts["measured_people"] / len(unit_people)
        asset_coverage = t_parts["measured_assets"] / len(unit_assets)
        cc = min(person_coverage, asset_coverage)
        ces_corrected = min(100.0, ces / (CC_FLOOR + (1 - CC_FLOOR) * cc))

        results.append({
            "unit_id": uid,
            "unit_name": unit["unit_name"],
            "headcount": int(unit["headcount"]),
            "business_criticality": int(unit["business_criticality"]),
            "HRI": hri,
            "TRI": tri,
            "CES": round(ces, 2),
            "CES_corrected": round(ces_corrected, 2),
            "coverage_confidence": round(cc, 3),
            "person_coverage": round(person_coverage, 3),
            "asset_coverage": round(asset_coverage, 3),
            "human": h_parts,
            "technical": t_parts,
        })

    results.sort(key=lambda r: r["CES_corrected"], reverse=True)
    for rank, row in enumerate(results, start=1):
        row["rank_corrected"] = rank
    by_raw = sorted(results, key=lambda r: r["CES"], reverse=True)
    for rank, row in enumerate(by_raw, start=1):
        row["rank_raw"] = rank

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"units": results}, handle, indent=2, ensure_ascii=False)

    print(f"Scored {len(results)} units -> {args.out}")
    print(f"{'UNIT':<24}{'HRI':>8}{'TRI':>8}{'CES':>8}{'CES*':>8}{'CC':>8}")
    for row in results:
        print(
            f"{row['unit_name']:<24}{row['HRI']:>8.1f}{row['TRI']:>8.1f}"
            f"{row['CES']:>8.1f}{row['CES_corrected']:>8.1f}{row['coverage_confidence']:>8.2f}"
        )


if __name__ == "__main__":
    main()
