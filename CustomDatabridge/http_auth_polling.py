# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger("HttpAuthPoll")

@dataclass
class _CachedToken:
    access_token: str
    expires_at: float

class OAuth2TokenCache:

    _MIN_TTL_S = 30.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], _CachedToken] = {}

    def get(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scope: str | None = None,
        timeout_s: float = 5.0,
    ) -> str | None:
        key = (token_url, client_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached.expires_at - time.time() > self._MIN_TTL_S:
                return cached.access_token

        body = {
            "client_id":     client_id,
            "client_secret": client_secret,
            "grant_type":    "client_credentials",
        }
        if scope:
            body["scope"] = scope
        try:
            resp = requests.post(
                token_url,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=timeout_s,
            )
        except Exception as exc:
            log.error("OAuth2 token request failed: %s", exc)
            return None
        if resp.status_code != 200:
            log.error("OAuth2 token endpoint %d: %s",
                      resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        token   = data.get("access_token")
        ttl     = float(data.get("expires_in", 300))
        if not token:
            log.error("OAuth2 response missing access_token: %s",
                      list(data.keys()))
            return None

        with self._lock:
            self._cache[key] = _CachedToken(
                access_token=token, expires_at=time.time() + ttl,
            )
        log.info("Acquired OAuth2 token from %s (ttl=%.0fs)", token_url, ttl)
        return token

_TOKEN_CACHE = OAuth2TokenCache()

_INDEX_RE = re.compile(r"^([^\[]+)?\[(-?\d+)\]$")

def json_pick(data: Any, path: str) -> Any:
    if data is None:
        return None
    p = (path or "").lstrip("$").lstrip(".").replace("/", ".")
    cur: Any = data
    for raw in (s for s in p.split(".") if s):
        m = _INDEX_RE.match(raw)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if key:
                if not isinstance(cur, dict) or key not in cur:
                    return None
                cur = cur[key]
            if not isinstance(cur, list):
                return None
            if -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        else:
            if not isinstance(cur, dict) or raw not in cur:
                return None
            cur = cur[raw]
    return cur

def _build_auth(source: dict) -> tuple[dict, dict]:
    headers: dict[str, str] = {}
    qextra:  dict[str, str] = {}
    auth_type = (source.get("auth_type") or "none").lower()

    if auth_type == "bearer":
        token = source.get("bearer_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key_header":
        key = source.get("api_key")
        if key:
            headers[source.get("api_key_header") or "X-API-Key"] = key
    elif auth_type == "api_key_query":
        key = source.get("api_key")
        if key:
            qextra[source.get("api_key_query") or "apikey"] = key
    elif auth_type == "oauth2_cc":
        url     = source.get("oauth_token_url")
        cid     = source.get("client_id")
        secret  = source.get("client_secret")
        scope   = source.get("scope")
        if url and cid and secret:
            tok = _TOKEN_CACHE.get(url, cid, secret, scope=scope)
            if tok:
                headers["Authorization"] = f"Bearer {tok}"
    elif auth_type == "basic":
        import base64
        u = source.get("username", "")
        p = source.get("password", "")
        token = base64.b64encode(f"{u}:{p}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers, qextra

def poll_http(source: dict, *, timeout_s: float = 5.0) -> Any:
    url = source.get("url") or source.get("host")
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "http://" + url.lstrip("/")

    method   = (source.get("method") or "GET").upper()
    json_path = (source.get("json_path") or "$.value").strip()

    headers, qextra = _build_auth(source)
    headers.setdefault("Accept", "application/json")

    params = dict(source.get("query_params") or {})
    params.update(qextra)

    try:
        resp = requests.request(
            method, url,
            headers=headers, params=params or None,
            timeout=timeout_s,
        )
    except Exception as exc:
        log.warning("HTTP %s %s failed: %s", method, url, exc)
        return None

    if resp.status_code == 401 and source.get("auth_type") == "oauth2_cc":
        key = (source.get("oauth_token_url"), source.get("client_id"))
        with _TOKEN_CACHE._lock:
            _TOKEN_CACHE._cache.pop(key, None)
        log.info("OAuth2 401 — invalidated cache, retrying once")
        return poll_http(source, timeout_s=timeout_s)

    if resp.status_code != 200:
        log.warning("HTTP %s %s → %d: %s",
                    method, url, resp.status_code, resp.text[:160])
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    return json_pick(data, json_path)
