"""Hybrid retrieval over the indexed policy wordings: dense similarity from ChromaDB fused
(reciprocal rank fusion) with BM25 keyword ranking, so exact insurance terms such as
"escape of water" are not missed by the embedding model."""

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from . import config

_STOP = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "is", "are", "be", "by", "with", "what",
    "which", "does", "do", "my", "our", "your", "under", "from", "this", "that", "it", "as", "at", "if", "any",
    "will", "can", "how", "when", "who", "client", "clients", "policy", "cover", "covered", "home",
}
# Insurers use different words for the same peril; expand broker phrasing to policy phrasing.
SYNONYMS = {
    "burst pipe": "escape of water water leakage leaking pipes",
    "burst": "escape of water leaking",
    "leak": "escape of water leakage",
    "excess": "excess you pay the first",
    "break-in": "theft attempted theft",
    "burglary": "theft attempted theft",
    "stolen": "theft",
    "cracks": "subsidence heave",
}
_client = None
_bm25_cache: dict = {}


def _chroma():
    global _client
    if _client is None:
        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
    return _client


def get_collection():
    return _chroma().get_or_create_collection(
        config.COLLECTION, embedding_function=DefaultEmbeddingFunction(), metadata={"hnsw:space": "cosine"}
    )


def reset_collection():
    if config.COLLECTION in [c.name if hasattr(c, "name") else c for c in _chroma().list_collections()]:
        _chroma().delete_collection(config.COLLECTION)
    return get_collection()


@dataclass
class Passage:
    citation: str
    insurer: str
    product: str
    doc_id: str
    page: int
    section: str
    text: str
    relevance: float
    source_link: str

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_doc_id(name: str | None) -> str | None:
    """Accept a doc_id ('rias_home') or an insurer name ('RIAS', 'esure')."""
    if not name:
        return None
    key = name.strip().lower()
    sources = config.load_sources()
    for s in sources:
        if key in (s["doc_id"].lower(), s["insurer"].lower()):
            return s["doc_id"]
    for s in sources:
        if key in s["insurer"].lower() or key in s["doc_id"].lower():
            return s["doc_id"]
    raise ValueError(f"Unknown policy document '{name}'. Known: {', '.join(s['doc_id'] for s in sources)}")


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in _STOP]


def expand_query(query: str) -> str:
    q = query.lower()
    extra = [v for k, v in SYNONYMS.items() if k in q]
    return " ".join([query, *extra])


def _bm25_index(collection):
    count = collection.count()
    if _bm25_cache.get("count") != count:
        data = collection.get(include=["documents", "metadatas"])
        docs = [Counter(_tokens(d)) for d in data["documents"]]
        df = Counter(t for d in docs for t in d)
        n = len(docs)
        _bm25_cache.update(
            count=count, ids=data["ids"], texts=data["documents"], metas=data["metadatas"], docs=docs,
            lens=[sum(d.values()) for d in docs], avg=sum(sum(d.values()) for d in docs) / max(n, 1),
            idf={t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()},
        )
    return _bm25_cache


def _bm25_rank(collection, query: str, doc_id: str | None, n: int, k1: float = 1.5, b: float = 0.75) -> list[str]:
    idx = _bm25_index(collection)
    q = set(_tokens(query))
    scores = []
    for i, (tf, length, meta) in enumerate(zip(idx["docs"], idx["lens"], idx["metas"], strict=True)):
        if doc_id and meta["doc_id"] != doc_id:
            continue
        s = sum(idx["idf"][t] * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * length / idx["avg"]))
                for t in q if t in tf)
        if s > 0:
            scores.append((s, idx["ids"][i]))
    scores.sort(reverse=True)
    return [cid for _, cid in scores[:n]]


def search(query: str, doc_id: str | None = None, top_k: int = 5, mode: str = "hybrid",
           expand: bool = True) -> list[Passage]:
    """mode: "hybrid" (default), "dense" or "bm25" - the last two exist for evaluation/ablation."""
    collection = get_collection()
    if collection.count() == 0:
        raise RuntimeError("The policy index is empty - run `policy-assistant setup` first.")
    expanded = expand_query(query) if expand else query
    pool = 25
    res = collection.query(
        query_texts=[expanded],
        n_results=min(pool, collection.count()),
        where={"doc_id": doc_id} if doc_id else None,
    )
    dense_ids = res["ids"][0]
    sparse_ids = _bm25_rank(collection, expanded, doc_id, pool)
    rankings = {"hybrid": (dense_ids, sparse_ids), "dense": (dense_ids,), "bm25": (sparse_ids,)}[mode]
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            fused[cid] = fused.get(cid, 0.0) + 1 / (60 + rank)
    idx = _bm25_cache
    lookup = {cid: i for i, cid in enumerate(idx["ids"])}
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
    best = ranked[0][1] if ranked else 1
    out = []
    for cid, score in ranked:
        text, meta = idx["texts"][lookup[cid]], idx["metas"][lookup[cid]]
        score = score / best
        out.append(Passage(
            citation=f"[{meta['insurer']} {meta['product']}, p.{meta['page']}]",
            insurer=meta["insurer"],
            product=meta["product"],
            doc_id=meta["doc_id"],
            page=meta["page"],
            section=meta.get("section", ""),
            text=text,
            relevance=round(score, 3),
            source_link=f"{meta['source_url']}#page={meta['page']}",
        ))
    return out
