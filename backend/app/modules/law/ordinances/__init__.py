"""Local ordinances that can bind one parcel on one assessment date, found nationwide from official records.

`jurisdiction` reads which local governments the parcel sits in (registry address, cross-checked with the
PNU's codes); `search` turns every page of a law.go.kr ordinance search, current and historical editions,
into records with a truthful completeness flag; `service` composes them for a parcel: candidates are kept
only when their issuing authority is one of the parcel's jurisdictions and an edition was in force on the
date. Nothing here infers applicability — a found ordinance is a source to read, not a verdict.
"""
