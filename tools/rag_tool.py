#!/usr/bin/env python3
"""
Local RAG (Retrieval-Augmented Generation) Tool

Searches a local ChromaDB vector database built from Dave's business documents.
Allows Atlas to answer questions grounded in real data — Wickes Solar reports,
Residio research, property market notes — rather than general knowledge.

The database lives at ~/Developer/atlas-rag/chroma_db/.
Add documents to ~/Developer/atlas-rag/docs/ and run ingest.py to index them.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

RAG_ROOT = Path.home() / "Developer" / "atlas-rag"
DB_PATH = RAG_ROOT / "chroma_db"
DOCS_PATH = RAG_ROOT / "docs"
COLLECTION_NAME = "atlas_local_docs"


def check_rag_requirements() -> bool:
    """Available if ChromaDB is installed and the database has been built."""
    try:
        import chromadb  # noqa: F401
        return DB_PATH.exists()
    except ImportError:
        return False


def rag_search(query: str, n_results: int = 5) -> str:
    """
    Search the local document knowledge base and return relevant excerpts.

    Args:
        query:     Natural language question or search terms.
        n_results: Number of document chunks to return (default 5, max 10).

    Returns:
        JSON string with matched document excerpts and their sources.
    """
    if not query or not query.strip():
        return json.dumps({"success": False, "error": "Query is required"})

    if not DB_PATH.exists():
        return json.dumps({
            "success": False,
            "error": (
                f"RAG database not found at {DB_PATH}. "
                f"Add documents to {DOCS_PATH} and run: "
                f"python {RAG_ROOT}/ingest.py"
            ),
        })

    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        return json.dumps({
            "success": False,
            "error": f"Missing dependency: {e}. Run: pip install chromadb sentence-transformers",
        })

    try:
        n_results = max(1, min(int(n_results), 10))

        client = chromadb.PersistentClient(path=str(DB_PATH))
        try:
            collection = client.get_collection(COLLECTION_NAME)
        except Exception:
            return json.dumps({
                "success": False,
                "error": (
                    f"Collection '{COLLECTION_NAME}' not found. "
                    f"Run: python {RAG_ROOT}/ingest.py"
                ),
            })

        total_docs = collection.count()
        if total_docs == 0:
            return json.dumps({
                "success": False,
                "error": "Database is empty. Add documents and run ingest.py.",
            })

        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode(query).tolist()

        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(n_results, total_docs),
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            source_path = Path(meta.get("source", "unknown"))
            hits.append({
                "source": source_path.name,
                "relevance_score": round(1 - dist, 4),  # invert distance → score
                "excerpt": doc[:1500].strip(),
            })

        if not hits:
            return json.dumps({
                "success": True,
                "query": query,
                "results": [],
                "message": "No relevant documents found for this query.",
            })

        return json.dumps({
            "success": True,
            "query": query,
            "total_documents_indexed": total_docs,
            "results": hits,
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("RAG search failed: %s", e, exc_info=True)
        return json.dumps({"success": False, "error": f"RAG search failed: {e}"})


def rag_ingest(document_text: str, document_name: str) -> str:
    """
    Add a new document to the RAG knowledge base directly (no file needed).

    Useful for indexing text sent via WhatsApp — e.g. pasted reports, notes,
    or content extracted from a photo via vision_analyze.

    Args:
        document_text: The full text content to index.
        document_name: A short descriptive name (e.g. 'q1-sales-report.txt').

    Returns:
        JSON string confirming success or describing the error.
    """
    if not document_text or not document_text.strip():
        return json.dumps({"success": False, "error": "document_text is required"})
    if not document_name or not document_name.strip():
        return json.dumps({"success": False, "error": "document_name is required"})

    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        return json.dumps({"success": False, "error": f"Missing dependency: {e}"})

    try:
        DB_PATH.mkdir(parents=True, exist_ok=True)

        client = chromadb.PersistentClient(path=str(DB_PATH))
        collection = client.get_or_create_collection(COLLECTION_NAME)

        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode(document_text.strip()).tolist()

        safe_name = document_name.strip().replace("/", "_").replace("\\", "_")
        doc_id = safe_name

        collection.upsert(
            ids=[doc_id],
            documents=[document_text.strip()],
            embeddings=[embedding],
            metadatas=[{"source": str(DOCS_PATH / safe_name)}],
        )

        return json.dumps({
            "success": True,
            "document_name": safe_name,
            "total_documents_indexed": collection.count(),
            "message": f"'{safe_name}' indexed successfully. "
                       f"Atlas can now answer questions about it.",
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("RAG ingest failed: %s", e, exc_info=True)
        return json.dumps({"success": False, "error": f"RAG ingest failed: {e}"})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
from tools.registry import registry

RAG_SEARCH_SCHEMA = {
    "name": "rag_search",
    "description": (
        "Search Dave's private local knowledge base of business documents. "
        "ALWAYS call this FIRST — before web_search or general knowledge — for ANY question about: "
        "Wickes Solar board members, chairman, CEO, executives, team, strategy, performance, partners; "
        "Residio product, research, target users, or market; "
        "Spain property, Costa del Sol, or La Zagaleta; "
        "named individuals in David's business network; "
        "or any specific figures, decisions, or context David may have shared. "
        "Examples that MUST use this tool first: 'who is the Wickes Solar chairman', "
        "'who is on the board', 'what is the exit strategy', 'who is David Wood', "
        "'what is Residio', 'who are the key people'. "
        "This database contains David's private documents — it is always more accurate "
        "than web search for his specific business context. "
        "Only use web_search after this returns no useful results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language question or search terms, e.g. 'best performing Wickes solar products last quarter'",
            },
            "n_results": {
                "type": "integer",
                "description": "Number of document excerpts to return (1–10, default 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

RAG_INGEST_SCHEMA = {
    "name": "rag_ingest",
    "description": (
        "Add a new document to the local knowledge base so Atlas can search it. "
        "Use after extracting text from an image or document Dave has shared. "
        "Also useful for indexing notes, reports, or any text Dave wants Atlas to remember long-term."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "document_text": {
                "type": "string",
                "description": "The full text content to index.",
            },
            "document_name": {
                "type": "string",
                "description": "Short descriptive filename, e.g. 'wickes-q1-2026-report.txt'",
            },
        },
        "required": ["document_text", "document_name"],
    },
}

registry.register(
    name="rag_search",
    toolset="rag",
    schema=RAG_SEARCH_SCHEMA,
    handler=lambda args, **kw: rag_search(
        query=args.get("query", ""),
        n_results=args.get("n_results", 5),
    ),
    check_fn=check_rag_requirements,
    emoji="📚",
)

registry.register(
    name="rag_ingest",
    toolset="rag",
    schema=RAG_INGEST_SCHEMA,
    handler=lambda args, **kw: rag_ingest(
        document_text=args.get("document_text", ""),
        document_name=args.get("document_name", ""),
    ),
    check_fn=check_rag_requirements,
    emoji="📥",
)
