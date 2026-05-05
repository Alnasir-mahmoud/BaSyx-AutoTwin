# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar


from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from validator.idta_validator import (  # noqa: E402
    IDTAValidator,
    TEMPLATES,
    validate_batch,
)

def _first_key_value(semantic_id: dict | None) -> str | None:
    if not semantic_id:
        return None
    keys = semantic_id.get("keys") or []
    if not keys:
        return None
    return keys[0].get("value")

def _detect_type(submodel: dict) -> str | None:
    sid = (_first_key_value(submodel.get("semanticId")) or "").rstrip("/")
    for tt, meta in TEMPLATES.items():
        if meta["expected_semantic_id"].rstrip("/") == sid:
            return tt
    return None

def _load_json_file(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _extract_from_aasx(aasx_path: Path) -> dict:
    with zipfile.ZipFile(aasx_path) as z:
        candidates = [
            n for n in z.namelist()
            if n.endswith(".json") and "aasx/" in n
        ]
        if candidates:
            with z.open(candidates[0]) as fh:
                return json.loads(fh.read().decode("utf-8"))
        xml_candidates = [
            n for n in z.namelist()
            if n.endswith(".xml") and "aasx/" in n
            and not n.endswith("-origin") and "_rels" not in n
        ]
        if xml_candidates:
            with z.open(xml_candidates[0]) as fh:
                xml_bytes = fh.read()
            return _xml_env_to_dict(xml_bytes)
    raise RuntimeError(f"No AAS environment JSON/XML found in {aasx_path}")

def _xml_env_to_dict(xml_bytes: bytes) -> dict:
    ns = {"aas": "https://admin-shell.io/aas/3/0"}
    root = ET.fromstring(xml_bytes)
    out_submodels: list[dict] = []
    for sm in root.iter("{%s}submodel" % ns["aas"]):
        sid_el = sm.find("aas:semanticId", ns)
        first_key = None
        if sid_el is not None:
            k = sid_el.find("aas:keys/aas:key/aas:value", ns)
            first_key = k.text if k is not None else None
        kind_el = sm.find("aas:kind", ns)
        kind = kind_el.text if kind_el is not None else None

        def _walk(parent: ET.Element) -> list[dict]:
            items: list[dict] = []
            for el in parent.findall(
                "aas:submodelElements/*", ns
            ) + parent.findall("aas:value/*", ns):
                id_short_el = el.find("aas:idShort", ns)
                id_short = (
                    id_short_el.text if id_short_el is not None else None
                )
                sid_el2 = el.find("aas:semanticId", ns)
                has_sid = sid_el2 is not None
                children = _walk(el)
                item: dict[str, Any] = {"idShort": id_short}
                if has_sid:
                    item["semanticId"] = {"keys": [{"value": ""}]}
                if children:
                    item["value"] = children
                items.append(item)
            return items

        out_submodels.append({
            "id": (sm.find("aas:id", ns).text
                   if sm.find("aas:id", ns) is not None else ""),
            "semanticId": (
                {"keys": [{"value": first_key}]} if first_key else None
            ),
            "kind": kind,
            "submodelElements": _walk(sm),
        })
    return {"submodels": out_submodels}

def _submodels_from_env(env: dict) -> list[dict]:
    if isinstance(env, dict) and "submodels" in env:
        return list(env["submodels"])
    if isinstance(env, dict) and env.get("modelType") == "Submodel":
        return [env]
    if isinstance(env, dict) and "submodelElements" in env:
        return [env]
    raise ValueError(
        "Input is not a recognised AAS environment or Submodel JSON."
    )

def _human_report(summary: dict) -> str:
    lines: list[str] = []
    total = summary["total"]
    passed = summary["passed"]
    rate = summary["passRate"] * 100.0
    lines.append("")
    lines.append(f"Validated {total} submodel(s): "
                 f"{passed} passed, {total - passed} failed "
                 f"({rate:.1f}%).")
    for idx, item in enumerate(summary["items"], 1):
        status = "PASS" if item["passed"] else "FAIL"
        lines.append(f"  [{idx}] {item['submodelType']:<10} {status}")
        for e in item["errors"]:
            lines.append(f"      [FAIL] {e}")
        for w in item["warnings"]:
            lines.append(f"      [WARN] {w}")
    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="idta-validator",
        description="Validate generated Submodels against IDTA templates.",
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", type=Path,
                   help="Single Submodel JSON file")
    g.add_argument("--env", type=Path,
                   help="AAS environment JSON file with submodels[]")
    g.add_argument("--aasx", type=Path, help="AASX package file")
    parser.add_argument(
        "--type", choices=list(TEMPLATES.keys()),
        help="Force a specific template type (needed with --file if "
             "semanticId is missing or non-standard)"
    )
    parser.add_argument(
        "--format", choices=("text", "json"), default="text",
        help="Output format (default: text)"
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Fail (exit 1) if any submodel fails, "
             "including unknown ones."
    )
    args = parser.parse_args(argv)

    if args.file is not None:
        submodels = [_load_json_file(args.file)]
    elif args.env is not None:
        submodels = _submodels_from_env(_load_json_file(args.env))
    else:
        submodels = _submodels_from_env(_extract_from_aasx(args.aasx))

    typed: list[tuple[dict, str]] = []
    unknown: list[dict] = []
    for sm in submodels:
        tt = args.type or _detect_type(sm)
        if tt is None:
            unknown.append(sm)
            continue
        typed.append((sm, tt))

    validator = IDTAValidator()
    summary = validate_batch(typed, validator=validator)
    summary["unknown"] = len(unknown)

    if args.format == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(_human_report(summary))
        if unknown:
            print(f"\nSkipped {len(unknown)} submodel(s) with "
                  "unknown/non-IDTA semanticId.")

    failed = summary["failed"] > 0 or (args.strict and unknown)
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
