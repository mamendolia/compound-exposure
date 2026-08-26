#!/usr/bin/env python3
"""
Convert a raw KnowBe4 phishing export into the internal model format.

The export is one row per recipient per campaign. The model needs one row per
person per period, attributed to a business unit, with no personal data
attached. This tool does that conversion and — more importantly — reports what
it could not do, before any score is computed.

Nothing identifying survives the conversion. The email address is hashed with a
salt that stays out of the repository, and every other personal column in the
export (name, job title, manager, phone, IP address, employee number) is
dropped rather than carried forward.

Two inputs are required:

  --phishing   the KnowBe4 campaign export
  --roster     a headcount list: one row per employee, with a unit

The roster is not optional. The export contains only people who were enrolled
in a campaign, so it cannot tell you who was missing — and coverage is a
headline output of this method, not a detail.

Usage:
    python3 tools/ingest_knowbe4.py \
        --phishing raw/knowbe4-h1.csv \
        --roster raw/roster.csv \
        --mapping mappings/example-client.json \
        --outdir data/client-h1 \
        --period P1
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Graded failure severity.
#
# The export distinguishes five failure actions. They are not equivalent: a
# click means the person engaged with the lure, enabling a macro means content
# executed. Collapsing them into one boolean throws away the distinction that
# matters most for choosing an intervention.
#
# Each delivered message is scored by the WORST action that occurred on it, so
# a person who clicked and then submitted credentials counts once, at the
# higher weight.
#
# These weights are argued, not fitted — like every other weight in this
# method. See docs/07-ingesting-real-data.md.
# ---------------------------------------------------------------------------
FAILURE_SEVERITY = {
    "opened_attachment": 0.70,
    "enabled_macro": 1.00,
    "scanned_qr": 0.50,
    "clicked": 0.50,
    "entered_data": 1.00,
}

PERSONAL_COLUMNS_NEVER_KEPT = {
    "email", "first name", "last name", "job title", "manager name",
    "manager email", "phone number", "mobile phone number", "extension",
    "ip address", "ip location", "employee number", "comment",
}


def norm(text):
    return (text or "").strip().lower().lstrip("\ufeff")


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"empty or unreadable: {path}")
    return rows


def get(row, column, lookup):
    """Fetch a value by mapped column name, case-insensitively."""
    if not column:
        return ""
    actual = lookup.get(norm(column))
    return (row.get(actual, "") or "").strip() if actual else ""


def filled(value):
    """KnowBe4 records events as timestamps; empty means it did not happen."""
    return value not in ("", "-", "0", "false", "False", "null", "None")


def pseudonymise(value, salt):
    return "P" + hashlib.sha256((salt + "|" + norm(value)).encode()).hexdigest()[:12]


def load_mapping(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def build_lookup(rows):
    return {norm(k): k for k in rows[0].keys()}


def ingest(phishing_rows, roster_rows, mapping, salt, period):
    p_map = mapping["phishing_columns"]
    r_map = mapping["roster_columns"]
    p_lookup = build_lookup(phishing_rows)
    r_lookup = build_lookup(roster_rows)

    warnings = []
    dropped = defaultdict(int)

    # --- roster: the denominator -------------------------------------------
    roster = {}
    for row in roster_rows:
        ident = get(row, r_map["identifier"], r_lookup)
        unit = get(row, r_map["unit"], r_lookup)
        if not ident:
            dropped["roster rows with no identifier"] += 1
            continue
        if not unit:
            unit = mapping.get("unattributed_unit", "UNATTRIBUTED")
            dropped["roster rows with no unit"] += 1
        roster[pseudonymise(ident, salt)] = unit

    # --- phishing: the measurement -----------------------------------------
    people = defaultdict(lambda: {
        "delivered": 0, "failure_weight": 0.0, "any_failure": 0,
        "reported": 0, "entered_data": 0, "units_seen": set(),
    })

    for row in phishing_rows:
        ident = get(row, p_map["identifier"], p_lookup)
        if not ident:
            dropped["rows with no identifier"] += 1
            continue

        if p_map.get("archived_at") and filled(get(row, p_map["archived_at"], p_lookup)):
            dropped["rows for archived users"] += 1
            continue

        # The denominator is delivery, not scheduling. A bounced message was
        # never seen by anyone; counting it as an unclicked send deflates the
        # failure rate, always in the flattering direction.
        if p_map.get("bounced_at") and filled(get(row, p_map["bounced_at"], p_lookup)):
            dropped["bounced messages"] += 1
            continue
        if p_map.get("delivered_at") and not filled(get(row, p_map["delivered_at"], p_lookup)):
            dropped["messages never delivered"] += 1
            continue

        pid = pseudonymise(ident, salt)
        entry = people[pid]
        entry["delivered"] += 1

        unit = get(row, p_map["unit"], p_lookup)
        if unit:
            entry["units_seen"].add(unit)

        severity = 0.0
        for action, weight in FAILURE_SEVERITY.items():
            column = p_map.get(action)
            if column and filled(get(row, column, p_lookup)):
                severity = max(severity, weight)
                if action == "entered_data":
                    entry["entered_data"] += 1
        if severity > 0:
            entry["any_failure"] += 1
        entry["failure_weight"] += severity

        if p_map.get("reported") and filled(get(row, p_map["reported"], p_lookup)):
            entry["reported"] += 1

    # --- attribution --------------------------------------------------------
    multi_unit = [p for p, e in people.items() if len(e["units_seen"]) > 1]
    if multi_unit:
        warnings.append(
            f"{len(multi_unit)} people appear under more than one value of the "
            f"unit column across campaigns. If that column is a campaign "
            f"targeting group rather than an org unit, attribution is circular "
            f"— see docs/07."
        )

    not_in_roster = [p for p in people if p not in roster]
    if not_in_roster:
        warnings.append(
            f"{len(not_in_roster)} measured people are absent from the roster. "
            f"They are attributed from the export's own unit column, which is "
            f"weaker evidence, and they inflate coverage above its true value."
        )

    rows_out = []
    for pid, unit in sorted(roster.items()):
        entry = people.get(pid)
        if not entry or entry["delivered"] == 0:
            rows_out.append({
                "person_id": pid, "unit_id": unit, "period": period,
                "in_scope": 0, "phish_sent": 0, "phish_clicked": 0,
                "failure_weight": 0.0, "phish_reported": 0,
                "credential_submitted": 0, "training_assigned": 0,
                "training_completed": 0,
            })
            continue
        rows_out.append({
            "person_id": pid, "unit_id": unit, "period": period,
            "in_scope": 1,
            "phish_sent": entry["delivered"],
            "phish_clicked": entry["any_failure"],
            "failure_weight": round(entry["failure_weight"], 4),
            "phish_reported": entry["reported"],
            "credential_submitted": entry["entered_data"],
            "training_assigned": 0, "training_completed": 0,
        })

    # Measured people missing from the roster still have to be scored.
    for pid in sorted(not_in_roster):
        entry = people[pid]
        units = entry["units_seen"]
        unit = sorted(units)[0] if units else mapping.get("unattributed_unit", "UNATTRIBUTED")
        rows_out.append({
            "person_id": pid, "unit_id": unit, "period": period,
            "in_scope": 1,
            "phish_sent": entry["delivered"],
            "phish_clicked": entry["any_failure"],
            "failure_weight": round(entry["failure_weight"], 4),
            "phish_reported": entry["reported"],
            "credential_submitted": entry["entered_data"],
            "training_assigned": 0, "training_completed": 0,
        })

    units_out = []
    per_unit = defaultdict(lambda: [0, 0])
    for row in rows_out:
        slot = per_unit[row["unit_id"]]
        slot[0] += 1
        slot[1] += row["in_scope"]
    for unit, (headcount, measured) in sorted(per_unit.items()):
        units_out.append({
            "unit_id": unit,
            "unit_name": unit,
            "headcount": headcount,
            "business_criticality": mapping.get("criticality", {}).get(unit, 3),
            "arm": mapping.get("arms", {}).get(unit, "control"),
            "intervention": "",
        })

    return rows_out, units_out, dropped, warnings, per_unit


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phishing", required=True)
    parser.add_argument("--roster", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--period", default="P1")
    parser.add_argument("--salt", default=os.environ.get("EXPOSURE_SALT", ""))
    args = parser.parse_args()

    if not args.salt:
        sys.exit(
            "No pseudonymisation salt. Set EXPOSURE_SALT in the environment or "
            "pass --salt. Use the same value for every period of the same "
            "engagement, or cohorts will not match between periods; use a "
            "different value for different clients. Never commit it."
        )

    mapping = load_mapping(args.mapping)
    phishing_rows = read_csv(args.phishing)
    roster_rows = read_csv(args.roster)

    # Refuse to proceed if a column that must never be carried is mapped.
    for role, column in mapping["phishing_columns"].items():
        if role != "identifier" and norm(column) in PERSONAL_COLUMNS_NEVER_KEPT:
            sys.exit(f"mapping error: '{column}' is personal data and cannot be "
                     f"used as '{role}'")

    rows, units, dropped, warnings, per_unit = ingest(
        phishing_rows, roster_rows, mapping, args.salt, args.period
    )

    os.makedirs(args.outdir, exist_ok=True)
    write_csv(os.path.join(args.outdir, "people.csv"), rows)
    write_csv(os.path.join(args.outdir, "units.csv"), units)

    print(f"Ingested {len(phishing_rows)} export rows -> {len(rows)} people "
          f"in {len(units)} units, period {args.period}")
    print(f"  {args.outdir}/people.csv")
    print(f"  {args.outdir}/units.csv")

    if dropped:
        print("\nRows excluded:")
        for reason, count in sorted(dropped.items()):
            print(f"  {count:>6}  {reason}")

    print("\nCoverage by unit — this is the number to check before trusting any score:")
    print(f"  {'UNIT':<28}{'HEADCOUNT':>10}{'MEASURED':>10}{'COVERAGE':>10}")
    for unit, (headcount, measured) in sorted(per_unit.items()):
        cov = measured / headcount if headcount else 0
        flag = "  <-- thin" if cov < 0.60 else ""
        print(f"  {unit[:28]:<28}{headcount:>10}{measured:>10}{cov:>9.0%}{flag}")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")

    print("\nTraining columns are zero: this export carries phishing only. "
          "Load the enrolment export separately, or the knowledge-gap term "
          "contributes nothing.")


if __name__ == "__main__":
    main()
