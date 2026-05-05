# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar


from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_ROOT = (
    REPO_ROOT / "IDTA-Templates" / "submodel-templates" / "published"
)

TEMPLATES = {
    "AID": {
        "path": (
            TEMPLATES_ROOT
            / "Asset Interfaces Description" / "1" / "1"
            / "IDTA 02017-1-1_Template_Asset Interfaces Description.json"
        ),
        "expected_semantic_id": (
            "https://admin-shell.io/idta/AssetInterfacesDescription/1/1/Submodel"
        ),
        "spec_number": "IDTA 02017-1-1",
        "human_name": "Asset Interfaces Description",
    },
    "AIMC": {
        "path": (
            TEMPLATES_ROOT
            / "Asset Interfaces Mapping Configuration" / "1" / "0"
            / "IDTA 02027-1-0_Template_AIMC .json"
        ),
        "expected_semantic_id": (
            "https://admin-shell.io/idta/"
            "AssetInterfacesMappingConfiguration/1/0/Submodel"
        ),
        "spec_number": "IDTA 02027-1-0",
        "human_name": "Asset Interfaces Mapping Configuration",
    },
    "TimeSeries": {
        "path": (
            TEMPLATES_ROOT
            / "Time Series Data" / "1" / "1"
            / "IDTA 02008-1-1_Template_TimeSeriesData.json"
        ),
        "expected_semantic_id": "https://admin-shell.io/idta/TimeSeries/1/1",
        "spec_number": "IDTA 02008-1-1",
        "human_name": "Time Series Data",
    },
}

@dataclass
class ValidationResult:
    submodel_type: str
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_rules: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.passed = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "submodelType": self.submodel_type,
            "passed": self.passed,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "checkedRules": list(self.checked_rules),
        }

def _first_key_value(semantic_id: dict | None) -> str | None:
    if not semantic_id:
        return None
    keys = semantic_id.get("keys") or []
    if not keys:
        return None
    return keys[0].get("value")

def _cardinality(element: dict) -> str | None:
    for q in element.get("qualifiers") or []:
        q_type = (q.get("type") or "").lower()
        if "cardinality" in q_type:
            return q.get("value")
    return None

def _iter_submodel_elements(elements: list[dict]):
    stack: list[tuple[dict, tuple[str, ...]]] = [
        (el, ()) for el in elements
    ]
    while stack:
        el, path = stack.pop()
        yield el, path
        nested = el.get("value")
        if isinstance(nested, list) and all(
            isinstance(x, dict) for x in nested
        ):
            new_path = path + (el.get("idShort", ""),)
            stack.extend((child, new_path) for child in nested)

def _extract_top_level_mandatory(template_submodel: dict) -> set[str]:
    mandatory: set[str] = set()
    for el in template_submodel.get("submodelElements") or []:
        card = _cardinality(el) or "One"
        if card in ("One", "OneToMany"):
            id_short = el.get("idShort")
            if id_short:
                mandatory.add(id_short)
    return mandatory

def _extract_deep_mandatory(
    template_submodel: dict,
) -> set[tuple[str, ...]]:
    mandatory: set[tuple[str, ...]] = set()
    for el, parent_path in _iter_submodel_elements(
        template_submodel.get("submodelElements") or []
    ):
        if _cardinality(el) in ("One", "OneToMany"):
            id_short = el.get("idShort")
            if id_short:
                mandatory.add(parent_path + (id_short,))
    return mandatory

class IDTAValidator:

    def __init__(self, templates_root: Path | None = None) -> None:
        self._loaded: dict[str, dict] = {}
        if templates_root is not None:
            self._override_root = templates_root
        else:
            self._override_root = None

    def _load_template(self, submodel_type: str) -> dict:
        if submodel_type in self._loaded:
            return self._loaded[submodel_type]
        if submodel_type not in TEMPLATES:
            raise ValueError(
                f"Unknown submodel type '{submodel_type}'. "
                f"Supported: {list(TEMPLATES)}"
            )
        meta = TEMPLATES[submodel_type]
        path = meta["path"]
        if self._override_root is not None:
            path = Path(str(path).replace(
                str(TEMPLATES_ROOT), str(self._override_root)
            ))
        with open(path, "r", encoding="utf-8") as f:
            aas_env = json.load(f)
        submodels = aas_env.get("submodels") or []
        if not submodels:
            raise RuntimeError(
                f"Template '{path}' contains no submodels."
            )
        template_submodel = submodels[0]
        self._loaded[submodel_type] = template_submodel
        return template_submodel

    def validate(
        self, submodel_json: dict, submodel_type: str
    ) -> ValidationResult:
        result = ValidationResult(submodel_type=submodel_type)
        template = self._load_template(submodel_type)
        meta = TEMPLATES[submodel_type]

        result.checked_rules.append("R1: semanticId matches template")
        actual_sid = _first_key_value(submodel_json.get("semanticId"))
        expected_sid = meta["expected_semantic_id"]
        if actual_sid != expected_sid:
            if (actual_sid or "").rstrip("/") != expected_sid.rstrip("/"):
                result.fail(
                    f"semanticId mismatch: expected '{expected_sid}', "
                    f"got '{actual_sid}'"
                )

        result.checked_rules.append(
            "R2: mandatory top-level SubmodelElements present"
        )
        top_mandatory = _extract_top_level_mandatory(template)
        top_actual = {
            el.get("idShort", "")
            for el in (submodel_json.get("submodelElements") or [])
        }
        missing_top = sorted(top_mandatory - top_actual)
        if missing_top:
            result.fail(
                f"Missing mandatory top-level elements: {missing_top}"
            )

        result.checked_rules.append(
            "R2b: deep mandatory elements (soft / warning)"
        )
        deep_mandatory = _extract_deep_mandatory(template)
        actual_paths = {
            path + (el.get("idShort", ""),)
            for el, path in _iter_submodel_elements(
                submodel_json.get("submodelElements") or []
            )
        }
        missing_deep = sorted(
            "/".join(p) for p in deep_mandatory - actual_paths
            if p[:-1] in actual_paths or not p[:-1]
        )
        if missing_deep:
            result.warn(
                f"Deep mandatory elements missing "
                f"(inside present variants): {missing_deep[:10]}"
                + (" ..." if len(missing_deep) > 10 else "")
            )

        result.checked_rules.append(
            "R3: all SubmodelElements have semanticId"
        )
        missing_sids: list[str] = []
        for el, parent_path in _iter_submodel_elements(
            submodel_json.get("submodelElements") or []
        ):
            if not el.get("semanticId"):
                missing_sids.append(
                    "/".join(parent_path + (el.get("idShort", "?"),))
                )
        if missing_sids:
            result.warn(
                f"SubmodelElements without semanticId: {missing_sids}"
            )

        result.checked_rules.append("R4: submodel kind is Instance, not Template")
        if submodel_json.get("kind") == "Template":
            result.fail(
                "Submodel.kind is 'Template'; expected 'Instance' "
                "(or kind omitted)."
            )

        return result

def validate_batch(
    submodels: list[tuple[dict, str]],
    validator: IDTAValidator | None = None,
) -> dict[str, Any]:
    validator = validator or IDTAValidator()
    per_item: list[dict[str, Any]] = []
    total = len(submodels)
    passed = 0
    for submodel_json, submodel_type in submodels:
        res = validator.validate(submodel_json, submodel_type)
        per_item.append(res.to_dict())
        if res.passed:
            passed += 1
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "passRate": (passed / total) if total else 0.0,
        "items": per_item,
    }
