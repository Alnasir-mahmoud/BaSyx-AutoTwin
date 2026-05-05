# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

CANONICAL_TYPES: list[str] = [
    "BOOL",
    "INT16", "UINT16",
    "INT32", "UINT32",
    "INT64", "UINT64",
    "FLOAT32", "FLOAT64",
    "STRING", "BYTE",
]

_ALIASES: dict[str, str] = {
    "bool": "BOOL",
    "int16": "INT16",
    "uint16": "UINT16",
    "int32": "INT32",
    "uint32": "UINT32",
    "int64": "INT64",
    "uint64": "UINT64",
    "float32": "FLOAT32",
    "float64": "FLOAT64",
    "real": "FLOAT32",
    "lreal": "FLOAT64",
    "string": "STRING",
    "byte": "BYTE",
    "word": "UINT16",
    "dword": "UINT32",
    "lword": "UINT64",
    "REAL": "FLOAT32",
    "LREAL": "FLOAT64",
    "INT": "INT16",
    "UINT": "UINT16",
    "WORD": "UINT16",
    "DINT": "INT32",
    "UDINT": "UINT32",
    "DWORD": "UINT32",
    "LINT": "INT64",
    "ULINT": "UINT64",
    "LWORD": "UINT64",
    "SINT": "INT16",
    "USINT": "UINT16",
    "CHAR": "STRING",
    "WCHAR": "STRING",
}

_TO_PLC4X: dict[str, str] = {
    "BOOL":    "BOOL",
    "INT16":   "INT",
    "UINT16":  "UINT",
    "INT32":   "DINT",
    "UINT32":  "UDINT",
    "INT64":   "LINT",
    "UINT64":  "ULINT",
    "FLOAT32": "REAL",
    "FLOAT64": "LREAL",
    "STRING":  "STRING[100]",
    "BYTE":    "BYTE",
}

_TO_CUSTOM: dict[str, str] = {
    "BOOL":    "bool",
    "INT16":   "int16",
    "UINT16":  "uint16",
    "INT32":   "int32",
    "UINT32":  "uint32",
    "INT64":   "int64",
    "UINT64":  "uint64",
    "FLOAT32": "float32",
    "FLOAT64": "float64",
    "STRING":  "string",
    "BYTE":    "byte",
}

def canonical(name: str | None) -> str:
    if not name:
        return "FLOAT32"
    n = name.strip()
    if n in CANONICAL_TYPES:
        return n
    upper = n.upper()
    if upper in CANONICAL_TYPES:
        return upper
    return _ALIASES.get(n, _ALIASES.get(upper, _ALIASES.get(n.lower(), upper)))

def to_plc4x(name: str | None) -> str:
    return _TO_PLC4X.get(canonical(name), "REAL")

def to_custom(name: str | None) -> str:
    return _TO_CUSTOM.get(canonical(name), "float32")
