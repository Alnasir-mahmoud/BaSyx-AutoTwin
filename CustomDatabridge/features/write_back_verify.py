
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Literal

Status = Literal[
    "OK",
    "MISMATCH",
    "READ_FAILED",
    "UNSUPPORTED",
]

@dataclass
class VerificationResult:
    status: Status
    written_value: float | int
    read_value: float | int | None
    register: int
    data_type: str
    tolerance: float
    elapsed_ms: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "writtenValue": self.written_value,
            "readValue": self.read_value,
            "register": self.register,
            "dataType": self.data_type,
            "tolerance": self.tolerance,
            "elapsedMs": round(self.elapsed_ms, 3),
            "error": self.error,
        }

    def format(self) -> str:
        if self.status == "OK":
            return (f"VERIFIED reg={self.register} "
                    f"wrote={self.written_value} "
                    f"read={self.read_value} "
                    f"({self.elapsed_ms:.1f}ms)")
        if self.status == "MISMATCH":
            return (f"MISMATCH reg={self.register} "
                    f"wrote={self.written_value} "
                    f"read={self.read_value} "
                    f"(tol={self.tolerance})")
        if self.status == "READ_FAILED":
            return (f"READ_FAILED reg={self.register} "
                    f"wrote={self.written_value} err={self.error}")
        return f"UNSUPPORTED reg={self.register} type={self.data_type}"

def _decode_registers(registers: list[int], data_type: str) -> float | int:
    dt = data_type.lower()
    if dt in ("float32", "real", "float"):
        raw = struct.pack(">HH", *registers[:2])
        return struct.unpack(">f", raw)[0]
    if dt in ("int16", "int"):
        raw = struct.pack(">H", registers[0] & 0xFFFF)
        return struct.unpack(">h", raw)[0]
    if dt in ("uint16", "uint", "word"):
        return int(registers[0]) & 0xFFFF
    if dt in ("int32", "dint"):
        raw = struct.pack(">HH", *registers[:2])
        return struct.unpack(">i", raw)[0]
    if dt in ("uint32", "udint", "dword"):
        raw = struct.pack(">HH", *registers[:2])
        return struct.unpack(">I", raw)[0]
    raise ValueError(f"Unsupported data_type: {data_type}")

_SUPPORTED_TYPES = {
    "float32", "real", "float",
    "int16", "int",
    "uint16", "uint", "word",
    "int32", "dint",
    "uint32", "udint", "dword",
}

def _register_count(data_type: str) -> int:
    dt = data_type.lower()
    if dt not in _SUPPORTED_TYPES:
        raise ValueError(f"Unsupported data_type: {data_type}")
    if dt in ("int16", "uint16", "int", "uint", "word"):
        return 1
    return 2

def verify_modbus_write(
    client,
    register: int,
    slave_id: int,
    data_type: str,
    written_value: float | int,
    *,
    tolerance: float = 0.001,
    readback_delay_s: float = 0.02,
    use_holding_register: bool = True,
) -> VerificationResult:
    t0 = time.monotonic()

    try:
        count = _register_count(data_type)
    except ValueError:
        return VerificationResult(
            status="UNSUPPORTED",
            written_value=written_value,
            read_value=None,
            register=register,
            data_type=data_type,
            tolerance=tolerance,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )

    if readback_delay_s > 0:
        time.sleep(readback_delay_s)

    try:
        if use_holding_register:
            resp = client.read_holding_registers(
                register, count=count, slave=slave_id,
            )
        else:
            resp = client.read_input_registers(
                register, count=count, slave=slave_id,
            )
    except Exception as exc:
        return VerificationResult(
            status="READ_FAILED",
            written_value=written_value,
            read_value=None,
            register=register,
            data_type=data_type,
            tolerance=tolerance,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
            error=str(exc),
        )

    if resp is None or getattr(resp, "isError", lambda: True)():
        return VerificationResult(
            status="READ_FAILED",
            written_value=written_value,
            read_value=None,
            register=register,
            data_type=data_type,
            tolerance=tolerance,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
            error=str(resp) if resp is not None else "no response",
        )

    try:
        read_value = _decode_registers(list(resp.registers), data_type)
    except Exception as exc:
        return VerificationResult(
            status="READ_FAILED",
            written_value=written_value,
            read_value=None,
            register=register,
            data_type=data_type,
            tolerance=tolerance,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
            error=f"decode error: {exc}",
        )

    if isinstance(read_value, float) or isinstance(written_value, float):
        diff = abs(float(read_value) - float(written_value))
        matched = diff <= tolerance
    else:
        matched = int(read_value) == int(written_value)

    return VerificationResult(
        status="OK" if matched else "MISMATCH",
        written_value=written_value,
        read_value=read_value,
        register=register,
        data_type=data_type,
        tolerance=tolerance,
        elapsed_ms=(time.monotonic() - t0) * 1000.0,
    )
