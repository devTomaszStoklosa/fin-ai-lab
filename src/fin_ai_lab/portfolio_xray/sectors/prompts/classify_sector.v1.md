---
description: Classify an equity position into a GICS-like sector.
variables:
  - instrument_name
  - symbol
  - sectors
---
Classify the company below into exactly one of these sectors: {{sectors}}.

Company name: {{instrument_name}}
Ticker (if known): {{symbol}}

If you are not confident which sector applies, or the name does not clearly
identify a company (e.g. it looks like a fund, note, or placeholder), answer
with "other" instead of guessing.

Respond only with the requested structured classification.
