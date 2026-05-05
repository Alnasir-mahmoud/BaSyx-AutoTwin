# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

import logging
import os

import requests

import connection as _conn
from grafana_dashboard_builder import (PropertySpec, build_dashboard,
                                      build_protocol_dashboard)
from influxdb_provisioner import DEFAULT_TOKEN as _INFLUX_TOKEN
from influxdb_provisioner import DEFAULT_ORG as _INFLUX_ORG

log = logging.getLogger("GrafanaProvisioner")

_DEFAULT_USER = os.environ.get("GRAFANA_USER", "admin")
_DEFAULT_PASS = os.environ.get("GRAFANA_PASSWORD", "admin")
_DATASOURCE_NAME = "InfluxDB-AAS"

class GrafanaProvisioner:
    def __init__(
        self,
        url: str | None = None,
        user: str | None = None,
        password: str | None = None,
        *,
        timeout_s: float = 8.0,
    ) -> None:
        self.url = (url or _conn.get_url("grafana")).rstrip("/")
        self.auth = (user or _DEFAULT_USER, password or _DEFAULT_PASS)
        self.timeout_s = timeout_s

    def is_reachable(self) -> bool:
        try:
            r = requests.get(f"{self.url}/api/health", timeout=self.timeout_s)
            return r.status_code < 500
        except Exception as exc:
            log.debug("Grafana health check failed: %s", exc)
            return False

    def find_datasource(self, name: str = _DATASOURCE_NAME) -> dict | None:
        try:
            r = requests.get(
                f"{self.url}/api/datasources/name/{name}",
                auth=self.auth, timeout=self.timeout_s,
            )
            if r.status_code == 200:
                return r.json()
        except Exception as exc:
            log.debug("Datasource lookup failed: %s", exc)
        return None

    def ensure_influx_datasource(
        self,
        *,
        name: str = _DATASOURCE_NAME,
        influx_url: str | None = None,
        token: str | None = None,
        org: str | None = None,
        default_bucket: str = "hems",
    ) -> str | None:
        existing = self.find_datasource(name)
        body = {
            "name":     name,
            "type":     "influxdb",
            "access":   "proxy",
            "url":      (influx_url or
                         os.environ.get("INFLUX_INTERNAL_URL",
                                         "http://influxdb:8086")),
            "isDefault": True,
            "jsonData": {
                "version":       "Flux",
                "organization":  org or _INFLUX_ORG,
                "defaultBucket": default_bucket,
                "tlsSkipVerify": True,
                "httpMode":      "POST",
            },
            "secureJsonData": {"token": token or _INFLUX_TOKEN},
        }
        try:
            if existing:
                ds_id = existing["id"]
                r = requests.put(
                    f"{self.url}/api/datasources/{ds_id}",
                    auth=self.auth, json=body, timeout=self.timeout_s,
                )
                if r.status_code in (200, 201):
                    return existing.get("uid") or (
                        r.json().get("datasource") or r.json()).get("uid")
                log.error("Datasource update failed (%d): %s",
                          r.status_code, r.text[:300])
                return None
            else:
                r = requests.post(
                    f"{self.url}/api/datasources",
                    auth=self.auth, json=body, timeout=self.timeout_s,
                )
            if r.status_code in (200, 201):
                ds = r.json().get("datasource") or r.json()
                return ds.get("uid")
            log.error("Datasource create failed (%d): %s",
                      r.status_code, r.text[:300])
        except Exception as exc:
            log.error("Datasource provisioning error: %s", exc)
        return None

    def upload_dashboard(self, payload: dict) -> dict | None:
        try:
            r = requests.post(
                f"{self.url}/api/dashboards/db",
                auth=self.auth, json=payload, timeout=self.timeout_s,
            )
            if r.status_code in (200, 201):
                return r.json()
            log.error("Dashboard upload failed (%d): %s",
                      r.status_code, r.text[:300])
        except Exception as exc:
            log.error("Dashboard upload error: %s", exc)
        return None

    def provision_for_asset(
        self,
        asset_name: str,
        properties: list[PropertySpec],
        *,
        token: str | None = None,
        org: str | None = None,
    ) -> dict | None:
        if not properties:
            log.info("No properties for asset %s — nothing to dashboard.",
                     asset_name)
            return None
        if not self.is_reachable():
            log.warning("Grafana at %s not reachable.", self.url)
            return None

        default_bucket = properties[0].bucket if properties else "hems"
        ds_uid = self.ensure_influx_datasource(
            token=token, org=org, default_bucket=default_bucket,
        )
        if not ds_uid:
            return None

        payload = build_dashboard(asset_name, properties,
                                   datasource_uid=ds_uid)
        result = self.upload_dashboard(payload)
        if result is None:
            return None

        return {
            "url":          result.get("url"),
            "uid":          result.get("uid"),
            "datasourceUid": ds_uid,
            "fullUrl":      _conn.get_url("grafana", external=True)
                            + (result.get("url") or ""),
        }

    def provision_protocol_dashboards(
        self,
        asset_name: str,
        protocols_properties: dict,
        *,
        token: str | None = None,
        org: str | None = None,
    ) -> dict:
        results: dict = {}
        if not self.is_reachable():
            return results

        all_props = [p for props in protocols_properties.values() for p in props]
        if not all_props:
            return results

        ds_uid = self.ensure_influx_datasource(
            token=token, org=org,
            default_bucket=all_props[0].bucket,
        )
        if not ds_uid:
            return results

        for protocol, properties in protocols_properties.items():
            if not properties:
                continue
            payload = build_protocol_dashboard(
                asset_name, protocol, properties, datasource_uid=ds_uid,
            )
            result = self.upload_dashboard(payload)
            if result:
                results[protocol] = {
                    "url":     result.get("url"),
                    "uid":     result.get("uid"),
                    "fullUrl": _conn.get_url("grafana", external=True)
                               + (result.get("url") or ""),
                }
        return results
