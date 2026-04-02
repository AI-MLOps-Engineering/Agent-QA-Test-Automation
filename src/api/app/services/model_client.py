# src/api/app/services/model_client.py
"""
Model client service for interacting with an external model server (Ollama / TGI).
Provides a small, async-friendly wrapper around HTTP calls to generate text from code-oriented models.

Design goals:
- Async API using httpx.AsyncClient
- Simple retry logic with exponential backoff (no external dependency)
- Clear error handling and logging
- Pluggable model name and server URL via settings
- Minimal surface: generate(prompt), embed(text) (embed optional / best-effort)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Dict, Any

import httpx

from app.core.config import settings

logger = logging.getLogger("agent_qa.model_client")


class ModelClientError(Exception):
    """Generic model client error."""


class ModelClient:
    """
    Async client to call a model server.

    Example usage:
        client = ModelClient()
        await client.generate("Write a pytest for function foo", max_tokens=512)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout: int = 60,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        self.base_url = base_url or (str(settings.MODEL_SERVER_URL) if settings.MODEL_SERVER_URL else None)
        self.default_model = default_model or settings.MODEL_DEFAULT_NAME
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._client: Optional[httpx.AsyncClient] = None

        if not self.base_url:
            logger.warning("ModelClient initialized without base_url; calls will fail until configured.")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(self.timeout))
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request_with_retries(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        Internal helper to perform HTTP requests with simple retry/backoff.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                client = await self._get_client()
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as exc:
                last_exc = exc
                wait = self.backoff_factor * (2 ** (attempt - 1))
                logger.warning("Model request failed (attempt %d/%d): %s. Retrying in %.2fs", attempt, self.max_retries, exc, wait)
                await asyncio.sleep(wait)
        logger.error("Model request failed after %d attempts: %s", self.max_retries, last_exc)
        raise ModelClientError(f"Request to model server failed: {last_exc}")

    async def generate(self, prompt: str, model: Optional[str] = None, max_tokens: int = 1024, temperature: float = 0.0) -> str:
        """
        Generate text from the model server.

        This implementation supports two common server APIs:
        - Ollama-like: POST /api/generate with JSON {model, prompt, ...}
        - TGI-like: POST /generate?model=<model> with JSON {inputs: prompt, parameters: {...}}

        The client attempts Ollama-style first, then falls back to a generic TGI-style endpoint.
        """
        if not self.base_url:
            raise ModelClientError("Model server base_url not configured")

        model_name = model or self.default_model
        # Try Ollama-style endpoint
        try:
            payload = {"model": model_name, "prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
            resp = await self._request_with_retries("POST", "/api/generate", json=payload)
            data = resp.json()
            # Ollama returns {"model": "...", "prompt": "...", "results": [{"content": "..."}], ...}
            if isinstance(data, dict):
                # try common shapes
                if "results" in data and isinstance(data["results"], list) and len(data["results"]) > 0:
                    content = data["results"][0].get("content") or data["results"][0].get("text")
                    if content:
                        return content
                # some Ollama variants return 'output' or 'text'
                if "output" in data and isinstance(data["output"], str):
                    return data["output"]
                if "text" in data and isinstance(data["text"], str):
                    return data["text"]
        except Exception as e:
            logger.debug("Ollama-style generate failed or not supported: %s", e)

        # Fallback: TGI-style endpoint
        try:
            payload = {"inputs": prompt, "parameters": {"max_new_tokens": max_tokens, "temperature": temperature}}
            resp = await self._request_with_retries("POST", f"/generate?model={model_name}", json=payload)
            data = resp.json()
            # TGI often returns {"generated_text": "..."} or {"results":[{"generated_text":"..."}]}
            if isinstance(data, dict):
                if "generated_text" in data:
                    return data["generated_text"]
                if "results" in data and isinstance(data["results"], list) and len(data["results"]) > 0:
                    gen = data["results"][0].get("generated_text") or data["results"][0].get("text")
                    if gen:
                        return gen
            # As a last resort, return raw text
            return resp.text
        except Exception as e:
            logger.exception("Model generation failed (both Ollama and TGI attempts): %s", e)
            raise ModelClientError("Model generation failed") from e

    async def embed(self, text: str) -> Optional[list[float]]:
        """
        Optional embedding method. Not all model servers expose embeddings.
        Attempts common endpoints and returns None if not available.
        """
        if not self.base_url:
            raise ModelClientError("Model server base_url not configured")

        # Try Ollama-style embeddings endpoint
        try:
            payload = {"model": self.default_model, "input": text}
            resp = await self._request_with_retries("POST", "/api/embeddings", json=payload)
            data = resp.json()
            # Ollama-like: {"data":[{"embedding":[...]}]}
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                emb = data["data"][0].get("embedding")
                if isinstance(emb, list):
                    return emb
        except Exception:
            logger.debug("Embeddings endpoint (Ollama-style) not available or failed")

        # Try TGI-style or HF inference endpoint
        try:
            payload = {"inputs": text}
            resp = await self._request_with_retries("POST", f"/embeddings?model={self.default_model}", json=payload)
            data = resp.json()
            # HF inference: {"data":[...]} or {"embedding":[...]}
            if isinstance(data, dict):
                if "embedding" in data and isinstance(data["embedding"], list):
                    return data["embedding"]
                if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                    maybe = data["data"][0].get("embedding") or data["data"][0].get("vector")
                    if isinstance(maybe, list):
                        return maybe
        except Exception:
            logger.debug("Embeddings endpoint (TGI/HF-style) not available or failed")

        # Not supported
        logger.info("Model server does not support embeddings or endpoint unreachable")
        return None

    async def health(self) -> bool:
        """
        Lightweight health check for the model server.
        """
        if not self.base_url:
            return False
        try:
            # Try a small generate call with tiny timeout
            client = await self._get_client()
            resp = await client.get("/health")
            if resp.status_code == 200:
                return True
        except Exception:
            # Try a minimal generate
            try:
                await self.generate(prompt="health check", max_tokens=1)
                return True
            except Exception:
                return False
        return False
