# Evaluation results

Corpus: 4 insurer wordings, 283 PDF pages, 997 indexed chunks.

## Retrieval (42 hand-labelled broker questions, filtered to one insurer)

| Config | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---|---|---|---|
| dense only | 36% | 64% | 74% | 0.50 |
| BM25 only | 45% | 64% | 71% | 0.55 |
| hybrid (dense+BM25) | 40% | 69% | 79% | 0.56 |
| hybrid + insurance synonyms | 55% | 83% | 95% | 0.69 |

## Claim triage (30 hand-written claim scenarios)

- Peril classification accuracy: 83%
- Correct excess from schedule: 87%
- Exclusion red flags: precision 100%, recall 89%
- Escape-of-water claims where a correct clause page was cited: 8/8
- Misclassified: "Damp patch spreading for months behind the shower, tiles now loose" (expected escape_of_water, got None); "Water got behind the bath because the silicone sealant had failed" (expected escape_of_water, got None); "Rainwater overflowing from a blocked gutter came through the wall" (expected escape_of_water, got None); "Lightning strike damaged the TV aerial and the boiler" (expected storm, got escape_of_water); "Someone smashed a window and took the bike from the hallway" (expected theft, got storm)

## PII redaction (200 synthetic notes, 523 PII values)

- Recall: 96.2% (20 values leaked)
- Policy chunks altered by redaction (false-positive check): 126/997 (12.6%), tags: {'CARD_NUMBER': 10, 'PHONE': 140, 'POSTCODE': 61, 'EMAIL': 30, 'ACCOUNT_NUMBER': 2}

## Guardrails

- Responses with disclaimer: 82/82
- Coverage responses where every passage has a citation: 72/72
- Drafts sent without human approval: 0/20
- Drafts with client PII left in the body: 0/20

## Latency (in-process, CPU, ms)

| Tool | p50 | p95 | n |
|---|---|---|---|
| search_policy_wording | 164.0 | 184.3 | 42 |
| check_claim_eligibility | 324.4 | 348.9 | 30 |
| get_client_policies | 0.3 | 0.7 | 7 |
| compare_coverage | 635.0 | 640.9 | 3 |
| draft_client_email | 1.8 | 7.0 | 20 |
