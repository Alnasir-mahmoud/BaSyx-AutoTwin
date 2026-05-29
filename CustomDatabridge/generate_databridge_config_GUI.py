# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar


import json
import requests
import base64
import os
import time
from typing import Dict, List, Optional, Tuple

from datatype_translate import to_custom as _to_custom

AAS_SERVER_URL  = os.getenv("AAS_SERVER_URL",  "http://localhost:8081")
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "mosquitto")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
INFLUXDB_URL_INTERNAL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")

def _rewrite_influx_host(qualifier_url: str) -> str:
    if not qualifier_url:
        return INFLUXDB_URL_INTERNAL
    bad_hosts = ("localhost", "127.0.0.1", os.getenv("HOSTNAME", ""))
    for h in bad_hosts:
        if h and (f"://{h}:" in qualifier_url or qualifier_url.endswith(f"://{h}")):
            return INFLUXDB_URL_INTERNAL
    return qualifier_url

OUTPUT_DIR = os.getenv(
    "OUTPUT_DIR",
    os.path.dirname(__file__)
)

def _encode(id_str: str) -> str:
    return base64.urlsafe_b64encode(id_str.encode()).decode().rstrip("=")

def _get(url: str) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [HTTP] GET {url} → {e}", flush=True)
        return None

def get_all_shells(server: str) -> List[dict]:
    data = _get(f"{server}/shells")
    if not data:
        return []
    return data.get("result", data) if isinstance(data, dict) else data

def get_submodel_ids_for_shell(server: str, shell_id: str) -> List[str]:
    enc = _encode(shell_id)
    data = _get(f"{server}/shells/{enc}/submodel-refs")
    if not data:
        return []
    refs = data.get("result", [])
    ids = []
    for ref in refs:
        keys = ref.get("keys", [])
        if keys:
            ids.append(keys[0]["value"])
    return ids

def get_submodel(server: str, sm_id: str) -> Optional[dict]:
    enc = _encode(sm_id)
    return _get(f"{server}/submodels/{enc}")

def get_submodel_elements(server: str, sm_id: str) -> List[dict]:
    enc = _encode(sm_id)
    data = _get(f"{server}/submodels/{enc}/submodel-elements")
    if not data:
        return []
    return data.get("result", data) if isinstance(data, dict) else data

def is_smc(elem: dict) -> bool:
    return "SubmodelElementCollection" in elem.get("modelType", "")

def find_smc(elements: List[dict], id_short: str) -> Optional[dict]:
    for e in elements:
        if e.get("idShort") == id_short and is_smc(e):
            return e
    return None

_KNOWN_PROTOCOL_SMC_NAMES = {
    "Modbus", "MQTT", "HTTP", "OPCUA", "OpcUa", "Kafka", "AMPERIX",
    "BACnet", "OCPP", "DLMS",
}

def find_protocol_pairs(elements: List[dict]
                         ) -> List[Tuple[Optional[str], dict, Optional[dict], str]]:
    pairs: List[Tuple[Optional[str], dict, Optional[dict], str]] = []

    for e in elements:
        if not is_smc(e):
            continue
        ids = e.get("idShort", "")
        if ids in _KNOWN_PROTOCOL_SMC_NAMES or ids.lower() in {
                "modbus", "mqtt", "http", "opcua", "kafka"}:
            comm = find_smc(e.get("value", []), "Connection")
            dp   = find_smc(e.get("value", []), "DataPoints")
            if comm is not None:
                pairs.append((ids.lower(), comm, dp, f"{ids}.DataPoints"))
    if pairs:
        return pairs

    comm_smcs: dict[str, dict] = {}
    dp_smcs:   dict[str, dict] = {}
    for e in elements:
        if not is_smc(e):
            continue
        ids = e.get("idShort", "")
        if ids == "CommunicationConfiguration":
            comm_smcs[""] = e
        elif ids.startswith("CommunicationConfiguration_"):
            comm_smcs[ids[len("CommunicationConfiguration_"):]] = e
        elif ids == "DataPoints":
            dp_smcs[""] = e
        elif ids.startswith("DataPoints_"):
            dp_smcs[ids[len("DataPoints_"):]] = e

    for suffix, comm in comm_smcs.items():
        prefix = f"DataPoints_{suffix}" if suffix else "DataPoints"
        pairs.append((suffix, comm, dp_smcs.get(suffix), prefix))
    return pairs

def find_datasinks_smc(elements: List[dict]) -> Optional[dict]:
    for e in elements:
        if is_smc(e) and e.get("idShort") == "DataSinks":
            return e
    return None

def extract_sink_info(datasinks_smc: Optional[dict]) -> dict:
    if not datasinks_smc:
        return {}

    out: dict = {}
    for child in datasinks_smc.get("value", []):
        if not is_smc(child):
            continue
        kind = child.get("idShort", "").lower()
        cfg = {}
        for sub in child.get("value", []):
            if sub.get("modelType") == "Property":
                k = sub.get("idShort", "")
                v = sub.get("value", "")
                if k:
                    cfg[k] = v
        if kind == "influxdb":
            out["influx"] = cfg
        elif kind == "mqtt":
            out["mqtt"] = cfg
    return out

def smc_prop_value(smc: dict, id_short: str) -> Optional[str]:
    for child in smc.get("value", []):
        if child.get("idShort") == id_short and child.get("modelType") in ("Property", "SubmodelElement"):
            return child.get("value")
        mt = child.get("modelType", {})
        if isinstance(mt, dict) and mt.get("name") == "Property" and child.get("idShort") == id_short:
            return child.get("value")
    return None

def get_qualifiers(prop: dict) -> Dict[str, str]:
    quals = {}
    for q in prop.get("qualifiers", []):
        qt = q.get("type") or q.get("type_")
        qv = q.get("value", "")
        if qt:
            quals[qt] = str(qv)
    return quals

def extract_comm_config(smc: dict) -> dict:
    cfg = {}
    for child in smc.get("value", []):
        id_short = child.get("idShort")
        val = child.get("value")
        if id_short and val is not None:
            cfg[id_short] = str(val)
    return cfg

def _bacnet_prop_id(raw: str) -> str:
    if not raw:
        return "presentValue"
    return raw[0].lower() + raw[1:]

def normalise_protocol(raw: str) -> str:
    r = raw.lower()
    if "modbus" in r:                 return "modbus"
    if "mqtt"   in r:                 return "mqtt"
    if "http"   in r or "rest" in r:  return "http"
    if "opc"    in r:                 return "opcua"
    if "kafka"  in r:                 return "kafka"
    if "bacnet" in r or "bac/ip" in r: return "bacnet"
    if "ocpp"   in r:                 return "ocpp"
    if "dlms"   in r or "cosem" in r: return "dlms"
    return r

def build_configs(
    server: str
) -> Tuple[List[dict], List[dict], List[dict], List[dict], List[dict]]:

    datasources:  List[dict] = []
    datasinks:    List[dict] = []
    routes:       List[dict] = []
    transformers: List[dict] = []
    write_routes: List[dict] = []

    print(f"Querying AAS Server: {server}", flush=True)

    shells = []
    for attempt in range(30):
        shells = get_all_shells(server)
        if shells:
            break
        print(f"  [INFO] Waiting for AAS Server... (attempt {attempt+1})", flush=True)
        time.sleep(2)

    if not shells:
        print("[WARN] No shells found on AAS server.", flush=True)
        return [], [], [], [], []

    print(f"Found {len(shells)} shell(s)\n", flush=True)

    for shell in shells:
        shell_id   = shell.get("id")
        asset_name = shell.get("idShort", "Asset")
        asset_safe = asset_name.replace(" ", "_").replace("-", "_")
        print(f"Processing Shell: {asset_name}  (id={shell_id})", flush=True)

        sm_ids = get_submodel_ids_for_shell(server, shell_id)

        for sm_id in sm_ids:
            elements = get_submodel_elements(server, sm_id)

            pairs = find_protocol_pairs(elements)
            if not pairs:
                continue

            sink_info = extract_sink_info(find_datasinks_smc(elements))
            shared_influx = sink_info.get("influx") or {}
            shared_mqtt   = sink_info.get("mqtt") or {}

            sm_data  = get_submodel(server, sm_id) or {}
            sm_label = sm_data.get("idShort", sm_id.split("/")[-1])
            sm_safe  = sm_label.replace(" ", "_").replace("-", "_")

            for suffix, comm_smc, dp_smc, dp_path_prefix in pairs:
                comm_cfg = extract_comm_config(comm_smc)

                raw_protocol = comm_cfg.get("Protocol")
                if not raw_protocol:
                    print(f"  [SKIP] No Protocol in CommunicationConfiguration"
                          f"{('_' + suffix) if suffix else ''}, skipping",
                          flush=True)
                    continue
                protocol = normalise_protocol(raw_protocol)

                _host_raw = (comm_cfg.get("Host") or comm_cfg.get("Broker")
                             or comm_cfg.get("ServerURL")
                             or comm_cfg.get("EndpointURL")
                             or comm_cfg.get("ProxyHost"))
                _port_from_host = None
                if _host_raw:
                    import re as _re
                    _stripped = _re.sub(r'^[a-zA-Z][a-zA-Z0-9+\-.]*://', '', _host_raw).split('/')[0].strip()
                    if ':' in _stripped:
                        _h, _p = _stripped.rsplit(':', 1)
                        host = _h.strip()
                        try:    _port_from_host = int(_p.strip())
                        except ValueError: pass
                    else:
                        host = _stripped
                else:
                    host = None
                if not host:
                    print(f"  [SKIP] No Host/Broker/URL in "
                          f"CommunicationConfiguration"
                          f"{('_' + suffix) if suffix else ''}", flush=True)
                    continue

                raw_port = comm_cfg.get("Port") or comm_cfg.get("ProxyPort")
                port = None
                if raw_port is not None:
                    try:    port = int(raw_port)
                    except Exception:
                        print(f"  [WARN] Port value '{raw_port}' is not an "
                              f"integer, skipping submodel", flush=True)
                        continue
                if port is None and _port_from_host is not None:
                    port = _port_from_host

                raw_slave = comm_cfg.get("SlaveID")
                slave_id = None
                if raw_slave is not None:
                    try:    slave_id = int(raw_slave)
                    except Exception:
                        print(f"  [WARN] SlaveID value '{raw_slave}' is "
                              f"not an integer", flush=True)

                print(f"  SubModel: {sm_label} | protocol={protocol} "
                      f"host={host} port={port} (suffix='{suffix}')",
                      flush=True)

                if not dp_smc:
                    print(f"  [SKIP] No DataPoints"
                          f"{('_' + suffix) if suffix else ''} SMC in "
                          f"{sm_label}", flush=True)
                    continue

                for child in dp_smc.get("value", []):
                    prop_name = child.get("idShort")
                    if not prop_name:
                        print(f"    [SKIP] DataPoint with no idShort",
                              flush=True)
                        continue
                    prop_safe = prop_name.replace(" ", "_").replace("-", "_")

                    if "SubmodelElementCollection" in child.get("modelType", ""):
                        value_child = next(
                            (c for c in child.get("value", []) or []
                             if c.get("idShort") == "Value"),
                            None,
                        )
                        if value_child is None:
                            print(f"    [SKIP] {prop_name}: wrapping SMC has "
                                  f"no Value child", flush=True)
                            continue
                        quals = get_qualifiers(value_child)
                        aas_path_suffix = ".Value"
                    else:
                        quals = get_qualifiers(child)
                        aas_path_suffix = ""

                    if not quals:
                        print(f"    [SKIP] {prop_name}: no qualifiers found",
                              flush=True)
                        continue

                    raw_type = quals.get("ModbusDataType") or quals.get("DataType")
                    if not raw_type:
                        print(f"    [SKIP] {prop_name}: no DataType qualifier",
                              flush=True)
                        continue
                    data_type = _to_custom(raw_type)

                    unit     = quals.get("Unit")
                    mqtt_out = f"aas/{asset_safe.lower()}/{sm_safe.lower()}/{prop_safe.lower()}"

                    route_id = f"Route_{asset_safe}_{sm_safe}_{prop_safe}"
                    src_id   = f"{route_id}_Source"
                    sink_id  = f"{route_id}_Sink"

                    if protocol == "modbus":
                        reg_str = quals.get("ModbusRegister")
                        if reg_str is None:
                            print(f"    [SKIP] {prop_name}: no ModbusRegister"
                                  f" qualifier", flush=True)
                            continue
                        try:
                            reg_num = int(reg_str)
                        except ValueError:
                            print(f"    [SKIP] {prop_name}: ModbusRegister "
                                  f"'{reg_str}' is not an integer", flush=True)
                            continue

                        if 30001 <= reg_num <= 39999:
                            reg_type = "input"
                            wire_addr = reg_num - 30001
                        elif 40001 <= reg_num <= 49999:
                            reg_type = "holding"
                            wire_addr = reg_num - 40001
                        elif 0 <= reg_num <= 29999:
                            reg_type = "input"
                            wire_addr = reg_num
                        else:
                            print(f"    [SKIP] {prop_name}: register {reg_num} "
                                  f"out of Modbus range", flush=True)
                            continue

                        source = {
                            "uniqueId":      src_id,
                            "id":            src_id,
                            "protocol":      "modbus",
                            "host":          host,
                            "port":          port,
                            "slave_id":      slave_id,
                            "register":      wire_addr,
                            "register_type": reg_type,
                            "dataType":      data_type,
                        }

                    elif protocol == "mqtt":
                        topic = quals.get("MqttTopic")
                        if not topic:
                            print(f"    [SKIP] {prop_name}: no MqttTopic"
                                  f" qualifier", flush=True)
                            continue
                        source = {
                            "uniqueId": src_id,
                            "id":       src_id,
                            "protocol": "mqtt",
                            "topic":    topic,
                        }

                    elif protocol == "http":
                        http_path = quals.get("HttpJsonPath")
                        if not http_path:
                            print(f"    [SKIP] {prop_name}: no HttpJsonPath"
                                  f" qualifier", flush=True)
                            continue
                        http_json_extract = quals.get("HttpResponseJsonPath", "value")
                        _raw_ep = (comm_cfg.get("EndpointURL") or comm_cfg.get("Host") or "")
                        _scheme = "https" if _raw_ep.lower().startswith("https://") else "http"
                        _http_port = port if port is not None else (443 if _scheme == "https" else 8082)
                        if (_scheme == "https" and _http_port == 443) or (_scheme == "http" and _http_port == 80):
                            _host_port = host
                        else:
                            _host_port = f"{host}:{_http_port}"
                        full_url = f"{_scheme}://{_host_port}{http_path}"
                        source = {
                            "uniqueId":  src_id,
                            "id":        src_id,
                            "protocol":  "http",
                            "url":       full_url,
                            "method":    comm_cfg.get("Method", "GET"),
                            "json_path": http_json_extract,
                        }
                        auth_type = (comm_cfg.get("HttpAuthType")
                                     or "none").lower()
                        source["auth_type"] = auth_type
                        if auth_type == "bearer":
                            source["bearer_token"] = comm_cfg.get(
                                "HttpBearerToken")
                        elif auth_type == "api_key_header":
                            source["api_key"]        = comm_cfg.get("HttpApiKey")
                            source["api_key_header"] = comm_cfg.get(
                                "HttpApiKeyHeader") or "X-API-Key"
                        elif auth_type == "api_key_query":
                            source["api_key"]       = comm_cfg.get("HttpApiKey")
                            source["api_key_query"] = comm_cfg.get(
                                "HttpApiKeyQuery") or "apikey"
                        elif auth_type == "oauth2_cc":
                            source["oauth_token_url"] = comm_cfg.get(
                                "OAuth2TokenUrl")
                            source["client_id"]       = comm_cfg.get(
                                "OAuth2ClientId")
                            source["client_secret"]   = comm_cfg.get(
                                "OAuth2ClientSecret")
                            source["scope"]           = comm_cfg.get(
                                "OAuth2Scope")
                        elif auth_type == "basic":
                            source["username"] = comm_cfg.get("HttpUsername")
                            source["password"] = comm_cfg.get("HttpPassword")
                        qp_str = comm_cfg.get("HttpQueryParams") or ""
                        if qp_str:
                            qp: dict[str, str] = {}
                            for pair in qp_str.split("&"):
                                if "=" in pair:
                                    k, v = pair.split("=", 1)
                                    if k.strip():
                                        qp[k.strip()] = v.strip()
                            if qp:
                                source["query_params"] = qp

                    elif protocol == "opcua":
                        node_id = quals.get("OpcuaNodeId")
                        if not node_id:
                            print(f"    [SKIP] {prop_name}: no OpcuaNodeId"
                                  f" qualifier", flush=True)
                            continue
                        raw_url = comm_cfg.get("ServerURL") or ""
                        server_url = (raw_url if raw_url.startswith("opc.tcp://")
                                      else f"opc.tcp://{host}:{port or 4840}")
                        source = {
                            "uniqueId":          src_id,
                            "id":                src_id,
                            "protocol":          "opcua",
                            "server":            server_url,
                            "node_id":           node_id,
                            "sampling_interval": int(quals.get("OpcuaSamplingInterval") or 500),
                        }

                    elif protocol == "kafka":
                        topic = quals.get("KafkaTopic")
                        if not topic:
                            print(f"    [SKIP] {prop_name}: no KafkaTopic"
                                  f" qualifier", flush=True)
                            continue
                        raw_broker = comm_cfg.get("BrokerUrl") or f"{host}:{port or 9092}"
                        source = {
                            "uniqueId":          src_id,
                            "id":                src_id,
                            "protocol":          "kafka",
                            "broker":            raw_broker,
                            "topic":             topic,
                            "json_path":         quals.get("KafkaJsonPath", ""),
                            "group_id":          comm_cfg.get("GroupId", "databridge"),
                            "max_poll_records":  int(comm_cfg.get("MaxPollRecords") or 5000),
                            "seek_to":           comm_cfg.get("SeekTo", "latest"),
                            "security_protocol": comm_cfg.get("SecurityProtocol", "PLAINTEXT"),
                        }

                    elif protocol == "bacnet":
                        obj_id = quals.get("BACnetObjectId")
                        if not obj_id:
                            print(f"    [SKIP] {prop_name}: no BACnetObjectId qualifier",
                                  flush=True)
                            continue
                        try:
                            dev_inst = int(comm_cfg.get("DeviceInstance", "0") or "0")
                        except Exception:
                            dev_inst = 0
                        source = {
                            "uniqueId":        src_id,
                            "id":              src_id,
                            "protocol":        "bacnet",
                            "host":            host,
                            "port":            port or 47808,
                            "device_instance": dev_inst,
                            "object_id":       obj_id,
                            "property_id":     _bacnet_prop_id(quals.get("BACnetPropertyId", "presentValue")),
                            "dataType":        data_type,
                        }

                    elif protocol == "ocpp":
                        measurand = quals.get("OCPPMeasurand")
                        if not measurand:
                            print(f"    [SKIP] {prop_name}: no OCPPMeasurand qualifier",
                                  flush=True)
                            continue
                        raw_url = (comm_cfg.get("ServerURL") or
                                   f"ws://{host}:{port or 9000}")
                        source = {
                            "uniqueId":        src_id,
                            "id":              src_id,
                            "protocol":        "ocpp",
                            "server_url":      raw_url,
                            "charge_point_id": comm_cfg.get("ChargePointId", "CP001"),
                            "measurand":       measurand,
                            "phase":           quals.get("OCPPPhase", ""),
                            "ocpp_version":    (comm_cfg.get("OCPPVersion", "1.6")
                                                .replace("OCPP ", "").strip()),
                        }

                    elif protocol == "dlms":
                        obis = quals.get("DLMSObisCode")
                        if not obis:
                            print(f"    [SKIP] {prop_name}: no DLMSObisCode qualifier",
                                  flush=True)
                            continue
                        try:
                            attribute = int(quals.get("DLMSAttribute", "2") or "2")
                        except Exception:
                            attribute = 2
                        try:
                            client_id = int(comm_cfg.get("ClientId", "16") or "16")
                        except Exception:
                            client_id = 16
                        source = {
                            "uniqueId":       src_id,
                            "id":             src_id,
                            "protocol":       "dlms",
                            "host":           host,
                            "port":           port or 4059,
                            "obis_code":      obis,
                            "attribute":      attribute,
                            "client_id":      client_id,
                            "logical_device": int(comm_cfg.get("LogicalDevice", "1") or "1"),
                            "auth_level":     (comm_cfg.get("AuthLevel", "none") or "none").lower(),
                            "password":       comm_cfg.get("Password", ""),
                        }

                    else:
                        print(f"    [SKIP] {prop_name}: unsupported protocol"
                              f" '{protocol}'", flush=True)
                        continue

                    datasources.append(source)

                    sink = {
                        "uniqueId":        sink_id,
                        "id":              sink_id,
                        "type":            "mqtt",
                        "host":            MQTT_BROKER_HOST,
                        "port":            MQTT_BROKER_PORT,
                        "topic":           mqtt_out,
                        "aas_submodel_id": sm_id,
                        "aas_id_short":    f"{dp_path_prefix}.{prop_name}{aas_path_suffix}",
                        "aas_value_type":  "xs:float",
                    }
                    if unit:
                        sink["unit"] = unit

                    influx_url_raw = (shared_influx.get("ServerUrl")
                                       or quals.get("InfluxServerUrl"))
                    if influx_url_raw:
                        influx_url = _rewrite_influx_host(influx_url_raw)
                        sink["enable_influx"]      = True
                        sink["influx_endpoint"]    = influx_url
                        sink["influx_token"]       = (shared_influx.get("Token")
                                                       or quals.get("InfluxToken", ""))
                        sink["influx_org"]         = (shared_influx.get("Org")
                                                       or quals.get("InfluxOrg", ""))
                        sink["influx_database"]    = (shared_influx.get("Bucket")
                                                       or quals.get("InfluxBucket", ""))
                        sink["influx_measurement"] = prop_name
                        rewrite_note = (" (rewritten)"
                                        if influx_url != influx_url_raw else "")
                        print(f"      + InfluxDB → {influx_url}{rewrite_note} "
                              f"bucket={sink['influx_database']}", flush=True)
                    else:
                        sink["enable_influx"] = False

                    ext_mqtt_topic = (shared_mqtt.get("Topic")
                                       or quals.get("SinkMqttTopic"))
                    if ext_mqtt_topic:
                        sink["external_mqtt_topic"]  = ext_mqtt_topic
                        sink["external_mqtt_broker"] = (
                            shared_mqtt.get("Broker")
                            or quals.get("SinkMqttBroker", MQTT_BROKER_HOST)
                        )
                        print(f"      + External MQTT → {ext_mqtt_topic}",
                              flush=True)

                    transform_formula = (quals.get("TransformFormula") or "").strip()
                    route_transformer_ids = []
                    if transform_formula:
                        if 'x' not in transform_formula:
                            print(f"    [WARN] {prop_name}: TransformFormula "
                                  f"{transform_formula!r} enthält kein 'x' — "
                                  f"bitte 'x' als Rohwert verwenden, z.B. x/10",
                                  flush=True)
                        sink["transform_formula"] = transform_formula
                        t_id = f"{route_id}_Transformer"
                        transformers.append({
                            "uniqueId": t_id,
                            "id":       t_id,
                            "type":     "formula",
                            "formula":  transform_formula,
                        })
                        route_transformer_ids.append(t_id)

                    datasinks.append(sink)

                    routes.append({
                        "uniqueId":    route_id,
                        "id":          route_id,
                        "dataSource":  src_id,
                        "transformers": route_transformer_ids,
                        "dataSink":    sink_id,
                    })

                    direction = (quals.get("Direction") or "Read").strip()
                    if direction in ("Write", "ReadWrite"):
                        write_target = dict(source)
                        if protocol == "modbus":
                            if direction == "Write":
                                write_target["register_type"] = "holding"
                        write_routes.append({
                            "uniqueId":   f"{route_id}_Write",
                            "direction":  "write",
                            "submodelId": sm_id,
                            "aasIdShort": sink["aas_id_short"],
                            "protocol":   protocol,
                            "source":     write_target,
                        })

                    reg_info = (f"reg={quals.get('ModbusRegister')}"
                                if protocol == "modbus" else "")
                    direction_note = ("" if direction == "Read"
                                       else f" [{direction}]")
                    print(f"    [{protocol.upper()}] {prop_name}{direction_note}"
                          f"  ({reg_info} type={data_type})  →  MQTT {mqtt_out}",
                          flush=True)

        print(flush=True)

    return datasources, datasinks, routes, transformers, write_routes

def write_configs(out_dir, datasources, datasinks, routes, transformers,
                   write_routes=None):
    os.makedirs(out_dir, exist_ok=True)

    def dump(filename, data):
        path = os.path.join(out_dir, filename)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  [WRITE] {path}  ({len(data)} entries)", flush=True)

    dump("datasources.json",  datasources)
    dump("datasinks.json",    datasinks)
    dump("routes.json",       routes)
    dump("transformers.json", transformers)
    dump("write_routes.json", write_routes or [])

_PLC4X_TYPES = {
    "float32": "REAL",  "float64": "LREAL",
    "int16":   "INT",   "uint16":  "UINT",
    "int32":   "DINT",  "uint32":  "UDINT",
    "bool":    "BOOL",  "string":  "STRING",
}

def _plc4x_dtype(custom: str) -> str:
    return _PLC4X_TYPES.get((custom or "float32").lower(), "REAL")

def build_official_configs(datasources, datasinks, routes):
    src_map  = {s["uniqueId"]: s for s in datasources}
    sink_map = {s["uniqueId"]: s for s in datasinks}

    plc4x_consumers   = []
    mqtt_consumers    = []
    http_consumers    = []
    opcua_consumers   = []
    kafka_consumers   = []
    aas_sinks         = []
    off_routes        = []
    jsonata_xfmrs     = []
    jsonata_files     = {}

    _SKIP_PROTOCOLS = {"bacnet", "ocpp", "dlms"}

    for route in routes:
        src  = src_map.get(route.get("dataSource") or route.get("datasource", ""))
        sink = sink_map.get(route.get("dataSink")   or route.get("datasink",  ""))
        if not src or not sink:
            continue

        protocol = src.get("protocol", "")
        if protocol in _SKIP_PROTOCOLS:
            continue

        id_short_full = sink.get("aas_id_short", "")
        parts = id_short_full.split(".")
        prop_name = parts[-2] if len(parts) >= 2 else parts[0]

        sm_id        = sink.get("aas_submodel_id", "")
        sm_b64       = _encode(sm_id) if sm_id else ""
        sm_endpoint  = f"{AAS_SERVER_URL}/submodels/{sm_b64}"
        aas_sink_uid = f"official/{prop_name}"
        aas_sinks.append({
            "uniqueId":        aas_sink_uid,
            "submodelEndpoint": sm_endpoint,
            "idShortPath":     id_short_full,
            "api":             "DotAAS-V3",
        })

        xfmr_uid  = f"extract{prop_name}"
        xfmr_file = f"{xfmr_uid}.jsonata"

        if protocol == "modbus":
            tag_name  = prop_name
            jsonata_expr = f'{tag_name} ? $string({tag_name}) : "0"'
        elif protocol in ("mqtt", "opcua"):
            jsonata_expr = f'$ ? $string($) : "0"'
        elif protocol in ("http", "kafka"):
            jsonata_expr = f'value ? $string(value) : "0"'
        else:
            jsonata_expr = f'$ ? $string($) : "0"'

        jsonata_xfmrs.append({
            "uniqueId":   xfmr_uid,
            "queryPath":  xfmr_file,
            "inputType":  "JsonString",
            "outputType": "JsonString",
        })
        jsonata_files[xfmr_file] = jsonata_expr

        if protocol == "modbus":
            reg      = src.get("register", 0)
            reg_type = src.get("register_type", "input")
            dtype    = _plc4x_dtype(src.get("dataType", "float32"))
            con_uid  = f"plc4x-{prop_name.lower()}"
            plc4x_consumers.append({
                "uniqueId":   con_uid,
                "serverUrl":  src.get("host", ""),
                "serverPort": src.get("port", 5020),
                "driver":     "modbus-tcp",
                "servicePath": "",
                "options":    "autoReconnect=true",
                "tags": [{"name": prop_name,
                          "value": f"{reg_type}-register:{reg + 1}:{dtype}"}],
            })
            off_routes.append({
                "datasource":  con_uid,
                "transformers": ["dataValueToJson", xfmr_uid],
                "datasinks":   [aas_sink_uid],
                "trigger":     "timer",
                "triggerData": {"timerName": "timer-db"},
            })

        elif protocol == "mqtt":
            con_uid = f"mqtt-{prop_name.lower()}"
            mqtt_consumers.append({
                "uniqueId":  con_uid,
                "serverUrl": f"tcp://{MQTT_BROKER_HOST}",
                "port":      MQTT_BROKER_PORT,
                "topic":     src.get("topic", ""),
            })
            off_routes.append({
                "datasource":  con_uid,
                "transformers": [xfmr_uid],
                "datasinks":   [aas_sink_uid],
            })

        elif protocol == "http":
            con_uid = f"http-{prop_name.lower()}"
            http_consumers.append({
                "uniqueId":  con_uid,
                "serverUrl": src.get("url", ""),
                "method":    src.get("method", "GET"),
            })
            off_routes.append({
                "datasource":  con_uid,
                "transformers": [xfmr_uid],
                "datasinks":   [aas_sink_uid],
                "trigger":     "timer",
                "triggerData": {"timerName": "timer-db"},
            })

        elif protocol == "opcua":
            con_uid = f"opcua-{prop_name.lower()}"
            opcua_consumers.append({
                "uniqueId":      con_uid,
                "serverUrl":     src.get("server", ""),
                "nodeInformation": src.get("node_id", ""),
            })
            off_routes.append({
                "datasource":  con_uid,
                "transformers": [xfmr_uid],
                "datasinks":   [aas_sink_uid],
                "trigger":     "timer",
                "triggerData": {"timerName": "timer-db"},
            })

        elif protocol == "kafka":
            con_uid = f"kafka-{prop_name.lower()}"
            kafka_consumers.append({
                "uniqueId":  con_uid,
                "serverUrl": src.get("broker", ""),
                "topic":     src.get("topic", ""),
            })
            off_routes.append({
                "datasource":  con_uid,
                "transformers": [xfmr_uid],
                "datasinks":   [aas_sink_uid],
            })

    return (plc4x_consumers, mqtt_consumers, http_consumers, opcua_consumers,
            kafka_consumers, aas_sinks, off_routes, jsonata_xfmrs, jsonata_files)

def write_official_configs(out_dir, plc4x, mqtt, http_c, opcua, kafka,
                            aas_sinks, off_routes, jsonata_xfmrs, jsonata_files):
    os.makedirs(out_dir, exist_ok=True)

    def dump(filename, data):
        if not data:
            return
        path = os.path.join(out_dir, filename)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  [OFFICIAL] {path}  ({len(data)} entries)", flush=True)

    dump("plc4xconsumer.json",         plc4x)
    dump("mqttconsumer.json",          mqtt)
    dump("httpconsumer.json",          http_c)
    dump("opcuaconsumer.json",         opcua)
    dump("kafkaconsumer.json",         kafka)
    dump("aasserver.json",             aas_sinks)
    dump("routes.json",                off_routes)
    dump("jsonatatransformer.json",    jsonata_xfmrs)

    _static = {
        "timerconsumer.json": [
            {"uniqueId": "timer-db", "fixedRate": True, "delay": 0, "period": 5000}
        ],
        "jsonjacksontransformer.json": [
            {"uniqueId": "dataValueToJson", "operation": "marshal", "jacksonModules": ""}
        ],
    }
    for fname, data in _static.items():
        path = os.path.join(out_dir, fname)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  [OFFICIAL] {path}", flush=True)

    for fname, expr in jsonata_files.items():
        path = os.path.join(out_dir, fname)
        with open(path, "w") as f:
            f.write(expr)

    counts = (f"{len(plc4x)} PLC4X  {len(mqtt)} MQTT  {len(http_c)} HTTP  "
              f"{len(opcua)} OPC-UA  {len(kafka)} Kafka  → {len(off_routes)} routes")
    print(f"  [OFFICIAL] {counts}", flush=True)

def _restart_official_databridge():
    import socket as _socket, http.client as _http
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        print("[OFFICIAL_DB] Docker socket not found — skipping restart.", flush=True)
        print("[OFFICIAL_DB] Run manually: docker compose restart databridge-official",
              flush=True)
        return
    try:
        class _UnixHTTP(_http.HTTPConnection):
            def connect(self):
                self.sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                self.sock.connect(sock_path)

        conn = _UnixHTTP("localhost")
        conn.request("POST", "/containers/databridge-official/restart?t=5")
        resp = conn.getresponse()
        resp.read()
        if resp.status in (204, 200):
            print("[OFFICIAL_DB] databridge-official restarted successfully.", flush=True)
        else:
            print(f"[OFFICIAL_DB] Restart returned HTTP {resp.status} — "
                  f"container may not be running yet.", flush=True)
    except Exception as exc:
        print(f"[OFFICIAL_DB] Could not restart via Docker socket: {exc}", flush=True)
        print("[OFFICIAL_DB] Run: docker compose restart databridge-official", flush=True)

if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("databridge_GUI — AAS Server Auto-Configuration", flush=True)
    print("=" * 60, flush=True)
    print(f"Server:     {AAS_SERVER_URL}", flush=True)
    print(f"Output dir: {OUTPUT_DIR}", flush=True)
    print(flush=True)

    sources, sinks, routes, transformers, write_routes = build_configs(AAS_SERVER_URL)

    print(f"Summary: {len(routes)} routes | {len(sources)} sources | "
          f"{len(sinks)} sinks | {len(transformers)} transformers | "
          f"{len(write_routes)} write-routes",
          flush=True)
    print(flush=True)

    write_configs(OUTPUT_DIR, sources, sinks, routes, transformers,
                   write_routes=write_routes)

    official_dir = os.path.join(OUTPUT_DIR, "official-config")
    print(f"\nGenerating official DataBridge configs → {official_dir}", flush=True)
    (plc4x, mqtt_c, http_c, opcua, kafka,
     aas_s, off_r, j_xfmrs, j_files) = build_official_configs(sources, sinks, routes)
    write_official_configs(official_dir, plc4x, mqtt_c, http_c, opcua, kafka,
                            aas_s, off_r, j_xfmrs, j_files)

    print("\n✅ Configuration written. databridge_service.py can now start.", flush=True)

    _restart_official_databridge()
