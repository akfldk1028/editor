# Local Qwen topology validation

Local-only Qwen3-4B NF4 runs. No external API was used.

## Rectangular office

- Input: `datasets/manifests/sample_mass_office_commercial.json`, floor 2
- Accepted: 2/2
- Distinct geometry: 2/2
- Scores: 0.9203, 0.8895
- Evidence: `office.review.json`

## L-shaped neighborhood commercial

- Input: `datasets/manifests/sample_mass_l_setback_office.json`, floor 1
- Accepted: 2/2
- Distinct geometry: 2/2
- Scores: 0.8514, 0.8514
- Both sales rooms touch the supplied street frontage.
- Evidence: `commercial-l.review.json`

## Visual limits

- Alternatives currently change room assignments/order within a stable
  circulation/core family; they are not yet distinct structural schemes.
- Labels still overlap around dense door/core annotations.
- Regulatory screening remains `not_checked` where typed jurisdiction,
  effective date, occupancy, and travel-distance facts are absent.
