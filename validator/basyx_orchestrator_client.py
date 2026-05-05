# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

import base64
import logging
import time
from typing import Any

log = logging.getLogger("OrchestratorClient")

_RESULTS_B64 = base64.b64encode(b"TestResults").decode()
_UNSUCCESSFUL_B64 = base64.b64encode(b"UnsuccessfulTestResults").decode()

def _get_prop(smc: dict, name: str) -> str:
    for el in smc.get("value", []) or []:
        if el.get("idShort") == name:
            return str(el.get("value") or "")
    return ""

def _latest_result_for(submodel_id: str,
                        elements: list[dict]) -> dict | None:
    matches = [
        e for e in elements
        if e.get("modelType") == "SubmodelElementCollection"
        and _get_prop(e, "ComparedSubmodelId") == submodel_id
    ]
    return matches[-1] if matches else None

def _parse_result(smc: dict) -> dict[str, Any]:
    errors_raw = _get_prop(smc, "Errors")
    warnings_raw = _get_prop(smc, "Warnings")
    differences_raw = _get_prop(smc, "Differences")
    infos_raw = _get_prop(smc, "Infos")

    def _split(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()] if s else []

    errors = _split(errors_raw)
    warnings = _split(warnings_raw)
    differences = _split(differences_raw)
    infos = _split(infos_raw)
    passed = not errors
    return {
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "differences": differences,
        "infos": infos,
        "source": "BaSyx Test Orchestrator",
    }

def fetch_results_for(
    orchestrator_url: str,
    submodel_ids: list[str],
    *,
    poll_delay_s: float = 2.5,
    poll_interval_s: float = 1.5,
    timeout_s: float = 25.0,
) -> dict[str, dict[str, Any]]:
    try:
        import requests as _req
    except ImportError:
        return {
            sid: {
                "passed": False,
                "errors": ["requests not installed"],
                "warnings": [],
                "differences": [],
                "infos": [],
                "source": "UNAVAILABLE",
            }
            for sid in submodel_ids
        }

    url = (
        f"{orchestrator_url.rstrip('/')}/submodels/{_RESULTS_B64}"
    )

    time.sleep(poll_delay_s)
    deadline = time.time() + timeout_s
    remaining = set(submodel_ids)
    results: dict[str, dict] = {}

    while time.time() < deadline and remaining:
        try:
            resp = _req.get(url, timeout=5.0)
            if resp.status_code == 200:
                elements = resp.json().get("submodelElements") or []
                for sid in list(remaining):
                    match = _latest_result_for(sid, elements)
                    if match:
                        results[sid] = _parse_result(match)
                        remaining.discard(sid)
        except Exception as exc:
            log.debug("Orchestrator poll error: %s", exc)

        if remaining:
            time.sleep(poll_interval_s)

    for sid in remaining:
        results[sid] = {
            "passed": False,
            "errors": [
                f"No validation result from orchestrator within "
                f"{timeout_s:.0f}s (MQTT/network issue?)"
            ],
            "warnings": [],
            "differences": [],
            "infos": [],
            "source": "TIMEOUT",
        }

    return results

def validate_batch_via_orchestrator(
    typed_submodels: list[tuple[dict, str]],
    orchestrator_url: str,
    *,
    poll_delay_s: float = 2.5,
    timeout_s: float = 25.0,
    fallback_validator=None,
) -> dict[str, Any]:
    try:
        import requests as _req
        health_url = f"{orchestrator_url.rstrip('/')}/actuator/health"
        try:
            r = _req.get(health_url, timeout=3.0)
            reachable = r.status_code < 500
        except Exception:
            reachable = False
    except ImportError:
        reachable = False

    if not reachable:
        log.warning(
            "Test Orchestrator at %s unreachable — "
            "falling back to local IDTAValidator.", orchestrator_url,
        )
        if fallback_validator is not None:
            from validator.idta_validator import validate_batch as _vb
            return _vb(typed_submodels, validator=fallback_validator)
        items = [
            {
                "submodelType": t,
                "passed": False,
                "errors": ["Orchestrator unreachable; no local fallback."],
                "warnings": [],
                "source": "UNAVAILABLE",
            }
            for _, t in typed_submodels
        ]
        return {
            "total": len(items),
            "passed": 0,
            "failed": len(items),
            "passRate": 0.0,
            "items": items,
            "source": "UNAVAILABLE",
        }

    submodel_ids = [sm["id"] for sm, _ in typed_submodels]
    type_map = {sm["id"]: t for sm, t in typed_submodels}

    raw = fetch_results_for(
        orchestrator_url,
        submodel_ids,
        poll_delay_s=poll_delay_s,
        timeout_s=timeout_s,
    )

    items = []
    for sid in submodel_ids:
        r = raw[sid]
        items.append(
            {
                "submodelType": type_map[sid],
                "passed": r["passed"],
                "errors": r["errors"],
                "warnings": r["warnings"],
                "differences": r.get("differences", []),
                "infos": r.get("infos", []),
                "source": r.get("source", "BaSyx Test Orchestrator"),
            }
        )

    total = len(items)
    passed = sum(1 for i in items if i["passed"])
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "passRate": passed / total if total else 0.0,
        "items": items,
        "source": "BaSyx Test Orchestrator",
    }
