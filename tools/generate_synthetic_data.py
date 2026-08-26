#!/usr/bin/env python3
"""
Generate a synthetic dataset for the compound-exposure method.

Everything this script produces is invented. No client data is involved at any
point. The seed is fixed, so anyone who clones the repository and runs the
tools in order obtains byte-identical files. That reproducibility is the
evidence that the data is synthetic -- a claim in a README is not.

Two measurement periods can be generated. Person identifiers are stable across
them and each person carries a latent propensity that does not change, so a
closed cohort can be followed. Between periods some people leave and others
join, because a dataset without turnover cannot demonstrate the problem
turnover causes.

Three things differ in the second period, and they are meant to be
disentangled by tools/compare_periods.py rather than assumed:

  1. campaign difficulty is lower -- every unit's click rate falls a little
     for reasons that have nothing to do with any intervention;
  2. three units received an intervention, of markedly different quality;
  3. everything else is sampling noise.

Usage:
    python3 tools/generate_synthetic_data.py --users 2000 --period P1 --outdir data/synthetic
    python3 tools/generate_synthetic_data.py --users 2000 --period P2 --outdir data/synthetic-p2
"""

import argparse
import csv
import hashlib
import os
import random

SEED = 20260820

# ---------------------------------------------------------------------------
# Unit profiles
#
#   share            fraction of the population assigned to the unit
#   criticality      business criticality of the unit, 1..5
#   ppp              baseline phish-prone probability
#   report           baseline probability that a recipient reports the phish
#   overdue          baseline probability that assigned training is overdue
#   qds              baseline Qualys-like detection score of its assets
#   mttr             mean time to remediate critical findings, in days
#   person_coverage  fraction of the headcount enrolled in the platform
#   asset_coverage   fraction of known assets actually scanned
# ---------------------------------------------------------------------------
UNITS = [
    # unit_id,   name,                   share, crit, ppp,  report, overdue, qds, mttr, p_cov, a_cov
    ("SALES",    "Sales & Marketing",     0.14,   3, 0.24,  0.11,   0.31,    52,   41,  0.94,  0.91),
    ("FIN",      "Finance & Admin",       0.07,   5, 0.18,  0.22,   0.14,    47,   28,  0.99,  0.97),
    ("IT",       "IT & Infrastructure",   0.05,   5, 0.06,  0.48,   0.05,    38,   16,  1.00,  0.99),
    ("RND",      "R&D",                   0.11,   4, 0.13,  0.19,   0.22,    61,   57,  0.92,  0.86),
    ("OPS_IT_A", "Operations - Site A",   0.22,   4, 0.29,  0.06,   0.44,    68,  121,  0.61,  0.74),
    ("OPS_IT_B", "Operations - Site B",   0.18,   3, 0.26,  0.08,   0.38,    64,   96,  0.68,  0.79),
    ("OPS_PL",   "Operations - Poland",   0.15,   3, 0.33,  0.04,   0.52,    71,  164,  0.38,  0.55),
    ("CORP_UK",  "Corporate - UK",        0.08,   4, 0.16,  0.14,   0.19,    55,   49,  0.72,  0.83),
]

ASSETS_PER_HEAD = 1.6
ATTRITION = 0.08  # share of the P1 population that has left by P2

# Campaign difficulty. The second campaign is easier to spot. This is the
# confounder the change analysis has to remove: every unit improves a little
# for a reason that is a property of the campaign, not of the population.
PERIODS = {
    "P1": {"difficulty": 1.00, "label": "H1 2026"},
    "P2": {"difficulty": 0.86, "label": "H2 2026"},
}

# Interventions applied between the periods, as multipliers on each person's
# latent propensity. Quality varies on purpose: one serious reporting
# programme, one weaker copy of it, and one content-only refresh that should
# turn out to be indistinguishable from doing nothing.
INTERVENTIONS = {
    "OPS_IT_A": {"click": 0.80, "report": 2.30, "overdue": 0.72, "mttr": 0.78,
                 "note": "reporting path + targeted coaching"},
    "CORP_UK":  {"click": 0.87, "report": 1.80, "overdue": 0.82, "mttr": 0.95,
                 "note": "reporting path only"},
    "SALES":    {"click": 0.98, "report": 1.04, "overdue": 0.92, "mttr": 1.00,
                 "note": "content refresh only"},
}

UNIT_IDS = [u[0] for u in UNITS]
CONTROL_UNITS = [u for u in UNIT_IDS if u not in INTERVENTIONS]


def stable_rng(*parts):
    """A random stream keyed by content, not by call order.

    Python's hash() is salted per process, so it cannot be used here. Keying on
    a digest means a person's latent traits are identical no matter which
    period is generated, or in which order.
    """
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return random.Random(int(hashlib.md5(key).hexdigest()[:12], 16))


def clamp(value, low=0.005, high=0.95):
    return max(low, min(high, value))


def latent_traits(person_id, profile):
    """Propensities that belong to the person and never change."""
    ppp, report, overdue = profile[4], profile[5], profile[6]
    rng = stable_rng("latent", person_id)
    return {
        "click": clamp(rng.gauss(ppp, ppp * 0.35)),
        "report": clamp(rng.gauss(report, report * 0.45)),
        "overdue": clamp(rng.gauss(overdue, overdue * 0.30)),
        "enrolled_roll": rng.random(),
        "attrition_roll": rng.random(),
    }


def build_roster(total_users):
    """Everyone who exists in P1, plus the joiners who arrive for P2."""
    roster = []
    person_id = 0
    for profile in UNITS:
        unit_id = profile[0]
        headcount = max(1, round(total_users * profile[2]))
        for _ in range(headcount):
            person_id += 1
            roster.append({"person_id": f"P{person_id:05d}", "unit_id": unit_id,
                           "profile": profile, "joiner": False})

    # Joiners replace leavers one for one, so headcount is stable and the only
    # thing that changes is who is in the population.
    joiner_id = person_id
    for entry in list(roster):
        traits = latent_traits(entry["person_id"], entry["profile"])
        if traits["attrition_roll"] < ATTRITION:
            joiner_id += 1
            roster.append({"person_id": f"P{joiner_id:05d}",
                           "unit_id": entry["unit_id"],
                           "profile": entry["profile"], "joiner": True})
    return roster


def generate_people(roster, period):
    difficulty = PERIODS[period]["difficulty"]
    rows = []

    for entry in roster:
        pid, unit_id, profile = entry["person_id"], entry["unit_id"], entry["profile"]
        traits = latent_traits(pid, profile)

        # Presence: joiners do not exist in P1, leavers are gone by P2.
        if period == "P1" and entry["joiner"]:
            continue
        if period == "P2" and not entry["joiner"] and traits["attrition_roll"] < ATTRITION:
            continue

        in_scope = traits["enrolled_roll"] < profile[9]

        if not in_scope:
            rows.append({
                "person_id": pid, "unit_id": unit_id, "period": period,
                "in_scope": 0, "phish_sent": 0, "phish_clicked": 0,
                "phish_reported": 0, "credential_submitted": 0,
                "training_assigned": 0, "training_completed": 0,
            })
            continue

        effect = INTERVENTIONS.get(unit_id) if period == "P2" else None
        p_click = clamp(traits["click"] * difficulty * (effect["click"] if effect else 1.0))
        p_report = clamp(traits["report"] * (effect["report"] if effect else 1.0))
        p_overdue = clamp(traits["overdue"] * (effect["overdue"] if effect else 1.0))

        rng = stable_rng("draw", pid, period)
        sent = rng.choice([3, 4, 4, 5])
        clicked = sum(1 for _ in range(sent) if rng.random() < p_click)

        reported = 0
        for i in range(sent):
            penalty = 0.35 if i < clicked else 1.0
            if rng.random() < p_report * penalty:
                reported += 1

        submitted = sum(1 for _ in range(clicked) if rng.random() < 0.46)

        assigned = rng.choice([2, 3, 3, 4])
        completed = sum(1 for _ in range(assigned) if rng.random() > p_overdue)

        rows.append({
            "person_id": pid, "unit_id": unit_id, "period": period,
            "in_scope": 1, "phish_sent": sent, "phish_clicked": clicked,
            "phish_reported": reported, "credential_submitted": submitted,
            "training_assigned": assigned, "training_completed": completed,
        })

    rows.sort(key=lambda r: r["person_id"])
    return rows


def generate_assets(total_users, period):
    rows = []
    asset_id = 0
    for profile in UNITS:
        unit_id, crit, qds, mttr, a_cov = profile[0], profile[3], profile[7], profile[8], profile[10]
        headcount = max(1, round(total_users * profile[2]))
        count = max(1, round(headcount * ASSETS_PER_HEAD))

        effect = INTERVENTIONS.get(unit_id) if period == "P2" else None
        mttr_period = mttr * (effect["mttr"] if effect else 1.0)

        for _ in range(count):
            asset_id += 1
            aid = f"A{asset_id:05d}"
            rng = stable_rng("asset", aid, period)
            scope_rng = stable_rng("asset-scope", aid)

            if scope_rng.random() >= a_cov:
                rows.append({
                    "asset_id": aid, "unit_id": unit_id, "period": period,
                    "in_scope": 0, "asset_criticality": 0, "qds_max": 0,
                    "oldest_critical_age_days": 0, "kev_count": 0,
                })
                continue

            asset_crit = max(1, min(5, round(rng.gauss(crit, 0.9))))
            qds_max = max(0, min(100, round(rng.gauss(qds, 16))))
            age = max(0, round(rng.expovariate(1 / mttr_period)))
            kev = rng.choice([1, 1, 2]) if (qds_max > 80 and rng.random() < 0.28) else 0

            rows.append({
                "asset_id": aid, "unit_id": unit_id, "period": period,
                "in_scope": 1, "asset_criticality": asset_crit, "qds_max": qds_max,
                "oldest_critical_age_days": age, "kev_count": kev,
            })
    return rows


def generate_units(total_users):
    return [{
        "unit_id": u[0],
        "unit_name": u[1],
        "headcount": max(1, round(total_users * u[2])),
        "business_criticality": u[3],
        "arm": "treated" if u[0] in INTERVENTIONS else "control",
        "intervention": INTERVENTIONS[u[0]]["note"] if u[0] in INTERVENTIONS else "",
    } for u in UNITS]


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"refusing to write an empty file: {path}")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        # lineterminator is pinned to "\n": csv.writer defaults to CRLF, which
        # collides with the repository's LF normalisation and makes every
        # regeneration look like a change to Git. Reproducibility is the point.
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0].keys()), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path}  ({len(rows)} rows)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=2000)
    parser.add_argument("--period", choices=sorted(PERIODS), default="P1")
    parser.add_argument("--outdir", default="data/synthetic")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    period = args.period
    print(f"Generating synthetic dataset — period {period} "
          f"({PERIODS[period]['label']}), {args.users} users, seed {SEED}")

    roster = build_roster(args.users)
    write_csv(os.path.join(args.outdir, "units.csv"), generate_units(args.users))
    write_csv(os.path.join(args.outdir, "people.csv"), generate_people(roster, period))
    write_csv(os.path.join(args.outdir, "assets.csv"), generate_assets(args.users, period))
    print("Done. This data is invented and must never be used as an industry benchmark.")


if __name__ == "__main__":
    main()
