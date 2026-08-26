#!/usr/bin/env python3
"""
Turn the synthetic dataset into a KnowBe4-shaped export, so the ingestion tool
can be demonstrated end to end without anyone's real data.

The output imitates the real export's shape: one row per recipient per
campaign, events recorded as timestamps, bounced and archived rows present so
that the exclusion logic has something to exclude, and the full complement of
personal columns that the ingestion is supposed to drop.

Everything is invented. Addresses are on example.invalid, which cannot resolve.

Usage:
    python3 tools/make_example_export.py --indir data/synthetic \
        --out-phishing examples/knowbe4-export-sample.csv \
        --out-roster examples/roster-sample.csv --people 200
"""

import argparse
import csv
import hashlib
import os
import random

UNIT_LABELS = {
    "SALES": "Sales & Marketing", "FIN": "Finance", "IT": "IT",
    "RND": "R&D", "OPS_IT_A": "Operations Site A",
    "OPS_IT_B": "Operations Site B", "OPS_PL": "Operations Poland",
    "CORP_UK": "Corporate UK",
}

HEADERS = [
    "Email", "Clicked At", "Replied At", "Data Entered At",
    "Attachment Opened At", "Macro Enabled At", "QR Code Scanned At",
    "Opened At", "Reported", "Scheduled", "Delivered At", "Bounced At",
    "Bounce Code", "Bounce Reason", "Failure Ignored At", "First Name",
    "Last Name", "Job Title", "Group", "Manager Name", "Manager Email",
    "Location", "Division", "Employee Number", "IP Address", "IP Location",
    "Browser", "Browser Version", "Operating System", "Email Template",
    "Created At", "Time Zone", "Phone Number", "Extension",
    "Mobile Phone Number", "Current PPP", "Archived At", "Risk Score",
    "Locale", "Organization", "Department", "Language", "Comment",
    "Employee Start Date",
]

BASE = "2026-03-%02dT%02d:%02d:00Z"


def stamp(rng):
    return BASE % (rng.randint(2, 27), rng.randint(7, 18), rng.randint(0, 59))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--indir", default="data/synthetic")
    ap.add_argument("--out-phishing", default="examples/knowbe4-export-sample.csv")
    ap.add_argument("--out-roster", default="examples/roster-sample.csv")
    ap.add_argument("--people", type=int, default=200)
    args = ap.parse_args()

    with open(os.path.join(args.indir, "people.csv"), newline="", encoding="utf-8") as fh:
        everyone = list(csv.DictReader(fh))
    # Sample across the whole file rather than taking the first N rows: people
    # are ordered by identifier and identifiers are assigned unit by unit, so
    # a head slice would produce a fixture containing exactly one unit.
    stride = max(1, len(everyone) // args.people)
    source = everyone[::stride][: args.people]

    rows, roster = [], []
    for person in source:
        pid = person["person_id"]
        unit = UNIT_LABELS.get(person["unit_id"], person["unit_id"])
        rng = random.Random(int(hashlib.md5(pid.encode()).hexdigest()[:8], 16))
        email = f"user{pid[1:]}@example.invalid"
        roster.append({"email": email, "department": unit})

        sent = int(person["phish_sent"])
        clicked = int(person["phish_clicked"])
        reported = int(person["phish_reported"])
        entered = int(person["credential_submitted"])
        in_scope = person["in_scope"] == "1"
        if not in_scope:
            continue  # never enrolled: absent from the export, present in roster

        # One bounced row per few people, so the exclusion logic is exercised.
        extra_bounce = rng.random() < 0.06

        for i in range(sent + (1 if extra_bounce else 0)):
            bounced = extra_bounce and i == sent
            did_click = i < clicked
            did_enter = i < entered
            # Some failures arrive as attachment or macro rather than a click.
            variant = rng.random()
            row = {h: "" for h in HEADERS}
            row.update({
                "Email": email,
                "Scheduled": stamp(rng),
                "Delivered At": "" if bounced else stamp(rng),
                "Bounced At": stamp(rng) if bounced else "",
                "Bounce Code": "550" if bounced else "",
                "Bounce Reason": "mailbox unavailable" if bounced else "",
                "Opened At": stamp(rng) if (not bounced and rng.random() < 0.7) else "",
                "Reported": stamp(rng) if i < reported and not bounced else "",
                "First Name": "Given", "Last Name": "Family",
                "Job Title": "Role", "Group": unit, "Department": unit,
                "Division": unit, "Location": "Site",
                "Manager Name": "Manager", "Manager Email": "mgr@example.invalid",
                "Employee Number": pid[1:], "IP Address": "203.0.113.10",
                "Email Template": f"template-{(i % 3) + 1}",
                "Organization": "Example Org", "Language": "en",
                "Current PPP": "0.0", "Risk Score": "0.0",
            })
            if did_click and not bounced:
                if variant < 0.55:
                    row["Clicked At"] = stamp(rng)
                elif variant < 0.75:
                    row["Attachment Opened At"] = stamp(rng)
                elif variant < 0.88:
                    row["Clicked At"] = stamp(rng)
                    row["Macro Enabled At"] = stamp(rng)
                else:
                    row["QR Code Scanned At"] = stamp(rng)
            if did_enter and not bounced:
                row["Data Entered At"] = stamp(rng)
                if not row["Clicked At"]:
                    row["Clicked At"] = stamp(rng)
            rows.append(row)

    for path, data, fields in (
        (args.out_phishing, rows, HEADERS),
        (args.out_roster, roster, ["email", "department"]),
    ):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(data)
        print(f"  {path}  ({len(data)} rows)")


if __name__ == "__main__":
    main()
