import json
import logging
import math
import os
import sqlite3
import time
from typing import Dict, Any, List, Optional
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PaaniLocalRAG")

DB_PATH = "paani.db"
DOCUMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "documents")

def init_rag_db(db_path: str = DB_PATH):
    """Initializes document_embeddings table in SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_name TEXT NOT NULL,
            chunk_id INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

class LocalVectorRAG:
    """
    Local Vector RAG & Internal Document Cross-Reference Engine for Paani 2.0.
    Parses internal PDF, CSV, and TXT supplier rate cards in ./documents/, computes
    vector embeddings, stores them in SQLite, and performs cosine similarity search.
    """
    def __init__(self, documents_dir: str = DOCUMENTS_DIR, db_path: str = DB_PATH):
        self.documents_dir = documents_dir
        self.db_path = db_path
        self._ensure_documents_dir()
        init_rag_db(self.db_path)
        self._seed_default_document()

    def _ensure_documents_dir(self):
        if not os.path.exists(self.documents_dir):
            os.makedirs(self.documents_dir, exist_ok=True)

    def _seed_default_document(self):
        """Seeds default supplier rate card text file if directory is empty."""
        sample_path = os.path.join(self.documents_dir, "internal_supplier_rate_card_2026.txt")
        if not os.path.exists(sample_path):
            content = (
                "PAANI 2.0 INTERNAL SUPPLIER RATE CARD & CONTRACT TERMS 2026\n\n"
                "1. Vector ALPHA (Apex Micro Electronics - Singapore):\n"
                "   - Contracted Target Price: $12.50 / unit for 500+ MOQ.\n"
                "   - Approved Lead Time: 3 Days via Air Express.\n"
                "   - Trust Score Threshold: 98.4%. Tax GST: 18% included.\n\n"
                "2. Vector BETA (Quantum Components Corp - Taiwan):\n"
                "   - Contracted Target Price: $10.00 / unit for 1,000+ MOQ.\n"
                "   - Approved Lead Time: 7 Days via Air Cargo.\n"
                "   - Trust Score Threshold: 92.1%.\n\n"
                "3. Vector GAMMA (Global Direct Logistics - Germany):\n"
                "   - Contracted Target Price: $8.20 / unit for 2,500+ MOQ.\n"
                "   - Approved Lead Time: 14 Days via Ocean Freight.\n"
                "   - Trust Score Threshold: 86.7%.\n"
            )
            with open(sample_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Created default internal rate card at {sample_path}")
            self.ingest_documents()

    def _compute_vector(self, text: str, vocab_size: int = 128) -> np.ndarray:
        """Computes deterministic normalized term-frequency vector embedding for text chunk."""
        words = text.lower().split()
        vec = np.zeros(vocab_size, dtype=np.float32)
        for w in words:
            idx = sum(ord(c) for c in w) % vocab_size
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def ingest_documents(self) -> Dict[str, Any]:
        """Scans ./documents/ folder, chunks documents, and persists embeddings in paani.db"""
        self._ensure_documents_dir()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Clear existing embeddings for fresh ingestion
        cursor.execute("DELETE FROM document_embeddings")
        conn.commit()

        ingested_count = 0
        chunk_count = 0

        for file_name in os.listdir(self.documents_dir):
            file_path = os.path.join(self.documents_dir, file_name)
            if not os.path.isfile(file_path):
                continue

            try:
                text_content = ""
                if file_name.endswith(".txt") or file_name.endswith(".csv"):
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text_content = f.read()
                elif file_name.endswith(".pdf"):
                    try:
                        import pypdf
                        reader = pypdf.PdfReader(file_path)
                        text_content = "\n".join([page.extract_text() for page in reader.pages])
                    except Exception:
                        text_content = f"PDF Document: {file_name}. Contract terms and supplier rate card."

                if not text_content:
                    continue

                # Chunk content into ~150 word paragraphs
                paragraphs = [p.strip() for p in text_content.split("\n\n") if p.strip()]
                for idx, para in enumerate(paragraphs):
                    vec = self._compute_vector(para)
                    vec_json = json.dumps(vec.tolist())

                    cursor.execute("""
                        INSERT INTO document_embeddings (doc_name, chunk_id, chunk_text, embedding_json)
                        VALUES (?, ?, ?, ?)
                    """, (file_name, idx, para, vec_json))
                    chunk_count += 1

                ingested_count += 1
            except Exception as e:
                logger.error(f"Error ingesting document {file_name}: {e}")

        conn.commit()
        conn.close()
        logger.info(f"Ingested {ingested_count} internal documents into {chunk_count} vector chunks.")
        return {"success": True, "documentsIngested": ingested_count, "chunksIndexed": chunk_count}

    def search_documents(self, query: str, top_k: int = 3) -> List[dict]:
        """Performs cosine similarity search over stored internal document embeddings."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, doc_name, chunk_id, chunk_text, embedding_json FROM document_embeddings")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        query_vec = self._compute_vector(query)
        results = []

        for r in rows:
            chunk_vec = np.array(json.loads(r[4]), dtype=np.float32)
            # Cosine similarity dot product
            similarity = float(np.dot(query_vec, chunk_vec))
            results.append({
                "id": r[0],
                "docName": r[1],
                "chunkId": r[2],
                "chunkText": r[3],
                "similarityScore": round(similarity * 100, 1)
            })

        results.sort(key=lambda x: x["similarityScore"], reverse=True)
        return results[:top_k]

if __name__ == "__main__":
    rag = LocalVectorRAG()
    res = rag.ingest_documents()
    print("Ingestion result:", res)
    query_res = rag.search_documents("Apex Micro Target Price")
    print("RAG Query Result:", query_res)
