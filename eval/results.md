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

- Peril classification accuracy: 97%
- Correct excess from schedule: 100%
- Exclusion red flags: precision 100%, recall 89%
- Escape-of-water claims where a correct clause page was cited: 11/11
- Misclassified: "Someone smashed a window and took the bike from the hallway" (expected theft, got accidental_damage)
- Held-out set (15 scenarios written before tuning): peril accuracy 73%, excess accuracy 73%

## PII redaction (200 synthetic notes, 523 PII values)

- Recall: 100.0% (0 values leaked)
- False positives on 45 PII-free claim descriptions: 0
- Policy chunks that would be altered if redaction ran on wordings (insurer phone numbers, addresses - why redaction is scoped to client data): 126/997 (12.6%)

## Guardrails

- Responses with disclaimer: 82/82
- Coverage responses where every passage has a citation: 72/72
- Drafts sent without human approval: 0/20
- Drafts with client PII left in the body: 0/20

## Latency (in-process, CPU, ms)

| Tool | p50 | p95 | n |
|---|---|---|---|
| search_policy_wording | 232.0 | 377.4 | 42 |
| check_claim_eligibility | 295.4 | 554.7 | 30 |
| get_client_policies | 0.3 | 0.6 | 7 |
| compare_coverage | 1092.5 | 1112.6 | 3 |
| draft_client_email | 1.2 | 2.0 | 20 |
