"""Download public policy wordings and index them in ChromaDB, one chunk per page region,
so every search hit can be cited back to an insurer, document and page."""

import re
import urllib.request

from pypdf import PdfReader

from . import config
from .retrieval import get_collection, reset_collection

_NOISE = re.compile(r"\.indd|^\s*\d{1,3}\s*$|^\s*\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}")
_SECTION = re.compile(r"^\s*(Section\s+\d{1,2}\s*[-–:]\s*[A-Z].{2,70})$")


def fetch_policies(force: bool = False) -> list[str]:
    config.PDF_DIR.mkdir(parents=True, exist_ok=True)
    done = []
    for src in config.load_sources():
        dest = config.PDF_DIR / src["filename"]
        if dest.exists() and not force:
            done.append(f"{src['doc_id']}: already present")
            continue
        req = urllib.request.Request(src["url"], headers={"User-Agent": "Mozilla/5.0 (policy-assistant-mcp)"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            raise RuntimeError(f"{src['url']} did not return a PDF")
        dest.write_bytes(data)
        done.append(f"{src['doc_id']}: downloaded {len(data) // 1024} KB")
    return done


def clean_page(text: str) -> list[str]:
    lines = []
    for line in text.replace("\ufb01", "fi").replace("\ufb02", "fl").splitlines():
        if _NOISE.search(line):
            continue
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def chunk_text(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + size // 2, end)
            end = cut if cut != -1 else end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        nxt = text.find(" ", start)
        start = nxt + 1 if nxt != -1 and nxt < end else start
    return [c for c in chunks if c]


def ingest(reset: bool = True) -> dict[str, int]:
    collection = reset_collection() if reset else get_collection()
    counts: dict[str, int] = {}
    for src in config.load_sources():
        pdf = config.PDF_DIR / src["filename"]
        if not pdf.exists():
            raise FileNotFoundError(f"{pdf} missing - run `policy-assistant fetch` first")
        reader = PdfReader(pdf)
        section = ""
        ids, docs, metas = [], [], []
        for page_no, page in enumerate(reader.pages, start=1):
            lines = clean_page(page.extract_text() or "")
            for line in lines:
                m = _SECTION.match(line)
                if m:
                    section = m.group(1)[:80]
                    break
            for i, chunk in enumerate(chunk_text(" ".join(lines))):
                if len(chunk) < 80:
                    continue
                ids.append(f"{src['doc_id']}-p{page_no}-c{i}")
                docs.append(chunk)
                metas.append({
                    "doc_id": src["doc_id"],
                    "insurer": src["insurer"],
                    "product": src["product"],
                    "page": page_no,
                    "section": section,
                    "source_url": src["url"],
                })
        for start in range(0, len(ids), 200):
            collection.upsert(ids=ids[start:start + 200], documents=docs[start:start + 200],
                              metadatas=metas[start:start + 200])
        counts[src["doc_id"]] = len(ids)
    return counts
