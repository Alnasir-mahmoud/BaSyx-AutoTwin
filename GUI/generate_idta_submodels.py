# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar


from __future__ import annotations

import argparse
import concurrent.futures
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import requests

_HERE = Path(__file__).resolve().parent
_CANDIDATE_ROOTS = [
    _HERE.parent,
    _HERE / "project_root",
    Path("/app/project_root"),
]
for _r in _CANDIDATE_ROOTS:
    if (_r / "validator").is_dir() and str(_r) not in sys.path:
        sys.path.insert(0, str(_r))
        _REPO_ROOT = _r
        break
else:
    _REPO_ROOT = _HERE.parent

from validator import IDTAValidator, validate_batch  # noqa: E402

_DEFAULT_ORCHESTRATOR_URL = os.environ.get(
    "ORCHESTRATOR_URL", "http://localhost:8085"
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import connection as _conn  # noqa: E402
from generate_configuration_offbasyx import (  # noqa: E402
    AAS_SERVER_URL,
    _encode,
    _get,
    extract_comm_config,
    get_all_shells,
    get_qualifiers,
    get_submodel,
    get_submodel_ids_for_shell,
    normalise_protocol,
    parse_polling,
    sanitize_id,
)

SID_AID_SUBMODEL = "https://admin-shell.io/idta/AssetInterfacesDescription/1/1/Submodel"
SID_AID_INTERFACE = "https://admin-shell.io/idta/AssetInterfacesDescription/1/1/Interface"
SID_AID_ENDPOINT_METADATA = "https://admin-shell.io/idta/AssetInterfacesDescription/1/1/EndpointMetadata"
SID_AID_INTERACTION_METADATA = "https://admin-shell.io/idta/AssetInterfacesDescription/1/1/InteractionMetadata"
SID_AID_PROPERTIES = "https://www.w3.org/2019/wot/td#properties"
SID_AID_TITLE = "https://www.w3.org/2019/wot/td#title"
SID_AID_BASE = "https://www.w3.org/2019/wot/td#base"
SID_AID_CONTENT_TYPE = "https://www.w3.org/2019/wot/hypermedia#forContentType"
SID_AID_SECURITY_DEFINITIONS = "https://www.w3.org/2019/wot/td#securityDefinitions"
SID_AID_SECURITY = "https://www.w3.org/2019/wot/td#security"

SID_AIMC_SUBMODEL = "https://admin-shell.io/idta/AssetInterfacesMappingConfiguration/1/0/Submodel"
SID_AIMC_MAPPING_CONFIGURATIONS = "https://admin-shell.io/idta/AssetInterfacesMappingConfiguration/1/0/MappingConfigurations"
SID_AIMC_MAPPING_CONFIGURATION = "https://admin-shell.io/idta/AssetInterfacesMappingConfiguration/1/0/MappingConfiguration"
SID_AIMC_INTERFACE_REFERENCE = "https://admin-shell.io/idta/AssetInterfacesMappingConfiguration/1/0/InterfaceReference"
SID_AIMC_MAPPING_RELATIONS = "https://admin-shell.io/idta/AssetInterfacesMappingConfiguration/1/0/MappingSourceSinkRelations"
SID_AIMC_MAPPING_RELATION = "https://admin-shell.io/idta/AssetInterfacesMappingConfiguration/1/0/MappingSourceSinkRelation"

SID_TS_SUBMODEL = "https://admin-shell.io/idta/TimeSeries/1/1"
SID_TS_METADATA = "https://admin-shell.io/idta/TimeSeries/Metadata/1/1"
SID_TS_NAME = "https://admin-shell.io/idta/TimeSeries/Metadata/Name/1/1"
SID_TS_DESCRIPTION = "https://admin-shell.io/idta/TimeSeries/Metadata/Description/1/1"
SID_TS_RECORD = "https://admin-shell.io/idta/TimeSeries/Record/1/1"
SID_TS_TIME = "https://admin-shell.io/idta/TimeSeries/RelativePointInTime/1/1"
SID_TS_SEGMENTS = "https://admin-shell.io/idta/TimeSeries/Segments/1/1"
SID_TS_LINKED_SEGMENT = "https://admin-shell.io/idta/TimeSeries/LinkedSegment/1/1"
SID_TS_ENDPOINT = "https://admin-shell.io/idta/TimeSeries/Endpoint/1/1"
SID_TS_QUERY = "https://admin-shell.io/idta/TimeSeries/Query/1/1"
SID_TS_START_TIME = "https://admin-shell.io/idta/TimeSeries/StartTime/1/1"

_TMPL_BASE = (
    _REPO_ROOT / "IDTA-Templates" / "submodel-templates" / "published"
)
_TMPL_FILES = {
    "aid":  (_TMPL_BASE / "Asset Interfaces Description"           / "1" / "1"
             / "IDTA 02017-1-1_Template_Asset Interfaces Description.json"),
    "aimc": (_TMPL_BASE / "Asset Interfaces Mapping Configuration" / "1" / "0"
             / "IDTA 02027-1-0_Template_AIMC .json"),
    "ts":   (_TMPL_BASE / "Time Series Data"                       / "1" / "1"
             / "IDTA 02008-1-1_Template_TimeSeriesData.json"),
}
_PROTOCOL_TMPL_NAME = {
    "modbus": "InterfaceTemplateForMODBUS",
    "mqtt":   "InterfaceTemplateForMQTT",
    "http":   "InterfaceTemplateForHTTP",
    "opcua":  "InterfaceTemplateForOPCUA",
    "kafka":  "InterfaceTemplateForHTTP",
    "bacnet": "InterfaceTemplateForBacnet",
    "ocpp":   "InterfaceTemplateForHTTP",
    "dlms":   "InterfaceTemplateForHTTP",
}

_tmpl_cache: dict[str, dict] = {}

def _load_template(name: str) -> dict | None:
    if name in _tmpl_cache:
        return _tmpl_cache[name]
    path = _TMPL_FILES.get(name)
    if not path or not path.exists():
        print(f"[TMPL] Template file not found: {path}", flush=True)
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    sm = data.get("submodels", [{}])[0]
    _tmpl_cache[name] = sm
    return sm

def _find_el(elements: list, id_short: str) -> dict | None:
    for el in elements:
        if isinstance(el, dict) and el.get("idShort") == id_short:
            return el
    return None

def _set_val(elements: list, id_short: str, value: str) -> None:
    el = _find_el(elements, id_short)
    if el is not None:
        el["value"] = value

def _strip_cardinality(el: dict) -> dict:
    qs = [q for q in el.get("qualifiers", [])
          if q.get("type") != "Cardinality"]
    if qs:
        el["qualifiers"] = qs
    else:
        el.pop("qualifiers", None)
    return el

def _clone(el: dict) -> dict:
    return copy.deepcopy(el)

def _ext_ref(iri: str) -> dict:
    return {
        "type": "ExternalReference",
        "keys": [{"type": "GlobalReference", "value": iri}],
    }

def _model_ref_submodel(iri: str) -> dict:
    return {
        "type": "ModelReference",
        "keys": [{"type": "Submodel", "value": iri}],
    }

def _cardinality_qualifier(value: str) -> dict:
    return {
        "type": "Cardinality",
        "valueType": "xs:string",
        "value": value,
    }

def _prop(id_short: str, value: Any, value_type: str, sid: str | None = None,
          extra_qualifiers: list[dict] | None = None) -> dict:
    el: dict[str, Any] = {
        "idShort": id_short,
        "valueType": value_type,
        "value": str(value) if value is not None else "",
        "modelType": "Property",
    }
    if sid:
        el["semanticId"] = _ext_ref(sid)
    qs = list(extra_qualifiers or [])
    if qs:
        el["qualifiers"] = qs
    return el

def _smc(id_short: str, children: list[dict],
         sid: str | None = None) -> dict:
    el: dict[str, Any] = {
        "idShort": id_short,
        "value": children,
        "modelType": "SubmodelElementCollection",
    }
    if sid:
        el["semanticId"] = _ext_ref(sid)
    return el

def _sml(id_short: str, items: list[dict],
         sid: str | None, item_sid: str | None = None,
         type_value: str = "SubmodelElementCollection") -> dict:
    el: dict[str, Any] = {
        "idShort": id_short,
        "orderRelevant": True,
        "typeValueListElement": type_value,
        "value": items,
        "modelType": "SubmodelElementList",
    }
    if sid:
        el["semanticId"] = _ext_ref(sid)
    if item_sid:
        el["semanticIdListElement"] = _ext_ref(item_sid)
    return el

def _ref_element(id_short: str, target_iri: str,
                 sid: str | None = None) -> dict:
    el: dict[str, Any] = {
        "idShort": id_short,
        "value": _ext_ref(target_iri),
        "modelType": "ReferenceElement",
    }
    if sid:
        el["semanticId"] = _ext_ref(sid)
    return el

def _model_ref_path(sm_id: str, *id_shorts: str) -> dict:
    keys = [{"type": "Submodel", "value": sm_id}]
    for seg in id_shorts:
        keys.append({"type": "SubmodelElementCollection", "value": seg})
    return {"type": "ModelReference", "keys": keys}

def _relationship_element(id_short: str, first_sm_id: str, first_path: list[str],
                          second_sm_id: str, second_path: list[str],
                          sid: str | None = None) -> dict:
    el: dict[str, Any] = {
        "idShort": id_short,
        "first":  _model_ref_path(first_sm_id,  *first_path),
        "second": _model_ref_path(second_sm_id, *second_path),
        "modelType": "RelationshipElement",
    }
    if sid:
        el["semanticId"] = _ext_ref(sid)
    return el

class DataPoint:
    __slots__ = ("id_short", "quals", "value_type", "description", "semantic_id")

    def __init__(self, id_short: str, quals: dict[str, str],
                 value_type: str, description: str = "",
                 semantic_id: str = "") -> None:
        self.id_short = id_short
        self.quals = quals
        self.value_type = value_type or "xs:float"
        self.description = description or ""
        self.semantic_id = semantic_id or ""

class InterfaceBlock:

    def __init__(self, sm_id: str, sm_label: str, suffix: str,
                 protocol: str, comm_cfg: dict[str, str],
                 polling_ms: int, data_points: list[DataPoint]) -> None:
        self.sm_id = sm_id
        self.sm_label = sm_label
        self.suffix = suffix
        self.protocol = protocol
        self.comm_cfg = comm_cfg
        self.polling_ms = polling_ms
        self.data_points = data_points

    @property
    def title(self) -> str:
        suf = f"_{self.suffix}" if self.suffix else ""
        return f"{self.sm_label}{suf}_{self.protocol}"

class AssetContext:

    def __init__(self, shell: dict) -> None:
        self.shell = shell
        self.shell_id: str = shell.get("id", "")
        self.asset_name: str = shell.get("idShort", "Asset")
        self.interfaces: list[InterfaceBlock] = []
        self.influx_cfg: dict | None = None

PROTOCOL_QUALIFIER_HINTS: dict[str, tuple[str, ...]] = {
    "modbus": ("ModbusRegister", "ModbusDataType"),
    "mqtt":   ("MqttTopic",),
    "opcua":  ("OpcuaNodeId",),
    "http":   ("HttpJsonPath", "HttpMethod"),
}

PROTOCOL_DEFAULT_ENDPOINT: dict[str, dict[str, str]] = {
    "modbus": {"Host": "thies-proxy", "Port": "502", "SlaveID": "1"},
    "mqtt":   {"Host": "mosquitto",   "Port": "1883"},
    "opcua":  {"Host": "ext-simulator", "Port": "4840"},
    "http":   {"Host": "ext-simulator", "Port": "8082"},
}

ASSET_ENDPOINT_DEFAULTS: dict[str, dict[str, str]] = {
    "ThiesClimaSensorUS": {
        "Host": "thies-proxy", "Port": "502", "SlaveID": "1",
        "PollingInterval": "5000",
    },
    "BuildingSimulator": {
        "Host": "ext-simulator", "Port": "5020", "SlaveID": "1",
        "PollingInterval": "1000",
    },
}

def _detect_protocol_from_property(prop: dict) -> str | None:
    quals = get_qualifiers(prop)
    for proto, hints in PROTOCOL_QUALIFIER_HINTS.items():
        if any(h in quals for h in hints):
            return proto
    return None

def _extract_description(prop: dict) -> str:
    desc_list = prop.get("description") or []
    if not desc_list:
        return ""
    en = next((d for d in desc_list if d.get("language") == "en"), None)
    return ((en or desc_list[0]).get("text") or "").strip()

def _extract_semantic_id(prop: dict) -> str:
    sid = prop.get("semanticId") or {}
    keys = sid.get("keys") or []
    return (keys[0].get("value") or "").strip() if keys else ""

def _flat_interfaces(
    asset_name: str, sm_id: str, sm_label: str,
    flat_props: list[dict],
) -> list[InterfaceBlock]:
    by_proto: dict[str, list[DataPoint]] = {}
    for prop in flat_props:
        id_s = prop.get("idShort")
        if not id_s:
            continue
        proto = _detect_protocol_from_property(prop)
        if not proto:
            continue
        by_proto.setdefault(proto, []).append(DataPoint(
            id_short=id_s,
            quals=get_qualifiers(prop),
            value_type=prop.get("valueType", "xs:float"),
            description=_extract_description(prop),
            semantic_id=_extract_semantic_id(prop),
        ))

    interfaces: list[InterfaceBlock] = []
    for proto, points in by_proto.items():
        cfg = dict(PROTOCOL_DEFAULT_ENDPOINT.get(proto, {}))
        cfg.update(ASSET_ENDPOINT_DEFAULTS.get(asset_name, {}))
        cfg.setdefault("Protocol", proto)
        polling = parse_polling(cfg.get("PollingInterval"))
        interfaces.append(InterfaceBlock(
            sm_id=sm_id, sm_label=sm_label, suffix="",
            protocol=proto, comm_cfg=cfg,
            polling_ms=polling, data_points=points,
        ))
    return interfaces

def _parse_submodel_into_interfaces(
    sm_data: dict, sm_id: str
) -> tuple[str, list[dict], list[dict]]:
    sm_label = sm_data.get("idShort", sm_id.split("/")[-1])
    elements = sm_data.get("submodelElements", []) or []

    comm_map: dict[str, dict] = {}
    dp_map:   dict[str, dict] = {}
    flat_props: list[dict] = []
    _PROTO_NAMES = {"modbus", "mqtt", "http", "opcua", "kafka"}

    for el in elements:
        id_s       = el.get("idShort", "")
        model_type = el.get("modelType", "")
        if (id_s.lower() in _PROTO_NAMES
                and "SubmodelElementCollection" in model_type):
            children   = el.get("value", []) or []
            conn_child = next(
                (c for c in children if c.get("idShort") == "Connection"), None)
            dp_child   = next(
                (c for c in children if c.get("idShort") == "DataPoints"),  None)
            if conn_child:
                comm_map[id_s.lower()] = conn_child
            if dp_child:
                dp_map[id_s.lower()]   = dp_child
        elif id_s.startswith("CommunicationConfiguration"):
            comm_map[id_s[len("CommunicationConfiguration"):]] = el
        elif id_s.startswith("DataPoints"):
            dp_map[id_s[len("DataPoints"):]] = el
        elif model_type == "Property":
            flat_props.append(el)

    return sm_label, comm_map, dp_map, flat_props

def scan_assets(server: str, wait_seconds: int = 15) -> list[AssetContext]:
    shells: list[dict] = []
    for attempt in range(max(1, wait_seconds // 2)):
        shells = get_all_shells(server)
        if shells:
            break
        print(f"  [wait] AAS server not ready yet (attempt {attempt + 1})",
              flush=True)
        time.sleep(2)
    if not shells:
        print("[scan] No shells found on AAS server.", flush=True)
        return []

    def _fetch_submodel(sm_id: str) -> dict:
        return get_submodel(server, sm_id) or {}

    def _process_shell(shell: dict) -> AssetContext | None:
        ctx    = AssetContext(shell)
        sm_ids = get_submodel_ids_for_shell(server, ctx.shell_id)
        if not sm_ids:
            return None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(sm_ids), 8)
        ) as pool:
            sm_datas = list(pool.map(_fetch_submodel, sm_ids))

        for sm_id, sm_data in zip(sm_ids, sm_datas):
            if not sm_data.get("submodelElements"):
                continue

            if ctx.influx_cfg is None:
                for _el in sm_data.get("submodelElements", []) or []:
                    if (_el.get("idShort") == "DataSinks"
                            and "Collection" in _el.get("modelType", "")):
                        for _sink in _el.get("value", []) or []:
                            if _sink.get("idShort") == "InfluxDB":
                                _p = {c["idShort"]: c.get("value", "")
                                      for c in _sink.get("value", []) or []
                                      if c.get("idShort")}
                                if _p.get("ServerUrl"):
                                    ctx.influx_cfg = {
                                        "InfluxServerUrl": _p.get("ServerUrl", ""),
                                        "InfluxOrg":       _p.get("Org", ""),
                                        "InfluxBucket":    _p.get("Bucket", ""),
                                        "InfluxToken":     _p.get("Token", ""),
                                    }
                                break
                        break

            sm_label, comm_map, dp_map, flat_props = \
                _parse_submodel_into_interfaces(sm_data, sm_id)

            if comm_map:
                for suffix, dp_smc in dp_map.items():
                    comm = comm_map.get(suffix) or comm_map.get("")
                    if not comm:
                        continue
                    comm_cfg = extract_comm_config(comm)
                    protocol = normalise_protocol(comm_cfg.get("Protocol", ""))
                    if not protocol:
                        continue
                    polling = parse_polling(comm_cfg.get("PollingInterval"))
                    points: list[DataPoint] = []
                    for prop in dp_smc.get("value", []) or []:
                        ps = prop.get("idShort")
                        if not ps:
                            continue
                        if "SubmodelElementCollection" in prop.get("modelType", ""):
                            value_child = next(
                                (c for c in prop.get("value", []) or []
                                 if c.get("idShort") == "Value"),
                                None,
                            )
                            if value_child is None:
                                continue
                            points.append(DataPoint(
                                id_short=ps,
                                quals=get_qualifiers(value_child),
                                value_type=value_child.get("valueType", "xs:float"),
                                description=_extract_description(value_child),
                                semantic_id=_extract_semantic_id(value_child),
                            ))
                        else:
                            points.append(DataPoint(
                                id_short=ps,
                                quals=get_qualifiers(prop),
                                value_type=prop.get("valueType", "xs:float"),
                                description=_extract_description(prop),
                                semantic_id=_extract_semantic_id(prop),
                            ))
                    if not points:
                        continue
                    ctx.interfaces.append(InterfaceBlock(
                        sm_id=sm_id, sm_label=sm_label, suffix=suffix,
                        protocol=protocol, comm_cfg=comm_cfg,
                        polling_ms=polling, data_points=points,
                    ))
            elif flat_props:
                ctx.interfaces.extend(
                    _flat_interfaces(ctx.asset_name, sm_id, sm_label, flat_props)
                )

        return ctx if ctx.interfaces else None

    assets: list[AssetContext] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(len(shells), 4)
    ) as pool:
        for ctx in pool.map(_process_shell, shells):
            if ctx is not None:
                assets.append(ctx)
    return assets

def _interface_id(asset_name: str, iface: InterfaceBlock) -> str:
    suf = f"_{iface.suffix}" if iface.suffix else ""
    return f"{sanitize_id(asset_name)}_{sanitize_id(iface.sm_label)}{suf}_{iface.protocol}"

def _base_url(iface: InterfaceBlock) -> str:
    host = iface.comm_cfg.get("Host", "localhost")
    port = iface.comm_cfg.get("Port", "")
    if iface.protocol == "mqtt":
        return f"mqtt://{host}:{port or '1883'}"
    if iface.protocol == "http":
        return f"http://{host}:{port or '80'}"
    if iface.protocol == "opcua":
        return f"opc.tcp://{host}:{port or '4840'}"
    if iface.protocol == "modbus":
        slave = iface.comm_cfg.get("SlaveID", "1")
        return f"modbus+tcp://{host}:{port or '502'}/{slave}"
    if iface.protocol == "kafka":
        return f"kafka://{host}:{port or '9092'}"
    if iface.protocol == "bacnet":
        device = iface.comm_cfg.get("DeviceInstance", "0")
        return f"bacnet://{host}:{port or '47808'}/device/{device}"
    if iface.protocol == "ocpp":
        server = iface.comm_cfg.get("ServerURL", f"ws://{host}:9000")
        return server
    if iface.protocol == "dlms":
        return f"dlms://{host}:{port or '4059'}"
    return f"{iface.protocol}://{host}:{port}"

def _protocol_form_items(iface: InterfaceBlock, dp: DataPoint) -> list[dict]:
    items: list[dict] = []
    if iface.protocol == "modbus":
        reg = dp.quals.get("ModbusRegister", "")
        dtype = dp.quals.get("ModbusDataType") or dp.quals.get("DataType", "")
        try:
            reg_num = int(reg)
        except (ValueError, TypeError):
            reg_num = 0
        modv_fn = "readInputRegisters" if 30001 <= reg_num <= 39999 else "readHoldingRegisters"
        items.append(_prop("href", f"/register/{reg}", "xs:string"))
        items.append(_prop("contentType", "application/octet-stream",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
        items.append(_prop("modv_function", modv_fn, "xs:string"))
        if reg:
            items.append(_prop("modv_address", reg, "xs:string"))
        if dtype:
            items.append(_prop("modv_type", dtype, "xs:string"))
    elif iface.protocol == "mqtt":
        topic = dp.quals.get("MqttTopic", f"{iface.title}/{dp.id_short}")
        items.append(_prop("href", topic, "xs:string"))
        items.append(_prop("contentType", "application/json",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
        items.append(_prop("mqv_qos", dp.quals.get("MqttQos", "0"), "xs:string"))
    elif iface.protocol == "http":
        path = dp.quals.get("HttpPath", f"/{dp.id_short}")
        items.append(_prop("href", path, "xs:string"))
        items.append(_prop("contentType", "application/json",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
        items.append(_prop("htv_methodName",
                           dp.quals.get("HttpMethod", "GET"), "xs:string"))
    elif iface.protocol == "opcua":
        node = dp.quals.get("OpcuaNodeId") or dp.quals.get("OpcUaNodeId") or dp.id_short
        items.append(_prop("href", node, "xs:string"))
        items.append(_prop("contentType", "application/json",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
    elif iface.protocol == "bacnet":
        obj_id   = dp.quals.get("BACnetObjectId", dp.id_short)
        prop_id  = dp.quals.get("BACnetPropertyId", "PresentValue")
        device   = iface.comm_cfg.get("DeviceInstance", "0")
        items.append(_prop("href", f"/device/{device}/{obj_id}/{prop_id}", "xs:string"))
        items.append(_prop("contentType", "application/json",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
        items.append(_prop("bacv_useService", "ReadProperty", "xs:string"))
        items.append(_prop("bacv_objectId", obj_id, "xs:string"))
        items.append(_prop("bacv_propertyId", prop_id, "xs:string"))
    elif iface.protocol == "ocpp":
        measurand = dp.quals.get("OCPPMeasurand", dp.id_short)
        phase     = dp.quals.get("OCPPPhase", "")
        cp_id     = iface.comm_cfg.get("ChargePointId", "CP001")
        href      = f"/api/metervalues/{cp_id}/{measurand}"
        if phase:
            href += f"/{phase}"
        items.append(_prop("href", href, "xs:string"))
        items.append(_prop("contentType", "application/json",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
        items.append(_prop("htv_methodName", "GET", "xs:string"))
    elif iface.protocol == "dlms":
        obis      = dp.quals.get("DLMSObisCode", dp.id_short)
        attribute = dp.quals.get("DLMSAttribute", "2")
        items.append(_prop("href", f"/{obis}/{attribute}", "xs:string"))
        items.append(_prop("contentType", "application/json",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
    else:
        items.append(_prop("href", dp.id_short, "xs:string"))
        items.append(_prop("contentType", "application/json",
                           "xs:string", sid=SID_AID_CONTENT_TYPE))
    return items

def build_aid_submodel(asset: AssetContext) -> dict:
    tmpl_sm = _load_template("aid")
    interfaces: list[dict] = []

    for iface in asset.interfaces:
        iface_id = _interface_id(asset.asset_name, iface)
        tmpl_name = _PROTOCOL_TMPL_NAME.get(iface.protocol, "InterfaceTemplateForHTTP")

        if tmpl_sm:
            iface_el = _clone(_find_el(tmpl_sm["submodelElements"], tmpl_name)
                              or tmpl_sm["submodelElements"][0])
        else:
            iface_el = _smc(iface_id, [], sid=SID_AID_INTERFACE)

        _strip_cardinality(iface_el)
        iface_el["idShort"] = iface_id

        children = iface_el.setdefault("value", [])

        _set_val(children, "title", iface.title)

        ep = _find_el(children, "EndpointMetadata")
        if ep:
            ep_ch = ep.setdefault("value", [])
            _set_val(ep_ch, "base", _base_url(iface))
            if iface.protocol == "modbus":
                _set_val(ep_ch, "modv_mostSignificantByte", "true")
                _set_val(ep_ch, "modv_mostSignificantWord", "true")

        im = _find_el(children, "InteractionMetadata")
        if im:
            props_el = _find_el(im.setdefault("value", []), "properties")
            if props_el:
                prop_tmpl = _find_el(props_el.get("value", []), "property_name")
                dp_entries: list[dict] = []
                for dp in iface.data_points:
                    if prop_tmpl:
                        dp_el = _clone(prop_tmpl)
                    else:
                        dp_el = _smc(dp.id_short, [])
                    _strip_cardinality(dp_el)
                    dp_el["idShort"] = dp.id_short

                    dp_ch = dp_el.setdefault("value", [])
                    _set_val(dp_ch, "type", "number")
                    _set_val(dp_ch, "observable", "true")
                    unit = dp.quals.get("Unit")
                    if unit:
                        _set_val(dp_ch, "unit", unit)
                    if dp.description:
                        _set_val(dp_ch, "description", dp.description)
                    if dp.semantic_id:
                        dp_el["semanticId"] = _ext_ref(dp.semantic_id)

                    forms_el = _find_el(dp_ch, "forms")
                    form_items = _protocol_form_items(iface, dp)
                    if forms_el is not None:
                        existing_sec = _find_el(
                            forms_el.get("value", []), "security")
                        forms_el["value"] = form_items
                        if existing_sec:
                            forms_el["value"].append(existing_sec)
                    else:
                        forms_el = _smc("forms", form_items + [{
                            "idShort": "security",
                            "modelType": "SubmodelElementList",
                            "typeValueListElement": "ReferenceElement",
                            "orderRelevant": True,
                            "value": [],
                        }])
                        dp_ch.append(forms_el)
                    dp_entries.append(dp_el)
                props_el["value"] = dp_entries

        interfaces.append(iface_el)

    if tmpl_sm:
        sm = _clone(tmpl_sm)
        sm.pop("kind", None)
    else:
        sm = {"modelType": "Submodel",
              "semanticId": _ext_ref(SID_AID_SUBMODEL),
              "administration": {"version": "1", "revision": "1"}}

    asset_safe = sanitize_id(asset.asset_name)
    sm["idShort"] = f"AssetInterfacesDescription_{asset_safe}"
    sm["id"]      = f"https://example.com/sm/aid/{asset_safe}"
    sm["submodelElements"] = interfaces
    return sm

def build_aimc_submodel(asset: AssetContext,
                        aid_submodel_id: str) -> dict:
    tmpl_sm = _load_template("aimc")

    mapping_entries: list[dict] = []
    for iface in asset.interfaces:
        iface_id  = _interface_id(asset.asset_name, iface)
        dp_smc_id = f"DataPoints{iface.suffix or ''}"

        relations: list[dict] = []
        for dp in iface.data_points:
            relations.append(_relationship_element(
                dp.id_short,
                aid_submodel_id,
                [iface_id, "InteractionMetadata", "properties", dp.id_short],
                iface.sm_id,
                [dp_smc_id, dp.id_short, "Value"],
                sid=SID_AIMC_MAPPING_RELATION,
            ))

        if tmpl_sm:
            mc_list = _find_el(tmpl_sm.get("submodelElements", []),
                               "MappingConfigurations")
            mc_tmpl = ((_find_el(mc_list.get("value", []),
                                 mc_list["value"][0].get("idShort", ""))
                        if mc_list and mc_list.get("value") else None))
            if mc_tmpl:
                mc_el = _clone(mc_tmpl)
                _strip_cardinality(mc_el)
                mc_el["idShort"] = f"Mapping_{iface_id}"
                mc_ch = mc_el.setdefault("value", [])
                ir = _find_el(mc_ch, "InterfaceReference")
                if ir:
                    ir["value"] = _model_ref_path(aid_submodel_id, iface_id)
                else:
                    mc_ch.insert(0, {
                        "idShort":    "InterfaceReference",
                        "semanticId": _ext_ref(SID_AIMC_INTERFACE_REFERENCE),
                        "value":      _model_ref_path(aid_submodel_id, iface_id),
                        "modelType":  "ReferenceElement",
                    })
                rel_sml = _find_el(mc_ch, "MappingSourceSinkRelations")
                if rel_sml:
                    rel_sml["value"] = relations
                else:
                    mc_ch.append(_sml("MappingSourceSinkRelations", relations,
                                      sid=SID_AIMC_MAPPING_RELATIONS,
                                      item_sid=SID_AIMC_MAPPING_RELATION,
                                      type_value="RelationshipElement"))
                mapping_entries.append(mc_el)
                continue

        mapping_entries.append(_smc(
            f"Mapping_{iface_id}",
            [
                {"idShort": "InterfaceReference",
                 "semanticId": _ext_ref(SID_AIMC_INTERFACE_REFERENCE),
                 "value": _model_ref_path(aid_submodel_id, iface_id),
                 "modelType": "ReferenceElement"},
                _sml("MappingSourceSinkRelations", relations,
                     sid=SID_AIMC_MAPPING_RELATIONS,
                     item_sid=SID_AIMC_MAPPING_RELATION,
                     type_value="RelationshipElement"),
            ],
            sid=SID_AIMC_MAPPING_CONFIGURATION,
        ))

    if tmpl_sm:
        sm = _clone(tmpl_sm)
        sm.pop("kind", None)
        mc_sml = _find_el(sm.setdefault("submodelElements", []),
                          "MappingConfigurations")
        if mc_sml:
            mc_sml["value"] = mapping_entries
        else:
            sm["submodelElements"] = [
                _sml("MappingConfigurations", mapping_entries,
                     sid=SID_AIMC_MAPPING_CONFIGURATIONS,
                     item_sid=SID_AIMC_MAPPING_CONFIGURATION,
                     type_value="SubmodelElementCollection")
            ]
    else:
        sm = {"modelType": "Submodel",
              "semanticId": _ext_ref(SID_AIMC_SUBMODEL),
              "submodelElements": [
                  _sml("MappingConfigurations", mapping_entries,
                       sid=SID_AIMC_MAPPING_CONFIGURATIONS,
                       item_sid=SID_AIMC_MAPPING_CONFIGURATION,
                       type_value="SubmodelElementCollection")
              ]}

    asset_safe = sanitize_id(asset.asset_name)
    sm["idShort"] = f"AssetInterfacesMappingConfiguration_{asset_safe}"
    sm["id"]      = f"https://example.com/sm/aimc/{asset_safe}"
    return sm

def _first_influx_config(asset: AssetContext) -> dict[str, str] | None:
    for iface in asset.interfaces:
        for dp in iface.data_points:
            if all(k in dp.quals for k in (
                "InfluxServerUrl", "InfluxOrg", "InfluxBucket",
            )):
                return dp.quals
    return None

def _influx_from_datasinks() -> dict[str, str] | None:
    path = _REPO_ROOT / "CustomDatabridge" / "datasinks.json"
    try:
        sinks = json.loads(path.read_text(encoding="utf-8"))
        for sink in sinks:
            if sink.get("enable_influx"):
                return {
                    "InfluxServerUrl": sink.get("influx_endpoint", ""),
                    "InfluxOrg":       sink.get("influx_org", ""),
                    "InfluxBucket":    sink.get("influx_database", ""),
                    "InfluxToken":     sink.get("influx_token", ""),
                    "InfluxUser":      sink.get("influx_user", "admin"),
                    "InfluxPassword":  sink.get("influx_password", "influxpassword"),
                }
    except Exception:
        pass
    return None

def build_timeseries_submodel(asset: AssetContext) -> dict:
    tmpl_sm = _load_template("ts")

    if tmpl_sm:
        sm = _clone(tmpl_sm)
        sm.pop("kind", None)
        elements = sm.setdefault("submodelElements", [])
    else:
        sm = {"modelType": "Submodel", "semanticId": _ext_ref(SID_TS_SUBMODEL)}
        elements = []
        sm["submodelElements"] = elements

    meta = _find_el(elements, "Metadata")
    if meta is None:
        meta = _smc("Metadata", [], sid=SID_TS_METADATA)
        elements.insert(0, meta)
    meta_ch = meta.setdefault("value", [])

    name_el = _find_el(meta_ch, "Name")
    if name_el:
        name_el["value"] = [{"language": "en",
                             "text": f"{asset.asset_name} operational data"}]
    else:
        meta_ch.insert(0, {"idShort": "Name",
                            "semanticId": _ext_ref(SID_TS_NAME),
                            "value": [{"language": "en",
                                       "text": f"{asset.asset_name} operational data"}],
                            "modelType": "MultiLanguageProperty"})

    record_tmpl = _find_el(meta_ch, "Record")
    if record_tmpl:
        record_el = record_tmpl
    else:
        record_el = _smc("Record", [], sid=SID_TS_RECORD)
        meta_ch.append(record_el)

    added: set[str] = set()
    record_children: list[dict] = [_prop(
        "Time", "0", "xs:long", sid=SID_TS_TIME,
        extra_qualifiers=[_cardinality_qualifier("OneToMany")],
    )]
    for iface in asset.interfaces:
        for dp in iface.data_points:
            if dp.id_short in added:
                continue
            record_children.append(_prop(
                dp.id_short, "", dp.value_type,
                extra_qualifiers=[_cardinality_qualifier("ZeroToMany")],
            ))
            added.add(dp.id_short)
    record_el["value"] = record_children

    segs = _find_el(elements, "Segments")
    if segs is None:
        segs = _smc("Segments", [], sid=SID_TS_SEGMENTS)
        elements.append(segs)

    influx = (_first_influx_config(asset)
              or asset.influx_cfg
              or _influx_from_datasinks())

    linked_tmpl = _find_el(segs.get("value", []), "LinkedSegment")
    if linked_tmpl:
        linked = linked_tmpl
    else:
        linked = _smc("LinkedSegment", [], sid=SID_TS_LINKED_SEGMENT)
    segs["value"] = [linked]

    linked_ch = linked.setdefault("value", [])

    name_el = _find_el(linked_ch, "Name")
    if name_el:
        name_el["value"] = [{"language": "en",
                              "text": f"{asset.asset_name} linked segment"}]
    else:
        linked_ch.insert(0, {
            "idShort": "Name", "modelType": "MultiLanguageProperty",
            "semanticId": _ext_ref(SID_TS_NAME),
            "value": [{"language": "en",
                        "text": f"{asset.asset_name} linked segment"}],
        })

    st_el = _find_el(linked_ch, "StartTime")
    if st_el:
        st_el["value"] = "1970-01-01T00:00:00Z"
    else:
        linked_ch.append(_prop("StartTime", "1970-01-01T00:00:00Z",
                               "xs:dateTime", sid=SID_TS_START_TIME))

    if influx:
        bucket      = influx.get("InfluxBucket", "hems")
        influx_org  = influx.get("InfluxOrg", "basyx")
        _gui_url = os.environ.get("GUI_URL", "")
        if _gui_url:
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(_gui_url)
            ext_host = _parsed.hostname or "localhost"
        else:
            ext_host = (os.environ.get("HOST_IP") or
                        _conn.load().get("host") or "localhost")
        ui_port  = os.environ.get("BASYX_UI_PORT", "3000")
        endpoint_val = (f"http://{ext_host}:{ui_port}/influxdb"
                        f"/api/v2/query?org={influx_org}")
        query = (
            f'from(bucket: "{bucket}")\n'
            f'  |> range(start: -1h)\n'
            f'  |> filter(fn: (r) => r._field == "value")\n'
            f'  |> map(fn: (r) => ({{r with topic: r._measurement}}))'
        )
    else:
        endpoint_val, query = "", ""

    for fid, fval, fsid in [("Endpoint", endpoint_val, SID_TS_ENDPOINT),
                             ("Query",    query,         SID_TS_QUERY)]:
        el = _find_el(linked_ch, fid)
        if el:
            el["value"] = fval
        else:
            linked_ch.append(_prop(fid, fval, "xs:string", sid=fsid))

    asset_safe = sanitize_id(asset.asset_name)
    sm["idShort"] = f"TimeSeries_{asset_safe}"
    sm["id"]      = f"https://example.com/sm/timeseries/{asset_safe}"
    submodel = sm
    return submodel

def upload_submodel(server: str, submodel: dict, retries: int = 3) -> bool:
    sm_id = submodel["id"]
    enc = _encode(sm_id)
    put_url = f"{server}/submodels/{enc}"
    post_url = f"{server}/submodels"
    last_err: str = ""
    for attempt in range(retries):
        if attempt:
            time.sleep(attempt)
        try:
            r = requests.put(put_url, json=submodel, timeout=15)
            if r.status_code in (200, 201, 204):
                return True
            r = requests.post(post_url, json=submodel, timeout=15)
            if r.status_code in (200, 201, 204, 409):
                return True
            last_err = f"HTTP {r.status_code} — {r.text[:200]}"
        except Exception as e:
            last_err = str(e)
    print(f"  [upload] {sm_id}: {last_err}", flush=True)
    return False

def attach_submodels_to_shell(server: str, shell: dict,
                              submodel_ids: list[str]) -> bool:
    shell_id = shell.get("id")
    if not shell_id:
        return False
    enc = _encode(shell_id)
    shell_url = f"{server}/shells/{enc}"
    current = _get(shell_url)
    if not current:
        return False
    refs = list(current.get("submodels") or [])
    existing = {
        k.get("value")
        for r in refs
        for k in (r.get("keys") or [])
    }
    added = 0
    for sm_id in submodel_ids:
        if sm_id not in existing:
            refs.append(_model_ref_submodel(sm_id))
            added += 1
    if added == 0:
        return True
    current["submodels"] = refs
    try:
        r = requests.put(shell_url, json=current, timeout=15)
        return r.status_code in (200, 201, 204)
    except Exception as e:
        print(f"  [attach] {shell_id}: {e}", flush=True)
        return False

def generate_and_upload(
    server: str,
    dry_run: bool = False,
    print_json: bool = False,
    orchestrator_url: str | None = None,  # noqa: ARG001 — kept for API compat
) -> dict[str, Any]:
    t0 = time.time()
    print(f"[idta] Scanning AAS server: {server}", flush=True)
    assets = scan_assets(server)
    if not assets:
        print("[idta] No qualifier-annotated assets found.", flush=True)
        return {"assets": 0, "generated": 0, "uploaded": 0, "validation": {}}
    print(f"[idta] Scan done in {time.time()-t0:.1f}s, "
          f"{len(assets)} asset(s) found.", flush=True)

    typed_submodels: list[tuple[dict, str]] = []
    uploaded = 0
    generated = 0

    for asset in assets:
        print(f"[idta] Asset: {asset.asset_name} "
              f"(interfaces={len(asset.interfaces)})", flush=True)
        aid  = build_aid_submodel(asset)
        aimc = build_aimc_submodel(asset, aid_submodel_id=aid["id"])
        ts   = build_timeseries_submodel(asset)

        generated += 3
        typed_submodels.extend([(aid, "AID"), (aimc, "AIMC"), (ts, "TimeSeries")])

        if print_json:
            print(json.dumps(
                {"aid": aid, "aimc": aimc, "timeseries": ts},
                indent=2, ensure_ascii=False,
            ))

        if not dry_run:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(
                    lambda sm: upload_submodel(server, sm),
                    (aid, aimc, ts),
                ))
            uploaded += sum(results)
            attach_submodels_to_shell(
                server, asset.shell,
                [aid["id"], aimc["id"], ts["id"]],
            )

    summary = validate_batch(typed_submodels, validator=IDTAValidator())
    print(f"[idta] Total time: {time.time()-t0:.1f}s", flush=True)

    src = summary.get("source", "")
    src_tag = f" [{src}]" if src else ""
    print(f"\n[idta] --- Validation summary{src_tag} ---")
    print(f"  Generated : {generated}")
    print(f"  Uploaded  : {uploaded}" if not dry_run
          else "  Uploaded  : (dry-run)")
    print(f"  Passed    : {summary['passed']}/{summary['total']} "
          f"({summary['passRate'] * 100:.1f}%)")
    for idx, item in enumerate(summary["items"], 1):
        status = "PASS" if item["passed"] else "FAIL"
        print(f"  [{idx:02d}] {item['submodelType']:<10} {status}")
        for e in item.get("errors", []):
            print(f"       [FAIL] {e}")
        for w in item.get("warnings", []):
            print(f"       [WARN] {w}")
        for d in item.get("differences", []):
            print(f"       [DIFF] {d}")

    return {
        "assets": len(assets),
        "generated": generated,
        "uploaded": uploaded,
        "validation": summary,
    }

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate-idta-submodels",
        description="Generate AID/AIMC/TimeSeries submodels from "
                    "qualifier-annotated AAS on the BaSyx server.",
    )
    parser.add_argument("--server", default=AAS_SERVER_URL,
                        help=f"AAS server URL (default: {AAS_SERVER_URL})")
    parser.add_argument(
        "--orchestrator", default=_DEFAULT_ORCHESTRATOR_URL,
        metavar="URL",
        help=(
            "BaSyx Test Orchestrator URL for IDTA conformance validation "
            f"(default: {_DEFAULT_ORCHESTRATOR_URL}, "
            "override via ORCHESTRATOR_URL env var). "
            "Falls back to local IDTAValidator if unreachable."
        ),
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Do not upload; only scan and build.")
    parser.add_argument("--print", dest="print_json", action="store_true",
                        help="Print generated submodels as JSON to stdout.")
    parser.add_argument("--save", metavar="DIR",
                        help="Additionally save each submodel as JSON "
                             "into DIR.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.save:
        os.makedirs(args.save, exist_ok=True)

    result = generate_and_upload(
        args.server,
        dry_run=args.dry_run,
        print_json=args.print_json,
        orchestrator_url=args.orchestrator,
    )

    if args.save and result["validation"].get("items"):
        assets = scan_assets(args.server)
        for asset in assets:
            asset_safe = sanitize_id(asset.asset_name)
            aid = build_aid_submodel(asset)
            aimc = build_aimc_submodel(asset, aid["id"])
            ts = build_timeseries_submodel(asset)
            for sm, tag in ((aid, "aid"), (aimc, "aimc"),
                            (ts, "timeseries")):
                path = Path(args.save) / f"{asset_safe}_{tag}.json"
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(sm, f, indent=2, ensure_ascii=False)
                print(f"  [save] {path}")

    v = result.get("validation") or {}
    if v.get("total", 0) > 0 and v.get("failed", 0) == 0:
        return 0
    return 1

if __name__ == "__main__":
    sys.exit(main())
