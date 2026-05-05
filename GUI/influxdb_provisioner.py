# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

import logging
import os
import re

import requests

import connection as _conn

log = logging.getLogger("InfluxProvisioner")

DEFAULT_TOKEN = os.environ.get(
    "INFLUXDB_TOKEN",
    "S18VeAlq042B4naMX31oqIaSGmUmOLAC-DV3VIdkxDJuAhTXLTVFEchyTSmCcUAmB7Wu94KgExzV8gJaDjzR3Q==",
)
DEFAULT_ORG = os.environ.get("INFLUXDB_ORG", "basyx")

def _sanitize_bucket(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", (name or "asset").strip())
    cleaned = cleaned.lstrip("-_") or "asset"
    return cleaned[:64]

class InfluxProvisioner:
    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        org: str | None = None,
        *,
        timeout_s: float = 5.0,
    ) -> None:
        self.url = (url or _conn.get_url("influxdb")).rstrip("/")
        self.token = token or DEFAULT_TOKEN
        self.org = org or DEFAULT_ORG
        self.timeout_s = timeout_s
        self._headers = {
            "Authorization": f"Token {self.token}",
            "Content-Type":  "application/json",
        }
        self._org_id_cache: str | None = None

    def is_reachable(self) -> bool:
        try:
            r = requests.get(f"{self.url}/health", timeout=self.timeout_s)
            return r.status_code < 500
        except Exception as exc:
            log.debug("Influx health check failed: %s", exc)
            return False

    def get_org_id(self) -> str | None:
        if self._org_id_cache:
            return self._org_id_cache
        try:
            r = requests.get(
                f"{self.url}/api/v2/orgs",
                params={"org": self.org},
                headers=self._headers,
                timeout=self.timeout_s,
            )
            if r.status_code != 200:
                log.warning("Influx /orgs returned %d: %s",
                            r.status_code, r.text[:200])
                return None
            for org in r.json().get("orgs", []):
                if org.get("name") == self.org:
                    self._org_id_cache = org.get("id")
                    return self._org_id_cache
        except Exception as exc:
            log.warning("Influx /orgs lookup failed: %s", exc)
        return None

    def find_bucket(self, name: str) -> dict | None:
        try:
            r = requests.get(
                f"{self.url}/api/v2/buckets",
                params={"name": name, "org": self.org},
                headers=self._headers,
                timeout=self.timeout_s,
            )
            if r.status_code != 200:
                return None
            for b in r.json().get("buckets", []):
                if b.get("name") == name:
                    return b
        except Exception as exc:
            log.debug("Influx /buckets lookup failed: %s", exc)
        return None

    def ensure_bucket(self, name: str) -> dict | None:
        existing = self.find_bucket(name)
        if existing:
            return existing
        org_id = self.get_org_id()
        if not org_id:
            log.error("Cannot create bucket %r — org %r not found.",
                      name, self.org)
            return None
        body = {
            "name":     name,
            "orgID":    org_id,
            "retentionRules": [],
        }
        try:
            r = requests.post(
                f"{self.url}/api/v2/buckets",
                headers=self._headers, json=body,
                timeout=self.timeout_s,
            )
            if r.status_code in (200, 201):
                return r.json()
            log.error("Bucket create failed (%d): %s",
                      r.status_code, r.text[:300])
        except Exception as exc:
            log.error("Bucket create error: %s", exc)
        return None

    def provision_for_asset(self, asset_name: str) -> dict[str, str] | None:
        if not self.is_reachable():
            log.warning("InfluxDB at %s is not reachable.", self.url)
            return None
        bucket = _sanitize_bucket(asset_name)
        if self.ensure_bucket(bucket) is None:
            return None
        external_url = _conn.get_url("influxdb", external=True)
        return {
            "InfluxServerUrl": external_url,
            "InfluxToken":     self.token,
            "InfluxOrg":       self.org,
            "InfluxBucket":    bucket,
        }
