"""Offline evaluation of Policy Assistant. Produces eval/results.json and eval/results.md.

Everything here is measured on this repo's own data: 4 public insurer wordings and the
fictional client table. Gold labels were written by hand from the PDF pages (see GOLD_*).
"""

import json
import random
import re
import statistics
import time
from pathlib import Path

from policy_assistant import claims, config, db, server
from policy_assistant.redact import redact_text
from policy_assistant.retrieval import get_collection, search

OUT = Path(__file__).resolve().parent

# (broker question, doc_id, pages where the answering clause is printed)
GOLD_RETRIEVAL = [
    ("Is a burst pipe covered?", "rias_home", {24, 30}),
    ("Is a burst pipe covered?", "esure_home", {14}),
    ("Is a burst pipe covered?", "aviva_home", {17, 23}),
    ("Is a burst pipe covered?", "aa_home", {20, 28, 39}),
    ("What excess applies to an escape of water claim?", "rias_home", {23, 27, 28, 30, 31}),
    ("What excess applies to an escape of water claim?", "esure_home", {9}),
    ("What excess applies to an escape of water claim?", "aa_home", {9}),
    ("Are roof tiles blown off in high winds covered?", "rias_home", {24}),
    ("Are roof tiles blown off in high winds covered?", "esure_home", {13}),
    ("Are roof tiles blown off in high winds covered?", "aviva_home", {8, 17, 20}),
    ("Are roof tiles blown off in high winds covered?", "aa_home", {17, 19, 27}),
    ("Is fence damage from a storm covered?", "rias_home", {24}),
    ("Is fence damage from a storm covered?", "esure_home", {13}),
    ("Is fence damage from a storm covered?", "aviva_home", {17}),
    ("Is fence damage from a storm covered?", "aa_home", {6, 7, 19}),
    ("What wind speed counts as a storm?", "aviva_home", {8, 20}),
    ("What wind speed counts as a storm?", "aa_home", {7, 17, 19, 27}),
    ("Is a burglary covered?", "rias_home", {25, 30}),
    ("Is a burglary covered?", "esure_home", {13}),
    ("Is a burglary covered?", "aviva_home", {17, 22, 23}),
    ("Is a burglary covered?", "aa_home", {20, 28, 39}),
    ("Are cracks in walls from subsidence covered?", "rias_home", {24, 30}),
    ("Are cracks in walls from subsidence covered?", "esure_home", {13, 14}),
    ("Are cracks in walls from subsidence covered?", "aviva_home", {8, 17}),
    ("Are cracks in walls from subsidence covered?", "aa_home", {17, 21, 29}),
    ("What is the subsidence excess?", "rias_home", {23, 24}),
    ("What is the subsidence excess?", "esure_home", {9}),
    ("What is the subsidence excess?", "aviva_home", {17}),
    ("What is the subsidence excess?", "aa_home", {9}),
    ("Leak caused by failed bathroom sealant or grout", "esure_home", {14}),
    ("Leak caused by failed bathroom sealant or grout", "aviva_home", {4, 17, 23}),
    ("Leak caused by failed bathroom sealant or grout", "aa_home", {7, 55}),
    ("Will they pay to find the source of a leak?", "rias_home", {24, 25}),
    ("Will they pay to find the source of a leak?", "aviva_home", {16}),
    ("Will they pay to find the source of a leak?", "aa_home", {20}),
    ("Is flood damage to contents covered?", "esure_home", {13}),
    ("Is flood damage to contents covered?", "aa_home", {28}),
    ("Is theft from an unattended car covered?", "esure_home", {21}),
    ("Is theft from an unattended car covered?", "aa_home", {12, 44, 45}),
    ("Damage while the house is left empty for months", "rias_home", {24, 25, 30}),
    ("Damage while the house is left empty for months", "esure_home", {14}),
    ("Damage while the house is left empty for months", "aa_home", {20}),
]

# (claim description, policy_id, expected peril key, expected red-flag keywords)
GOLD_CLAIMS = [
    ("Pipe burst under the kitchen sink overnight and soaked the floor", "POL-1001", "escape_of_water", set()),
    ("Washing machine hose split and water came through the ceiling below", "POL-1005", "escape_of_water", set()),
    ("The water tank in the loft cracked during the cold snap", "POL-1004", "escape_of_water", set()),
    ("Frozen pipe burst in the garage while we were on holiday for a week", "POL-1001", "escape_of_water",
     {"unoccupancy"}),
    ("Damp patch spreading for months behind the shower, tiles now loose", "POL-1005", "escape_of_water",
     {"gradual"}),
    ("Slow leak from an old rusted radiator valve stained the carpet", "POL-1004", "escape_of_water",
     {"gradual", "wear"}),
    ("Water got behind the bath because the silicone sealant had failed", "POL-1003", "escape_of_water",
     {"sealant"}),
    ("Leak from the dishwasher flooded the kitchen of the let flat while it was vacant", "POL-1002",
     "escape_of_water", {"unoccupancy"}),
    ("Gale force winds blew roof tiles off and rain came in", "POL-1001", "storm", set()),
    ("Storm knocked down the garden fence", "POL-1005", "storm", set()),
    ("Hail cracked the conservatory roof", "POL-1004", "storm", set()),
    ("River burst its banks and flooded the ground floor", "POL-1004", "flood", set()),
    ("Surface water flooded the basement after heavy rain", "POL-1002", "flood", set()),
    ("Kitchen fire started by the toaster, smoke damage throughout", "POL-1001", "fire", set()),
    ("Chip pan fire burnt the kitchen units", "POL-1005", "fire", set()),
    ("Burglars broke in through the back door and stole a laptop and jewellery", "POL-1003", "theft", set()),
    ("Bike stolen from the shed", "POL-1004", "theft", set()),
    ("House was burgled while we were abroad for three months", "POL-1004", "theft", {"unoccupancy"}),
    ("Large crack appeared in the extension wall, surveyor suspects subsidence", "POL-1001", "subsidence", set()),
    ("Cracks in the walls after the clay soil shrank in the dry summer", "POL-1002", "subsidence", set()),
    ("Spilled red wine on the cream carpet", "POL-1001", "accidental_damage", set()),
    ("Dropped the TV while moving it and the screen smashed", "POL-1005", "accidental_damage", set()),
    ("Accidentally put a foot through the ceiling while in the loft", "POL-1004", "accidental_damage", set()),
    ("Builder doing renovation work cut through a water pipe", "POL-1001", "escape_of_water", {"building work"}),
    ("Rainwater overflowing from a blocked gutter came through the wall", "POL-1005", "escape_of_water",
     {"gutter"}),
    ("Kid knocked a glass of water over the laptop", "POL-1003", "accidental_damage", set()),
    # UK wordings group lightning with fire (e.g. Aviva p.22: "Fire ..., explosion, lightning or earthquake").
    ("Lightning strike damaged the TV aerial and the boiler", "POL-1004", "fire", set()),
    ("Someone smashed a window and took the bike from the hallway", "POL-1001", "theft", set()),
    ("Oil boiler leaked heating oil onto the utility room floor", "POL-1004", "escape_of_water", set()),
    ("Tree branch fell on the car port during strong wind", "POL-1005", "storm", set()),
]
# Written before any fixes driven by GOLD_CLAIMS, to check the fixes generalise.
GOLD_CLAIMS_HOLDOUT = [
    ("Toilet cistern overflowed and water dripped into the living room", "POL-1003", "escape_of_water", set()),
    ("Hot water cylinder split in the airing cupboard", "POL-1001", "escape_of_water", set()),
    ("Thieves took the lawnmower from the garden shed", "POL-1005", "theft", set()),
    ("Strong winds brought down the chimney stack", "POL-1004", "storm", set()),
    ("Electrical fault caused a fire in the loft", "POL-1002", "fire", set()),
    ("Heavy snow collapsed the garage roof", "POL-1004", "storm", set()),
    ("Pipe under the floor had been dripping slowly for weeks before we noticed", "POL-1001", "escape_of_water",
     {"gradual"}),
    ("Sea water flooded the cottage during a high tide", "POL-1004", "flood", set()),
    ("Paint spilled on the new carpet during redecorating", "POL-1001", "accidental_damage", set()),
    ("Neighbour's tree roots caused cracking to the foundations", "POL-1002", "subsidence", set()),
    ("Burglar forced the patio door, nothing taken but the lock was broken", "POL-1003", "theft", set()),
    ("Washing machine leaked while the property was empty for 70 days", "POL-1002", "escape_of_water",
     {"unoccupancy"}),
    ("Kitchen tap left running and the sink overflowed", "POL-1005", "escape_of_water", set()),
    ("Smoke from a neighbour's fire damaged our curtains", "POL-1003", "fire", set()),
    ("Window smashed by a stone thrown up by the lawnmower", "POL-1001", "accidental_damage", set()),
]
FLAG_KEYS = {"gradual": "gradual", "unoccupancy": "unoccupancy", "wear": "wear and tear", "sealant": "sealant",
             "building work": "building/renovation", "gutter": "guttering"}


def retrieval_eval() -> dict:
    configs = {"dense only": ("dense", False), "BM25 only": ("bm25", False),
               "hybrid (dense+BM25)": ("hybrid", False), "hybrid + insurance synonyms": ("hybrid", True)}
    out = {}
    for name, (mode, expand) in configs.items():
        hits1 = hits3 = hits5 = 0
        rr = []
        for q, doc, gold in GOLD_RETRIEVAL:
            pages = [p.page for p in search(q, doc, 5, mode=mode, expand=expand)]
            rank = next((i + 1 for i, p in enumerate(pages) if p in gold), None)
            hits1 += rank == 1
            hits3 += bool(rank and rank <= 3)
            hits5 += bool(rank)
            rr.append(1 / rank if rank else 0)
        n = len(GOLD_RETRIEVAL)
        out[name] = {"hit@1": hits1 / n, "hit@3": hits3 / n, "hit@5": hits5 / n, "mrr": statistics.mean(rr)}
    return {"n_questions": len(GOLD_RETRIEVAL), "configs": out}


def claims_eval(dataset: list = GOLD_CLAIMS) -> dict:
    peril_ok = excess_ok = 0
    tp = fp = fn = 0
    clause_hit = clause_n = 0
    eow_gold = {d: g for q, d, g in GOLD_RETRIEVAL if q == "Is a burst pipe covered?"}
    misses = []
    with db.session() as conn:
        policies = {r["policy_id"]: dict(r) for r in conn.execute("SELECT * FROM policies")}
    for desc, pid, peril, flags in dataset:
        res = server.check_claim_eligibility(desc, pid)
        got = next((p.key for p in claims.PERILS if p.label == res.get("likely_peril")), None)
        if got == peril:
            peril_ok += 1
        else:
            misses.append({"claim": desc, "expected": peril, "got": got})
        expected_excess = claims.applicable_excess(policies[pid], next(p for p in claims.PERILS if p.key == peril))
        if res.get("excess", {}).get("total_excess_gbp") == expected_excess["total_excess_gbp"]:
            excess_ok += 1
        issues = " ".join(res.get("possible_issues", [])).lower()
        found = {k for k, kw in FLAG_KEYS.items() if kw in issues}
        tp += len(found & flags)
        fp += len(found - flags)
        fn += len(flags - found)
        doc = policies[pid]["doc_id"]
        if peril == "escape_of_water" and got == peril:
            clause_n += 1
            clause_hit += any(c["page"] in eow_gold[doc] for c in res["relevant_clauses"])
    n = len(dataset)
    return {
        "n_scenarios": n,
        "peril_accuracy": peril_ok / n,
        "excess_accuracy": excess_ok / n,
        "red_flag_precision": tp / (tp + fp) if tp + fp else 1.0,
        "red_flag_recall": tp / (tp + fn) if tp + fn else 1.0,
        "escape_of_water_correct_clause_cited": f"{clause_hit}/{clause_n}",
        "misclassified": misses,
    }


FIRST = ["Sarah", "James", "Priya", "Tom", "Aisha", "Oliver", "Grace", "Mohammed", "Chloe", "Daniel"]
LAST = ["Thompson", "Okafor", "Patel", "Gallagher", "Rahman", "Wright", "Evans", "Khan", "Murphy", "Hughes"]


def _pii_samples(n: int, rng: random.Random) -> list[tuple[str, list[str], list[str]]]:
    templates = [
        "Client {name} called from {phone} about the leak.",
        "Please email {email} with the claim form. Postcode {postcode}.",
        "{name}, DOB: {dob}, NI number {ni}, wants to add their partner.",
        "Paid by card {card}; contact {phone} or {email}.",
        "Visit {name} at {postcode} - mobile {phone}.",
        "Date of birth {dob2}. Reach {name} on {phone}.",
    ]
    out = []
    for _ in range(n):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        d, m, y = rng.randint(1, 28), rng.randint(1, 12), rng.randint(1950, 2004)
        vals = {
            "name": name,
            "email": f"{name.split()[0].lower()}.{name.split()[1].lower()}@{rng.choice(['example.com', 'mail.co.uk'])}",
            "phone": rng.choice([f"07700 900{rng.randint(100, 999)}", f"+44 7700 900{rng.randint(100, 999)}",
                                 f"07700900{rng.randint(100, 999)}", f"0113 496 0{rng.randint(100, 999)}",
                                 f"(0113) 496 0{rng.randint(100, 999)}"]),
            "postcode": rng.choice(["LS6 2AB", "BS1 5TT", "M1 3HE", "G12 8QQ", "SW1A 1AA", "EH1 1YZ"]),
            "dob": f"{d:02d}/{m:02d}/{y}",
            "dob2": f"{y}-{m:02d}-{d:02d}",
            "ni": f"{rng.choice(['AB', 'JK', 'TW'])} {rng.randint(10, 99)} {rng.randint(10, 99)} "
                  f"{rng.randint(10, 99)} {rng.choice('ABCD')}",
            "card": rng.choice(["4111 1111 1111 1111", "5500-0000-0000-0004", "4012888888881881"]),
        }
        t = rng.choice(templates)
        keys = re.findall(r"{(\w+)}", t)
        secrets = [vals[k] for k in keys]
        out.append((t.format(**vals), secrets, [name]))
    return out


def pii_eval() -> dict:
    rng = random.Random(7)
    samples = _pii_samples(200, rng)
    total = leaked = 0
    leaked_kinds: dict[str, int] = {}
    for text, secrets, known in samples:
        red = redact_text(text, known)
        for s in secrets:
            total += 1
            if s in red:
                leaked += 1
                kind = "phone" if re.search(r"\d{3}", s) and not re.search(r"[A-Za-z@]", s) else s
                leaked_kinds[kind if len(kind) < 12 else "other"] = leaked_kinds.get(kind, 0) + 1
    clean = [c[0] for c in GOLD_CLAIMS + GOLD_CLAIMS_HOLDOUT]
    false_pos = [t for t in clean if redact_text(t) != t]
    data = get_collection().get(include=["documents"])
    changed = [d for d in data["documents"] if redact_text(d) != d]
    tags = {}
    for d in changed:
        for t in re.findall(r"\[([A-Z_]+)\]", redact_text(d)):
            tags[t] = tags.get(t, 0) + 1
    return {
        "synthetic_records": len(samples),
        "pii_values": total,
        "pii_recall": 1 - leaked / total,
        "leaked_values": leaked,
        "leaked_examples": [t for t, s, _ in samples if any(x in redact_text(t, _) for x in s)][:3],
        "pii_free_texts": len(clean),
        "pii_free_texts_altered": len(false_pos),
        "policy_chunks_scanned": len(data["documents"]),
        "policy_chunks_altered": len(changed),
        "policy_chunk_alteration_rate": len(changed) / len(data["documents"]),
        "tags_in_policy_text": tags,
    }


def guardrail_and_latency_eval() -> dict:
    timings: dict[str, list[float]] = {}

    def timed(name, fn, *a, **kw):
        t = time.perf_counter()
        r = fn(*a, **kw)
        timings.setdefault(name, []).append((time.perf_counter() - t) * 1000)
        return r

    responses = []
    for q, doc, _ in GOLD_RETRIEVAL:
        responses.append(timed("search_policy_wording", server.search_policy_wording, q, doc, 5))
    for desc, pid, _, _ in GOLD_CLAIMS:
        responses.append(timed("check_claim_eligibility", server.check_claim_eligibility, desc, pid))
    for cid in ("C001", "C002", "C003", "C004", "C005", "Sarah Thompson", "POL-1004"):
        responses.append(timed("get_client_policies", server.get_client_policies, cid))
    for a, b in (("POL-1001", "esure"), ("aviva", "AA"), ("POL-1002", "POL-1005")):
        responses.append(timed("compare_coverage", server.compare_coverage, a, b, ["escape of water", "theft"]))
    drafts = []
    for i in range(20):
        drafts.append(timed("draft_client_email", server.draft_client_email, "C001",
                            f"Eval draft {i}", f"Dear Sarah Thompson, call 07700 900123. Covered [RIAS, p.24]. #{i}",
                            "POL-1001"))
    sent_dir = config.OUTBOX_DIR / "sent"
    sent_without_approval = sum((sent_dir / f"{d['draft_id']}.eml").exists() for d in drafts)
    with_disclaimer = sum(r.get("disclaimer") == config.DISCLAIMER for r in responses)
    cov = [r for r in responses if "results" in r or "relevant_clauses" in r]
    with_citations = sum(all(x["citation"] for x in r.get("results", r.get("relevant_clauses", []))) and
                         bool(r.get("results", r.get("relevant_clauses"))) for r in cov)
    pii_in_drafts = sum("07700" in d["body_preview"] or "Thompson" in d["body_preview"] for d in drafts)

    def pct(v, q):
        v = sorted(v)
        return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]

    return {
        "tool_responses": len(responses),
        "responses_with_disclaimer": with_disclaimer,
        "coverage_responses_with_citations": f"{with_citations}/{len(cov)}",
        "drafts_created": len(drafts),
        "drafts_sent_without_human_approval": sent_without_approval,
        "drafts_with_pii_left_in_body": pii_in_drafts,
        "latency_ms": {k: {"p50": round(statistics.median(v), 1), "p95": round(pct(v, 0.95), 1), "n": len(v)}
                       for k, v in timings.items()},
    }


def corpus_stats() -> dict:
    from pypdf import PdfReader

    pages = sum(len(PdfReader(config.PDF_DIR / s["filename"]).pages) for s in config.load_sources())
    return {"insurers": len(config.load_sources()), "pdf_pages": pages, "chunks": get_collection().count()}


def to_markdown(r: dict) -> str:
    c = r["corpus"]
    lines = ["# Evaluation results", "",
             f"Corpus: {c['insurers']} insurer wordings, {c['pdf_pages']} PDF pages, {c['chunks']} indexed chunks.", "",
             f"## Retrieval ({r['retrieval']['n_questions']} hand-labelled broker questions, filtered to one insurer)",
             "", "| Config | Hit@1 | Hit@3 | Hit@5 | MRR |", "|---|---|---|---|---|"]
    for name, m in r["retrieval"]["configs"].items():
        lines.append(f"| {name} | {m['hit@1']:.0%} | {m['hit@3']:.0%} | {m['hit@5']:.0%} | {m['mrr']:.2f} |")
    cl = r["claims"]
    lines += ["", f"## Claim triage ({cl['n_scenarios']} hand-written claim scenarios)", "",
              f"- Peril classification accuracy: {cl['peril_accuracy']:.0%}",
              f"- Correct excess from schedule: {cl['excess_accuracy']:.0%}",
              f"- Exclusion red flags: precision {cl['red_flag_precision']:.0%}, recall {cl['red_flag_recall']:.0%}",
              f"- Escape-of-water claims where a correct clause page was cited: "
              f"{cl['escape_of_water_correct_clause_cited']}"]
    if cl["misclassified"]:
        lines.append("- Misclassified: " + "; ".join(f"\"{m['claim']}\" (expected {m['expected']}, got {m['got']})"
                                                    for m in cl["misclassified"]))
    h = r["claims_holdout"]
    lines += [f"- Held-out set ({h['n_scenarios']} scenarios written before tuning): peril accuracy "
              f"{h['peril_accuracy']:.0%}, excess accuracy {h['excess_accuracy']:.0%}"]
    p = r["pii"]
    lines += ["", f"## PII redaction ({p['synthetic_records']} synthetic notes, {p['pii_values']} PII values)", "",
              f"- Recall: {p['pii_recall']:.1%} ({p['leaked_values']} values leaked)",
              f"- False positives on {p['pii_free_texts']} PII-free claim descriptions: {p['pii_free_texts_altered']}",
              f"- Policy chunks that would be altered if redaction ran on wordings (insurer phone numbers, addresses"
              f" - why redaction is scoped to client data): {p['policy_chunks_altered']}/"
              f"{p['policy_chunks_scanned']} ({p['policy_chunk_alteration_rate']:.1%})"]
    g = r["guardrails"]
    lines += ["", "## Guardrails", "",
              f"- Responses with disclaimer: {g['responses_with_disclaimer']}/{g['tool_responses']}",
              f"- Coverage responses where every passage has a citation: {g['coverage_responses_with_citations']}",
              f"- Drafts sent without human approval: {g['drafts_sent_without_human_approval']}/{g['drafts_created']}",
              f"- Drafts with client PII left in the body: {g['drafts_with_pii_left_in_body']}/{g['drafts_created']}",
              "", "## Latency (in-process, CPU, ms)", "", "| Tool | p50 | p95 | n |", "|---|---|---|---|"]
    for k, v in g["latency_ms"].items():
        lines.append(f"| {k} | {v['p50']} | {v['p95']} | {v['n']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    config.DB_PATH, config.AUDIT_LOG, config.OUTBOX_DIR = tmp / "eval.db", tmp / "audit.jsonl", tmp / "outbox"
    db.init_db(config.DB_PATH)
    search("warm up", None, 1)
    results = {"corpus": corpus_stats(), "retrieval": retrieval_eval(), "claims": claims_eval(),
               "claims_holdout": claims_eval(GOLD_CLAIMS_HOLDOUT), "pii": pii_eval(),
               "guardrails": guardrail_and_latency_eval()}
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (OUT / "results.md").write_text(to_markdown(results))
    print(to_markdown(results))
    print(json.dumps({"misclassified": results["claims"]["misclassified"],
                      "leaked_examples": results["pii"]["leaked_examples"]}, indent=2))


if __name__ == "__main__":
    main()
