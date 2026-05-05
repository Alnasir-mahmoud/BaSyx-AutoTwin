# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

import base64
import json
import logging
import re
import struct
import threading
from typing import Callable, Optional
from urllib.parse import unquote

import requests

log = logging.getLogger("AASChangeListener")

_UPDATE_RE = re.compile(
    r"^sm-repository/[^/]+/submodels/(?P<smB64>[^/]+)"
    r"(?:/submodelElements/(?P<path>[^/]+))?"
    r"/updated$"
)

def _decode_sm_id(b64: str) -> str:
    pad = '=' * (-len(b64) % 4)
    try:
        return base64.urlsafe_b64decode(b64 + pad).decode("utf-8")
    except Exception:
        return b64

def parse_topic(topic: str) -> Optional[tuple[str, str]]:
    m = _UPDATE_RE.match(topic)
    if not m:
        return None
    sm_b64 = m.group("smB64")
    path   = m.group("path") or ""
    return _decode_sm_id(sm_b64), unquote(path)

def _encode_modbus_value(value, data_type: str):
    dt = (data_type or "float32").lower()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if dt in ("float32", "real"):
        raw = struct.pack(">f", v)
        return list(struct.unpack(">HH", raw))
    if dt in ("int16",):
        return [struct.unpack(">H", struct.pack(">h", int(v)))[0]]
    if dt in ("uint16", "word"):
        return [int(v) & 0xFFFF]
    if dt in ("int32", "dint"):
        raw = struct.pack(">i", int(v))
        return list(struct.unpack(">HH", raw))
    if dt in ("uint32", "udint", "dword"):
        raw = struct.pack(">I", int(v))
        return list(struct.unpack(">HH", raw))
    if dt in ("float64", "lreal"):
        raw = struct.pack(">d", v)
        return list(struct.unpack(">HHHH", raw))
    return None

def write_modbus(source: dict, value) -> bool:
    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError:
        log.error("pymodbus not installed — cannot write to Modbus.")
        return False

    regs = _encode_modbus_value(value, source.get("dataType", "float32"))
    if regs is None:
        log.error("Cannot encode value %r for type %s",
                  value, source.get("dataType"))
        return False
    client = ModbusTcpClient(source["host"], port=int(source["port"]),
                              timeout=2.0)
    try:
        if not client.connect():
            log.error("Modbus connect failed: %s:%s",
                      source["host"], source["port"])
            return False
        slave = int(source.get("slave_id", 1))
        addr  = int(source["register"])
        rr = client.write_registers(addr, regs, device_id=slave)
        if rr is None or rr.isError():
            log.error("Modbus write_registers reg=%d failed: %s", addr, rr)
            return False
        log.info("Modbus write OK reg=%d val=%s", addr, value)
        return True
    finally:
        client.close()

def write_mqtt(source: dict, value, mqtt_client) -> bool:
    topic = source.get("topic")
    if not topic or mqtt_client is None:
        return False
    payload = json.dumps({"value": value})
    mqtt_client.publish(topic, payload)
    log.info("MQTT publish %s: %s", topic, payload)
    return True

def write_opcua(source: dict, value) -> bool:
    server_url = source.get("server") or source.get("opcua_url", "")
    node_id    = source.get("node_id") or source.get("opcua_node_id", "")
    if not server_url or not node_id:
        log.error("OPC UA write: missing server/node_id in source %s", source)
        return False
    try:
        from asyncua.sync import Client as _SyncClient, ua
    except ImportError:
        log.error("asyncua not installed — cannot write to OPC UA.")
        return False
    try:
        with _SyncClient(url=server_url) as client:
            node = client.get_node(node_id)
            try:
                current = node.read_data_value().Value
                typed_value = type(current.Value)(value)
                dv = ua.DataValue(ua.Variant(typed_value, current.VariantType))
            except Exception:
                dv = ua.DataValue(ua.Variant(float(value), ua.VariantType.Float))
            node.write_value(dv)
        log.info("OPC UA write OK: %s %s = %s", server_url, node_id, value)
        return True
    except Exception as exc:
        log.error("OPC UA write %s %s failed: %s", server_url, node_id, exc)
        return False

def write_bacnet(source: dict, value) -> bool:
    host    = source.get("host", "")
    port    = source.get("port", 47808)
    obj_id  = source.get("object_id", "")
    prop_id = source.get("property_id", "presentValue")
    if not host or not obj_id:
        log.error("BACnet write: missing host/object_id in source %s", source)
        return False
    try:
        import asyncio, concurrent.futures
        async def _write():
            from bacpypes3.ipv4.app import NormalApplication
            from bacpypes3.app import DeviceObject
            from bacpypes3.pdu import Address
            from bacpypes3.primitivedata import Real
            device = DeviceObject(
                objectIdentifier=("device", 598),
                objectName="AASChangeListener",
                maxApduLengthAccepted=1024,
                segmentationSupported="noSegmentation",
            )
            async with NormalApplication(device, "0.0.0.0:0") as app:
                sep = ":" if ":" in obj_id else ","
                obj_type, obj_inst = obj_id.split(sep, 1)
                addr = Address(f"{host}:{port}")
                await app.write_property(
                    addr, (obj_type.strip(), int(obj_inst.strip())),
                    prop_id, Real(float(value)), priority=8,
                )
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            pool.submit(asyncio.run, _write()).result(timeout=8)
        log.info("BACnet write OK: %s:%s %s.%s = %s", host, port, obj_id, prop_id, value)
        return True
    except ImportError:
        log.error("bacpypes3 not installed — cannot write to BACnet")
        return False
    except Exception as exc:
        log.error("BACnet write %s:%s %s failed: %s", host, port, obj_id, exc)
        return False

_ocpp_write_proxy = None

def write_ocpp(source: dict, value) -> bool:
    if _ocpp_write_proxy is not None:
        try:
            _ocpp_write_proxy(source, value)
            return True
        except Exception as exc:
            log.error("OCPP write via proxy failed: %s", exc)
            return False
    log.warning("OCPP write: no proxy registered (DataBridge OCPP CS not started?)")
    return False

def write_dlms(source: dict, value) -> bool:
    host      = source.get("host", "")
    port      = source.get("port", 4059)
    obis      = source.get("obis_code", "")
    attribute = int(source.get("attribute", 2))
    if not host or not obis:
        log.error("DLMS write: missing host/obis_code in source %s", source)
        return False
    try:
        from gurux_dlms import GXDLMSClient, GXReplyData
        from gurux_net import GXNet, NetworkType
        from gurux_dlms.objects import GXDLMSData
        from gurux_dlms.enums import InterfaceType, Authentication
    except ImportError:
        log.error("gurux_dlms/gurux_net not installed — cannot write to DLMS")
        return False
    auth_map  = {"none": Authentication.NONE, "low": Authentication.LOW, "high": Authentication.HIGH}
    auth      = auth_map.get((source.get("auth_level") or "none").lower(), Authentication.NONE)
    media     = GXNet(NetworkType.TCP, host, int(port))
    client    = GXDLMSClient(True, int(source.get("client_id", 16)),
                              int(source.get("logical_device", 1) or 1),
                              auth, source.get("password") or None, InterfaceType.WRAPPER)
    try:
        media.open()
        reply = GXReplyData()
        for pdu in client.aareRequest():
            media.send(pdu)
        media.receive(reply)
        client.parseAareResponse(reply.data)
        reply.clear()
        obj = GXDLMSData(obis)
        obj.value = float(value)
        for pdu in client.write(obj, attribute):
            media.send(pdu)
            reply.clear()
            media.receive(reply)
        log.info("DLMS write OK: %s:%s OBIS=%s = %s", host, port, obis, value)
        return True
    except Exception as exc:
        log.error("DLMS write %s:%s OBIS=%s failed: %s", host, port, obis, exc)
        return False
    finally:
        try:
            for pdu in client.releaseRequest():
                media.send(pdu)
        except Exception:
            pass
        media.close()

def write_http(source: dict, value) -> bool:
    try:
        from http_auth_polling import _build_auth
    except Exception as exc:
        log.error("http_auth_polling unavailable: %s", exc)
        return False
    url = source.get("url")
    if not url:
        return False
    headers, qextra = _build_auth(source)
    headers.setdefault("Content-Type", "application/json")
    method = (source.get("write_method") or "PUT").upper()
    try:
        r = requests.request(method, url, headers=headers,
                              params=qextra or None,
                              json={"value": value}, timeout=5.0)
        if 200 <= r.status_code < 300:
            log.info("HTTP %s %s → %d", method, url, r.status_code)
            return True
        log.warning("HTTP %s %s → %d: %s",
                    method, url, r.status_code, r.text[:160])
    except Exception as exc:
        log.error("HTTP write %s %s failed: %s", method, url, exc)
    return False

class AASChangeListener:

    def __init__(self, write_routes: dict, aas_server_url: str,
                 mqtt_client) -> None:
        self.write_routes  = write_routes
        self.aas_server_url = aas_server_url.rstrip("/")
        self.mqtt_client   = mqtt_client
        self._lock         = threading.Lock()
        self.stats         = {
            "events_received":    0,
            "events_matched":     0,
            "writes_attempted":   0,
            "writes_succeeded":   0,
            "writes_failed":      0,
        }

    def subscribe(self) -> None:
        if self.mqtt_client is None:
            log.warning("No MQTT client available — write-back disabled.")
            return
        self.mqtt_client.message_callback_add(
            "sm-repository/+/submodels/+/submodelElements/+/updated",
            self._on_message,
        )
        self.mqtt_client.subscribe(
            "sm-repository/+/submodels/+/submodelElements/+/updated", qos=0)
        log.info("AAS change listener subscribed (write routes: %d)",
                 len(self.write_routes))

    def _on_message(self, _client, _userdata, msg) -> None:
        with self._lock:
            self.stats["events_received"] += 1
        parsed = parse_topic(msg.topic)
        if parsed is None:
            return
        sm_id, path = parsed
        route = self.write_routes.get((sm_id, path))
        if route is None:
            return
        with self._lock:
            self.stats["events_matched"] += 1

        new_value = self._fetch_value(sm_id, path)
        if new_value is None:
            log.warning("Could not fetch new value for %s.%s", sm_id, path)
            return

        ok = self._dispatch_write(route, new_value)
        with self._lock:
            self.stats["writes_attempted"] += 1
            self.stats["writes_succeeded" if ok else "writes_failed"] += 1
        log.info("[AAS→Device] %s.%s = %s → %s",
                 sm_id.split("/")[-1], path, new_value,
                 "OK" if ok else "FAIL")

    def _fetch_value(self, sm_id: str, path: str):
        try:
            enc = base64.urlsafe_b64encode(sm_id.encode()).decode().rstrip("=")
            url = (f"{self.aas_server_url}/submodels/{enc}/"
                   f"submodel-elements/{path}")
            r = requests.get(url, timeout=3.0)
            if r.status_code != 200:
                return None
            return r.json().get("value")
        except Exception as exc:
            log.warning("AAS GET %s failed: %s", path, exc)
            return None

    def _dispatch_write(self, route: dict, value) -> bool:
        proto = (route.get("protocol") or "").lower()
        src   = route.get("source") or route
        if proto == "modbus":
            return write_modbus(src, value)
        if proto == "mqtt":
            return write_mqtt(src, value, self.mqtt_client)
        if proto == "http":
            return write_http(src, value)
        if proto == "opcua":
            return write_opcua(src, value)
        if proto == "bacnet":
            return write_bacnet(src, value)
        if proto == "ocpp":
            return write_ocpp(src, value)
        if proto == "dlms":
            return write_dlms(src, value)
        log.warning("Unknown protocol for write-back: %s", proto)
        return False
