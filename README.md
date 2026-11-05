# Policy Assistant MCP server

An MCP server for insurance brokers. It answers coverage questions from real, public insurer
policy wordings, with a citation for every answer, PII redaction on client data, a
"not advice" disclaimer, and human sign-off before anything goes to a client.

Demo question: *"Is water damage from a burst pipe covered under Sarah Thompson's home policy, and what's the excess?"*
The agent looks up the client's active policy, finds the escape-of-water ("water leakage") clause in the RIAS
wording (pages 23-24), takes the £250 escape-of-water excess from the schedule and answers with citations.

## Tools

| Tool | Type | What it does |
|---|---|---|
| `search_policy_wording(query, insurer_or_doc_id?, top_k?)` | read | Hybrid search (ChromaDB embeddings + BM25) over the policy PDFs. Each hit has insurer, document, page and a link to the exact PDF page. |
| `get_client_policies(client)` | read | Looks up a client by id, policy id or name in SQLite. Returns schedules (cover type, sums insured, excesses, optional covers). Name, email and phone are masked. |
| `compare_coverage(policy_a, policy_b, topics?)` | read | Side-by-side cited clauses for each topic. Each side is a client policy id (also compares schedule excesses) or an insurer. |
| `check_claim_eligibility(claim_description, policy_id)` | read | Finds the likely peril, the excess from the schedule, red flags (gradual damage, unoccupancy, wear and tear...), missing optional cover, and the relevant cover and exclusion clauses. Gives an indicative view only. |
| `draft_client_email(client_id, subject, body, policy_id?)` | write | Saves a **draft** as `PENDING_APPROVAL`. It never sends. |

It also has resources `policy://documents` and `policy://disclaimer`, and a `coverage_question` prompt.

## Responsible AI, enforced in code

- **PII redaction**: the model only gets masked client data (`Sarah T.`, `s***@example.com`). Free text (claim descriptions, broker notes, email drafts, the audit log) is scrubbed for emails, phone numbers, postcodes, NI numbers, card numbers, dates of birth and the client's known details.
- **Citations**: every passage comes with `[Insurer Product, p.N]` and a `#page=N` link. The server instructions tell the model to cite and to say when it can't find something in the wording.
- **Disclaimer**: every tool response has `disclaimer` and `requires_human_review: true`. The disclaimer is added to every email draft automatically.
- **Human sign-off**: the agent has no send tool. A broker reviews drafts outside the agent:
  ```bash
  policy-assistant drafts                          # list pending drafts
  policy-assistant show DRAFT-0001                 # real name/email filled in, for the human only
  policy-assistant approve DRAFT-0001 --reviewer "Jane Broker"   # type APPROVE to send
  policy-assistant reject  DRAFT-0001 --reviewer "Jane Broker" --reason "wrong excess"
  ```
  Sending is simulated: approved emails are written to `data/outbox/sent/*.eml` with an `X-Approved-By` header.
- **Audit trail**: every tool call and every approval goes to `data/audit.log.jsonl`, redacted.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
policy-assistant setup        # downloads the PDFs, seeds SQLite, builds the ChromaDB index (~20s)
pytest -q
python scripts/demo.py        # runs the burst-pipe scenario over real MCP (stdio)
```

The policy PDFs aren't committed because they're the insurers' copyright. `data/sources.json` lists
their public URLs (RIAS, esure, Aviva, AA home insurance). To add another insurer, add an entry there and
run `policy-assistant setup` again.

The clients and policies in `policy_assistant/db.py` are fictional.

## Use it from Claude Desktop (or any MCP client)

`claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "policy-assistant": {
      "command": "/absolute/path/to/policy-assistant-mcp/.venv/bin/python",
      "args": ["-m", "policy_assistant.server"],
      "cwd": "/absolute/path/to/policy-assistant-mcp"
    }
  }
}
```
Then ask: *"Is water damage from a burst pipe covered under client Sarah Thompson's home policy, and what's the excess?"*

To poke at the tools in a browser: `mcp dev policy_assistant/server.py` (MCP Inspector, needs Node).

## Measured results

`python -m eval.run_eval` re-runs everything and writes [`eval/results.md`](eval/results.md). Gold labels were written by hand from the PDF pages. `eval/results_baseline.*` is the first run, before fixing what it found.

| What | Result |
|---|---|
| Corpus | 4 insurers, 283 PDF pages, 997 chunks |
| Retrieval, 42 broker questions: Hit@5 / Hit@1 | dense only 74% / 36% → hybrid + synonyms **95% / 55%** (MRR 0.50 → 0.69) |
| Claim triage, peril accuracy | 30 tuning scenarios: 83% → 97%. 15 held-out: 53% → 73% |
| Excess taken from the right schedule field | 87% → 100% (tuning set) |
| PII recall, 523 synthetic values | 96.2% → 100%, 0 false positives on 45 clean texts |
| Responses with disclaimer / cited passages | 82/82, 72/72 |
| Drafts sent without human approval | 0/20 |
| Latency, CPU, in-process (p50) | search ~0.2 s, claim check ~0.3 s, compare ~1 s |

What the first run caught: `"window"` matched the storm keyword `"wind"`, lightning was filed under storm (UK wordings group it with fire), and bracketed landlines like `(0113) 496 0163` slipped past redaction. The held-out set was written before those fixes. Its remaining misses ("thieves", "burglar", "snow", "hot water cylinder") show the limits of keyword triage.

## Layout

```
policy_assistant/
  server.py     MCP server and the 5 tools
  retrieval.py  ChromaDB + BM25 hybrid search, citations
  ingest.py     PDF download, page-level chunking, indexing
  claims.py     peril classification, excess logic, exclusion red flags
  redact.py     PII redaction and masking
  db.py         SQLite schema, fictional seed data, drafts
  cli.py        setup + human approval commands
  audit.py      redacted audit log
scripts/demo.py end-to-end MCP client demo
eval/           labelled eval sets, run_eval.py, results
tests/          pytest
```

## Limitations

- `check_claim_eligibility` is triage, not a claims decision. Peril detection is keyword-based on purpose, so it's predictable and easy to explain.
- PDF text from two-column layouts can come out interleaved, so a chunk may mix columns. Citations still point at the right page.
- The embedding model is Chroma's default (`all-MiniLM-L6-v2`, runs locally on CPU). BM25 fusion and insurance synonyms make up for its weak spots.
