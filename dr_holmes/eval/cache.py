"""SQLite-backed deterministic LLM response cache.

Cache key = sha256(canonical_json({provider, model, prompt_version,
                                   messages, tools, temperature, max_tokens}))

Critical property: every agent's LLM call goes through this. Re-running
metrics on the same eval run hits the cache and pays $0.
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from contextlib import contextmanager

from pydantic import BaseModel


_DEFAULT_DB = "./data/llm_cache.db"


class CachedResponse(BaseModel):
    cache_key: str
    provider: str
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    response: dict
    metadata: dict = {}
    cache_hit: bool = False


def canonical_json(obj: Any) -> str:
    """Stable JSON for hashing — sort keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def derive_cache_key(
    *,
    provider: str,
    model: str,
    prompt_version: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 800,
    response_format: dict | None = None,
) -> str:
    payload = canonical_json({
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "messages": messages,
        "tools": tools or [],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": response_format,
    })
    return hashlib.sha256(payload.encode()).hexdigest()


class LLMResponseCache:
    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_schema()
        self._stats = {"hits": 0, "misses": 0}

    def _init_schema(self):
        with self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key       TEXT PRIMARY KEY,
                provider        TEXT NOT NULL,
                model           TEXT NOT NULL,
                prompt_version  TEXT NOT NULL,
                input_tokens    INTEGER DEFAULT 0,
                output_tokens   INTEGER DEFAULT 0,
                cost_usd        REAL DEFAULT 0.0,
                response_json   TEXT NOT NULL,
                metadata_json   TEXT,
                cache_hit_count INTEGER DEFAULT 0,
                created_at      TEXT NOT NULL,
                last_used_at    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_cache_provider_model
                ON llm_cache (provider, model);
            CREATE INDEX IF NOT EXISTS ix_cache_prompt_version
                ON llm_cache (prompt_version);
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    # ── Lookup ──────────────────────────────────────────────────────

    def get(self, cache_key: str) -> Optional[CachedResponse]:
        with self._conn() as c:
            row = c.execute(
                "SELECT cache_key, provider, model, prompt_version, "
                "       input_tokens, output_tokens, cost_usd, "
                "       response_json, metadata_json "
                "FROM llm_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        # bump usage stats
        with self._conn() as c:
            c.execute(
                "UPDATE llm_cache SET cache_hit_count = cache_hit_count + 1, "
                "    last_used_at = ? WHERE cache_key = ?",
                (datetime.utcnow().isoformat(), cache_key),
            )
        return CachedResponse(
            cache_key=row[0],
            provider=row[1],
            model=row[2],
            prompt_version=row[3],
            input_tokens=row[4],
            output_tokens=row[5],
            cost_usd=row[6],
            response=json.loads(row[7]),
            metadata=json.loads(row[8]) if row[8] else {},
            cache_hit=True,
        )

    def put(self, *, cache_key: str, provider: str, model: str,
            prompt_version: str, input_tokens: int, output_tokens: int,
            cost_usd: float, response: dict, metadata: dict | None = None):
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO llm_cache "
                "(cache_key, provider, model, prompt_version, "
                " input_tokens, output_tokens, cost_usd, "
                " response_json, metadata_json, cache_hit_count, "
                " created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (cache_key, provider, model, prompt_version,
                 input_tokens, output_tokens, cost_usd,
                 json.dumps(response), json.dumps(metadata or {}),
                 now, now),
            )

    # ── High-level: get-or-call ─────────────────────────────────────

    def get_or_call(
        self,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        response_format: dict | None = None,
        call_fn: Callable[[], tuple[dict, int, int, float]],
        metadata: dict | None = None,
    ) -> CachedResponse:
        """If cached, return cached. Else call_fn() → (response_dict, in_tok, out_tok, cost), cache, return.

        call_fn must be deterministic (temperature=0 enforced upstream)."""
        key = derive_cache_key(
            provider=provider, model=model, prompt_version=prompt_version,
            messages=messages, tools=tools, temperature=temperature,
            max_tokens=max_tokens, response_format=response_format,
        )

        cached = self.get(key)
        if cached is not None:
            self._stats["hits"] += 1
            return cached

        self._stats["misses"] += 1
        response, in_tok, out_tok, cost = call_fn()
        self.put(
            cache_key=key, provider=provider, model=model,
            prompt_version=prompt_version,
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
            response=response, metadata=metadata,
        )
        return CachedResponse(
            cache_key=key, provider=provider, model=model,
            prompt_version=prompt_version, input_tokens=in_tok,
            output_tokens=out_tok, cost_usd=cost,
            response=response, metadata=metadata or {}, cache_hit=False,
        )

    # ── Stats ───────────────────────────────────────────────────────

    def stats(self) -> dict:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total else 0.0
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": hit_rate,
        }

    def total_rows(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
