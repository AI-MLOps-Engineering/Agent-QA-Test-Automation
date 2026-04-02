# src/api/app/services/vectorstore.py
"""
Vector store client wrapper for ChromaDB (or HTTP vector store).
Provides a small, testable, async-friendly interface used by the Orchestrator.

Design goals:
- Async-friendly API (wraps sync clients with threadpool when needed)
- Support for two modes:
    * local Python client (chromadb) if available
    * HTTP API (Chroma HTTP server) via httpx
- Simple retry/backoff for network calls
- Minimal surface: upsert_documents(namespace, docs), query(namespace, query, top_k)
- Clear logging and graceful degradation when vector store is not configured
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Any

import httpx

from app.core.config import settings

logger = logging.getLogger("agent_qa.vectorstore")

# Try to import chromadb local client; if not available, fall back to HTTP mode
try:
    import chromadb  # type: ignore
    from chromadb.config import Settings as ChromaSettings  # type: ignore
    from chromadb.utils import embedding_functions  # type: ignore

    _HAS_CHROMADB = True
except Exception:
    _HAS_CHROMADB = False


class VectorStoreError(Exception):
    """Generic vector store error."""


class VectorStoreClient:
    """
    Async-friendly vector store client.

    Modes:
    - If settings.VECTORSTORE_URL is set and chromadb HTTP server is used, the client will use HTTP.
    - If chromadb python package is installed and no VECTORSTORE_URL is provided, the client will use the local python client.
    - If neither is available, the client will operate in a no-op mode (logs only).
    """

    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None, namespace_prefix: Optional[str] = None):
        self.base_url = url or (str(settings.VECTORSTORE_URL) if settings.VECTORSTORE_URL else None)
        self.api_key = api_key or settings.VECTORSTORE_API_KEY
        self.namespace_prefix = namespace_prefix or ""
        self._http_client: Optional[httpx.AsyncClient] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._local_client = None
        self._mode = "noop"

        if self.base_url:
            self._mode = "http"
            logger.info("VectorStoreClient configured in HTTP mode (url=%s)", self.base_url)
        elif _HAS_CHROMADB:
            self._mode = "local"
            logger.info("VectorStoreClient configured in local chromadb mode")
            try:
                # Create a local chroma client (in-memory by default)
                chroma_settings = ChromaSettings()
                self._local_client = chromadb.Client(chroma_settings)
            except Exception:
                logger.exception("Failed to initialize local chromadb client; falling back to noop")
                self._local_client = None
                self._mode = "noop"
        else:
            logger.warning("No vector store configured; VectorStoreClient operating in noop mode")

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._http_client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=30.0)
        return self._http_client

    def _get_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=4)
        return self._executor

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        # local client may not need explicit close

    # -------------------------
    # Upsert documents
    # -------------------------
    async def upsert_documents(self, namespace: str, docs: List[Dict[str, Any]]) -> None:
        """
        Upsert a list of documents into the vector store.

        Each doc is expected to be a dict with at least:
            - 'id' (optional): unique id for the doc
            - 'content' or 'text': textual content to embed/index
            - 'metadata' (optional): dict of metadata

        If no id is provided, a synthetic id will be generated.
        """
        ns = f"{self.namespace_prefix}{namespace}"
        if not docs:
            logger.debug("upsert_documents called with empty docs for namespace=%s", ns)
            return

        if self._mode == "noop":
            logger.info("VectorStore noop upsert: namespace=%s docs=%d", ns, len(docs))
            return

        # Normalize docs
        normalized = []
        for i, d in enumerate(docs):
            doc_id = d.get("id") or d.get("path") or f"doc-{i}"
            content = d.get("content") or d.get("text") or ""
            metadata = d.get("metadata") or {"path": d.get("path")} if d.get("path") else {}
            normalized.append({"id": str(doc_id), "content": content, "metadata": metadata})

        if self._mode == "http":
            await self._upsert_http(ns, normalized)
        elif self._mode == "local":
            await self._upsert_local(ns, normalized)

    async def _upsert_http(self, namespace: str, docs: List[Dict[str, Any]]) -> None:
        """
        Upsert documents using a hypothetical Chroma HTTP API.
        This implementation is conservative and tolerant to different server shapes.
        """
        client = await self._get_http_client()
        payload = {"namespace": namespace, "documents": [{"id": d["id"], "text": d["content"], "metadata": d["metadata"]} for d in docs]}
        # Simple retry/backoff
        last_exc = None
        for attempt in range(1, 4):
            try:
                resp = await client.post("/upsert", json=payload)
                resp.raise_for_status()
                logger.debug("VectorStore HTTP upsert success namespace=%s docs=%d", namespace, len(docs))
                return
            except Exception as exc:
                last_exc = exc
                wait = 0.5 * (2 ** (attempt - 1))
                logger.warning("VectorStore HTTP upsert attempt %d failed: %s; retrying in %.2fs", attempt, exc, wait)
                await asyncio.sleep(wait)
        logger.exception("VectorStore HTTP upsert failed after retries: %s", last_exc)
        raise VectorStoreError("HTTP upsert failed") from last_exc

    async def _upsert_local(self, namespace: str, docs: List[Dict[str, Any]]) -> None:
        """
        Upsert documents using the local chromadb python client.
        chromadb client is synchronous; run in threadpool.
        """
        if not self._local_client:
            logger.error("Local chromadb client not initialized")
            raise VectorStoreError("Local chromadb client not available")

        def _sync_upsert():
            try:
                # Create or get collection
                coll = None
                try:
                    coll = self._local_client.get_collection(name=namespace)
                except Exception:
                    coll = self._local_client.create_collection(name=namespace)
                ids = [d["id"] for d in docs]
                texts = [d["content"] for d in docs]
                metadatas = [d["metadata"] for d in docs]
                # If embedding function is available, chroma will compute embeddings; otherwise store texts
                coll.add(ids=ids, documents=texts, metadatas=metadatas)
                logger.debug("Local chromadb upsert namespace=%s docs=%d", namespace, len(docs))
            except Exception:
                logger.exception("Local chromadb upsert failed")
                raise

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._get_executor(), _sync_upsert)

    # -------------------------
    # Query
    # -------------------------
    async def query(self, namespace: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Query the vector store for relevant documents.

        Returns a list of dicts: {"id": str, "score": float, "content": str, "metadata": dict}
        """
        ns = f"{self.namespace_prefix}{namespace}"
        if self._mode == "noop":
            logger.debug("VectorStore noop query: namespace=%s query=%s", ns, query)
            return []

        if self._mode == "http":
            return await self._query_http(ns, query, top_k)
        elif self._mode == "local":
            return await self._query_local(ns, query, top_k)
        return []

    async def _query_http(self, namespace: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        client = await self._get_http_client()
        payload = {"namespace": namespace, "query": query, "top_k": top_k}
        last_exc = None
        for attempt in range(1, 4):
            try:
                resp = await client.post("/query", json=payload)
                resp.raise_for_status()
                data = resp.json()
                # Expecting a shape like {"results":[{"id":"...","score":0.9,"text":"...","metadata":{}}]}
                results = []
                if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
                    for item in data["results"]:
                        results.append(
                            {
                                "id": item.get("id"),
                                "score": float(item.get("score", 0.0)),
                                "content": item.get("text") or item.get("content") or "",
                                "metadata": item.get("metadata") or {},
                            }
                        )
                else:
                    # Fallback: try to interpret raw list
                    if isinstance(data, list):
                        for item in data[:top_k]:
                            results.append({"id": item.get("id"), "score": float(item.get("score", 0.0)), "content": item.get("text", ""), "metadata": item.get("metadata", {})})
                logger.debug("VectorStore HTTP query namespace=%s query=%s results=%d", namespace, query, len(results))
                return results
            except Exception as exc:
                last_exc = exc
                wait = 0.5 * (2 ** (attempt - 1))
                logger.warning("VectorStore HTTP query attempt %d failed: %s; retrying in %.2fs", attempt, exc, wait)
                await asyncio.sleep(wait)
        logger.exception("VectorStore HTTP query failed after retries: %s", last_exc)
        return []

    async def _query_local(self, namespace: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self._local_client:
            logger.error("Local chromadb client not initialized")
            return []

        def _sync_query():
            try:
                coll = self._local_client.get_collection(name=namespace)
                # chroma local client supports query with n_results
                results = coll.query(query_texts=[query], n_results=top_k, include=["metadatas", "documents", "ids"])
                # results is a dict with lists per query
                out = []
                if results:
                    docs = results.get("documents", [[]])[0]
                    ids = results.get("ids", [[]])[0]
                    metadatas = results.get("metadatas", [[]])[0]
                    # chroma local client may not return scores; set None
                    for i, doc in enumerate(docs):
                        out.append({"id": ids[i] if i < len(ids) else None, "score": None, "content": doc, "metadata": metadatas[i] if i < len(metadatas) else {}})
                return out
            except Exception:
                logger.exception("Local chromadb query failed")
                return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._get_executor(), _sync_query)

    # -------------------------
    # Utility helpers
    # -------------------------
    async def delete_namespace(self, namespace: str) -> None:
        """
        Delete a namespace/collection from the vector store.
        """
        ns = f"{self.namespace_prefix}{namespace}"
        if self._mode == "noop":
            logger.info("VectorStore noop delete_namespace: %s", ns)
            return

        if self._mode == "http":
            client = await self._get_http_client()
            try:
                resp = await client.post("/delete_namespace", json={"namespace": ns})
                resp.raise_for_status()
                logger.info("VectorStore HTTP deleted namespace=%s", ns)
            except Exception:
                logger.exception("VectorStore HTTP delete_namespace failed for %s", ns)
                raise VectorStoreError("HTTP delete_namespace failed")
        elif self._mode == "local":
            def _sync_delete():
                try:
                    self._local_client.delete_collection(name=ns)
                    logger.info("Local chromadb deleted collection=%s", ns)
                except Exception:
                    logger.exception("Local chromadb delete collection failed for %s", ns)
                    raise

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._get_executor(), _sync_delete)
