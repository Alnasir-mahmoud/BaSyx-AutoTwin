# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

import json
import os
from pathlib import Path

_CONN_FILE = Path(__file__).resolve().parent / "connection.json"

DEFAULT_HOST = "localhost"

DEFAULT_PORTS: dict[str, int] = {
    "aas":           8081,
    "aas_registry":  8082,
    "sm_registry":   8083,
    "discovery":     8084,
    "orchestrator":  8085,
    "influxdb":      8086,
    "mqtt":          1883,
    "grafana":       3001,
    "ui":            3000,
    "gui":           5000,
    "dashboard":     8087,
}

_ENV_URL_VARS: dict[str, str] = {
    "aas":           "AAS_SERVER_URL",
    "aas_registry":  "AAS_REGISTRY_URL",
    "sm_registry":   "SM_REGISTRY_URL",
    "discovery":     "AAS_DISCOVERY_URL",
    "orchestrator":  "ORCHESTRATOR_URL",
    "influxdb":      "INFLUXDB_URL",
    "grafana":       "GRAFANA_URL",
    "mqtt":          "MQTT_URL",
    "ui":            "AAS_UI_URL",
    "dashboard":     "DASHBOARD_API_URL",
}

def load() -> dict:
    data = {"host": DEFAULT_HOST, "ports": dict(DEFAULT_PORTS)}
    if _CONN_FILE.exists():
        try:
            with open(_CONN_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            host = stored.get("host")
            if host:
                data["host"] = str(host).strip()
            for k, v in (stored.get("ports") or {}).items():
                if k in DEFAULT_PORTS:
                    try:
                        data["ports"][k] = int(v)
                    except (ValueError, TypeError):
                        pass
        except Exception as exc:
            print(f"[connection] Failed to read {_CONN_FILE}: {exc}")
    return data

def save(data: dict) -> dict:
    current = load()
    if data.get("host") is not None:
        host = str(data["host"]).strip() or DEFAULT_HOST
        current["host"] = host
    for k, v in (data.get("ports") or {}).items():
        if k in DEFAULT_PORTS:
            try:
                current["ports"][k] = int(v)
            except (ValueError, TypeError):
                pass
    try:
        with open(_CONN_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception as exc:
        print(f"[connection] Failed to write {_CONN_FILE}: {exc}")
    return current

def is_configured() -> bool:
    return _CONN_FILE.exists()

def get_url(
    service: str,
    *,
    scheme: str | None = None,
    external: bool = False,
) -> str:
    if not external:
        env_var = _ENV_URL_VARS.get(service)
        if env_var:
            env_val = os.environ.get(env_var)
            if env_val:
                return env_val.rstrip("/")

    conn = load()
    host = conn.get("host") or DEFAULT_HOST
    port = conn["ports"].get(service, DEFAULT_PORTS.get(service, 80))
    if scheme is None:
        scheme = "tcp" if service == "mqtt" else "http"
    return f"{scheme}://{host}:{port}"
