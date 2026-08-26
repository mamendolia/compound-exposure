# 07 — Ingesting real data

The synthetic dataset exists to demonstrate the method. This document covers
running it on an actual engagement, where the difficulty is never the
arithmetic — it is that the export does not contain what the model assumes.

## The roster is not optional

A phishing export contains only the people who were enrolled in a campaign.
Someone who was never enrolled does not appear as a row of zeroes; they do not
appear at all.

That means the export alone cannot produce the denominator, and coverage
confidence — one of the two load-bearing ideas in this method — cannot be
computed from it. A separate headcount list per unit is required, and it has to
come from somewhere authoritative: HR, the identity provider, the payroll
system. Not from the awareness platform, which is precisely the source whose
blind spot you are trying to measure.

`tools/ingest_knowbe4.py` refuses to run without one.

## The denominator is delivery, not scheduling

The export records both. They differ by the messages that bounced, and the gap
is rarely small in organisations with stale directories.

A bounced message was never seen by anyone. Counting it as a send that produced
no click deflates the failure rate — always in the flattering direction, which
is why the error tends to survive review. Rows with a bounce timestamp are
excluded, and the count of exclusions is printed rather than buried.

Archived users are excluded on the same principle.

## Failure is graded, not binary

The export distinguishes five ways a person can fail a simulation. They are not
equivalent, and collapsing them into one boolean throws away the distinction
that most affects what you should do about it.

| Action | Weight | Reasoning |
|--------|--------|-----------|
| Clicked link | 0.50 | Engagement with the lure; no payload delivered |
| QR code scanned | 0.50 | Same, by a different route |
| Attachment opened | 0.70 | Content reached the endpoint |
| Macro enabled | 1.00 | Content executed |
| Credentials entered | 1.00 | Compromise equivalent; the report arrives too late |

Each delivered message is scored by the **worst** action recorded against it,
so a person who clicked and then submitted credentials counts once, at the
higher weight. A person's susceptibility is the sum of those weights over the
messages delivered to them.

Like every weight in this method, these are argued rather than fitted. The
ladder encodes one claim: that proximity to execution matters more than
engagement. Someone who disagrees can change five numbers in one place.

This also matters for segmentation. A function that handles invoices is
attacked with attachments; measuring only link clicks will report it as
healthier than it is. The graded scale is what makes the lure-family argument
in `docs/03` visible in the numbers.

## Attribution: the part that breaks

The model needs every person attributed to a business unit. The export offers
several candidate columns, and they are not interchangeable.

**`Group` is the dangerous one.** In practice groups are frequently used to
target campaigns rather than to mirror the organisation. If a person's group is
the group that was phished, attributing units from it is circular reasoning:
you are classifying people by how you selected them. It is also multi-valued —
one person can sit in several groups, and the export will show different values
across campaigns.

The ingestion tool reports how many people appear under more than one unit
value. If that count is not near zero, the column is a targeting artefact and
`Department` or `Division` is the better source. Check this **before** reading
any score, not after.

Where the export and the roster disagree, the roster wins: it is the
authoritative record, and people present in the export but absent from the
roster are flagged, because they silently inflate coverage.

## Personal data

The export carries a great deal of it — names, job titles, managers, phone
numbers, IP addresses, employee numbers. None of it is needed.

The email address is hashed with a salt supplied through the environment
(`EXPOSURE_SALT`) and every other personal column is dropped rather than
carried forward. The tool refuses to start without a salt, and refuses to map a
personal column into any role other than the identifier.

Three operational rules follow:

- **Use the same salt across periods of one engagement.** Cohort analysis
  matches people between periods by pseudonym; a changed salt silently produces
  an empty cohort and a change analysis that reports nothing.
- **Use a different salt per client.** Otherwise the same person at two clients
  hashes identically.
- **Never commit it.** The salt plus a list of candidate email addresses is
  enough to reverse the pseudonyms, which is the whole point of having one.

Aggregation to unit level and the ten-person suppression floor from `docs/01`
still apply to anything that reaches a report.

## What this does not yet cover

- **Training data.** The phishing export carries no enrolment or completion
  columns; those come from a separate export. Until it is loaded, the knowledge
  gap term contributes nothing and the human index is behaviour only.
- **The technical vector.** `compute_exposure.py` expects an asset file. A
  Qualys ingestion equivalent to this one is the next piece.
- **Campaign difficulty.** The export records the template used. Holding it
  constant across periods is a process discipline, not something the tool can
  enforce — see `docs/06`.

## Order of operations

1. Map the columns in a per-client mapping file.
2. Run the ingestion and read the exclusion counts and coverage table.
3. Check the multi-unit warning before trusting attribution.
4. Only then compute scores.

Step 2 is the one people skip, and it is the one that catches every mistake
that would otherwise become a confident number in a report someone signs.
