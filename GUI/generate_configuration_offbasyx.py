# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar


import os
import sys
import re
import json
import base64
import subprocess
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from qualifier_vocabulary import lookup_value as _q
except ImportError:
    def _q(quals, *names, default=None):
        for n in names:
            if quals and n in quals:
                return quals[n]
        return default
import time

import requests

AAS_SERVER_URL   = os.getenv("AAS_SERVER_URL",   "http://aas-env:8081")
OUTPUT_DIR       = os.getenv(
    "OUTPUT_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "databridge_config")
)
DOCKER_CONTAINER = "databridge-official"
DOCKER_IMAGE     = "eclipsebasyx/databridge:1.0.0-SNAPSHOT"

DOCKER_HOST_MAP = {
    "192.168.1.20":  "mosquitto",
    "192.168.1.200": "ext-simulator",
    "192.168.1.100": "ext-simulator",
    "kafka.local":   "kafka",
}

def _resolve_host(host: str) -> str:
    return DOCKER_HOST_MAP.get(host.strip(), host.strip())

def _resolve_url(url: str) -> str:
    for ip, svc in DOCKER_HOST_MAP.items():
        url = url.replace(ip, svc)
    return url

from datatype_translate import to_plc4x as _to_plc4x

def _encode(id_str: str) -> str:
    return base64.urlsafe_b64encode(id_str.encode()).decode().rstrip("=")

def _get(url: str):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [HTTP] GET {url} → {e}", flush=True)
        return None

def get_all_shells(server: str) -> list:
    data = _get(f"{server}/shells")
    if not data:
        return []
    return data.get("result", data) if isinstance(data, dict) else data

def get_submodel_ids_for_shell(server: str, shell_id: str) -> list:
    enc  = _encode(shell_id)
    data = _get(f"{server}/shells/{enc}/submodel-refs")
    if not data:
        return []
    ids = []
    for ref in data.get("result", []):
        keys = ref.get("keys", [])
        if keys:
            ids.append(keys[0]["value"])
    return ids

def get_submodel(server: str, sm_id: str):
    return _get(f"{server}/submodels/{_encode(sm_id)}")

def get_submodel_elements(server: str, sm_id: str) -> list:
    data = _get(f"{server}/submodels/{_encode(sm_id)}/submodel-elements")
    if not data:
        return []
    return data.get("result", data) if isinstance(data, dict) else data

def extract_comm_config(smc: dict) -> dict:
    cfg = {}
    for child in smc.get("value", []):
        id_short = child.get("idShort")
        val      = child.get("value")
        if id_short and val is not None:
            cfg[id_short] = str(val)
    return cfg

def get_qualifiers(prop: dict) -> dict:
    quals = {}
    for q in prop.get("qualifiers", []):
        qt = q.get("type") or q.get("type_")
        qv = q.get("value", "")
        if qt:
            quals[qt] = str(qv)
    return quals

def unwrap_datapoint(dp: dict) -> tuple:
    name = dp.get("idShort", "")
    if "SubmodelElementCollection" in dp.get("modelType", ""):
        for c in dp.get("value", []) or []:
            if c.get("idShort") == "Value":
                return name, c, ".Value"
        return name, None, ""
    return name, dp, ""

def normalise_protocol(raw: str) -> str:
    r = raw.lower()
    if "modbus" in r:                  return "modbus"
    if "mqtt"   in r:                  return "mqtt"
    if "http"   in r or "rest" in r:   return "http"
    if "opc"    in r:                  return "opcua"
    if "kafka"  in r:                  return "kafka"
    if "bacnet" in r or "bac" in r:    return "bacnet"
    if "ocpp"   in r:                  return "ocpp"
    if "dlms"   in r or "cosem" in r:  return "dlms"
    return r

def safe_int(val, default=0) -> int:
    try:
        if val is None or val == "":
            return default
        return int(val)
    except (ValueError, TypeError):
        return default

def parse_polling(val) -> int:
    if not val:
        return 5000
    digits = "".join(c for c in str(val) if c.isdigit())
    return int(digits) if digits else 5000

def sanitize_id(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", str(name))
    return ("n" + s) if s and s[0].isdigit() else s

def _get_influxdb_sink_id(quals, asset_safe, sm_safe, prop_name, influxdb_sinks):
    server_url  = (_q(quals, "InfluxServerUrl")
                   or _q(quals, "ServerUrl"))
    token       = (_q(quals, "InfluxToken")
                   or _q(quals, "Token"))
    org         = (_q(quals, "InfluxOrg")
                   or _q(quals, "Org"))
    bucket      = (_q(quals, "InfluxBucket")
                   or _q(quals, "Bucket"))

    if not (server_url and token and org and bucket):
        return None

    influx_id = f"influxdb_{asset_safe}_{sm_safe}_{prop_name}"
    influxdb_sinks.append({
        "uniqueId":    influx_id,
        "serverUrl":   server_url,
        "token":       token,
        "org":         org,
        "bucket":      bucket,
        "measurement": asset_safe,
        "submodel":    sm_safe,
        "property":    prop_name,
        "fieldName":   prop_name
    })
    print(f"      + InfluxDB → {server_url} bucket={bucket} measurement={asset_safe} submodel={sm_safe} property={prop_name}", flush=True)
    return influx_id

def build_official_configs(server: str) -> dict:
    plc4x_consumers  = []
    mqtt_consumers   = []
    http_consumers   = []
    opcua_consumers  = []
    kafka_consumers  = []
    influxdb_sinks   = []
    timer_consumers  = {}
    aas_sinks        = []
    routes           = []
    jsonata_transformers = []
    jsonata_expr_files  = {}
    jsonata_ids      = set()
    tag_names        = set()
    sink_ids         = set()
    has_plc4x       = False
    has_opcua       = False

    plc4x_by_conn  = {}
    opcua_by_node  = {}
    kafka_by_topic = {}

    print(f"Querying AAS Server: {server}", flush=True)

    shells = []
    for attempt in range(30):
        shells = get_all_shells(server)
        if shells:
            break
        print(f"  [INFO] Waiting for AAS Server... (attempt {attempt + 1})", flush=True)
        time.sleep(2)

    if not shells:
        print("[WARN] No shells found on AAS server.", flush=True)
        return {}

    print(f"Found {len(shells)} shell(s)\n", flush=True)

    for shell in shells:
        shell_id   = shell.get("id")
        asset_name = shell.get("idShort", "Asset")
        print(f"Processing Shell: {asset_name}  (id={shell_id})", flush=True)

        sm_ids = get_submodel_ids_for_shell(server, shell_id)

        for sm_id in sm_ids:
            elements = get_submodel_elements(server, sm_id)

            comm_map = {}
            dp_map   = {}

            _PROTO_NAMES = {"modbus","mqtt","http","opcua","kafka","bacnet","ocpp","dlms"}

            for elem in elements:
                id_s = elem.get("idShort", "")
                if id_s.lower() in _PROTO_NAMES and "SubmodelElementCollection" in elem.get("modelType",""):
                    children = elem.get("value", []) or []
                    conn_child = next((c for c in children
                                        if c.get("idShort") == "Connection"), None)
                    dp_child   = next((c for c in children
                                        if c.get("idShort") == "DataPoints"), None)
                    if conn_child:
                        comm_map[id_s.lower()] = conn_child
                    if dp_child:
                        dp_map[id_s.lower()] = dp_child
                elif id_s.startswith("CommunicationConfiguration"):
                    comm_map[id_s[len("CommunicationConfiguration"):]] = elem
                elif id_s.startswith("DataPoints"):
                    dp_map[id_s[len("DataPoints"):]] = elem

            if not comm_map:
                continue

            shared_sink_quals: dict[str, str] = {}
            for elem in elements:
                if (elem.get("idShort") == "DataSinks"
                        and "SubmodelElementCollection" in elem.get("modelType", "")):
                    for child in elem.get("value", []) or []:
                        if "SubmodelElementCollection" not in child.get("modelType", ""):
                            continue
                        kind = child.get("idShort", "").lower()
                        prefix = "Influx" if kind == "influxdb" else \
                                  ("SinkMqtt" if kind == "mqtt" else kind)
                        for sub in child.get("value", []) or []:
                            if sub.get("modelType") == "Property":
                                k = sub.get("idShort", "")
                                v = sub.get("value", "")
                                if k:
                                    shared_sink_quals[k] = str(v)
                                    shared_sink_quals[f"{prefix}{k}"] = str(v)

            sm_data     = get_submodel(server, sm_id) or {}
            sm_label    = sm_data.get("idShort", sm_id.split("/")[-1])
            sm_safe     = sanitize_id(sm_label)
            sm_endpoint = f"{server}/submodels/{_encode(sm_id)}"

            print(f"  SubModel: {sm_label}", flush=True)

            for suffix, dp_smc in dp_map.items():
                comm = comm_map.get(suffix) or comm_map.get("")
                if not comm:
                    print(f"    [SKIP] No CommunicationConfiguration for suffix '{suffix}'", flush=True)
                    continue

                comm_cfg  = extract_comm_config(comm)
                raw_proto = comm_cfg.get("Protocol", "")
                if not raw_proto:
                    print(f"    [SKIP] No Protocol value in CommunicationConfiguration", flush=True)
                    continue
                protocol = normalise_protocol(raw_proto)

                dp_smc_id_short = f"DataPoints{suffix}"
                polling         = parse_polling(comm_cfg.get("PollingInterval"))

                print(f"    Suffix='{suffix}' | protocol={protocol} | polling={polling}ms", flush=True)

                if protocol == "modbus":
                    host = _resolve_host(comm_cfg.get("Host") or "ext-simulator")
                    port = safe_int(comm_cfg.get("Port"), 5020)

                    conn_key = (host, port)
                    if conn_key not in plc4x_by_conn:
                        cid   = f"plc4x_{sanitize_id(host)}_{port}"
                        entry = {
                            "uniqueId":    cid,
                            "serverUrl":   host,
                            "serverPort":  port,
                            "driver":      "modbus-tcp",
                            "servicePath": "",
                            "options": [
                                {"name": "period", "value": str(polling)}
                            ],
                            "tags": []
                        }
                        plc4x_by_conn[conn_key] = entry
                        plc4x_consumers.append(entry)

                    consumer = plc4x_by_conn[conn_key]
                    has_plc4x = True

                    for dp in dp_smc.get("value", []):
                        prop_name, value_elem, path_suffix = unwrap_datapoint(dp)
                        if not prop_name or value_elem is None:
                            continue
                        quals     = {**shared_sink_quals, **get_qualifiers(value_elem)}
                        register  = _q(quals, "ModbusRegister")
                        data_type = (_q(quals, "ModbusDataType") or "FLOAT32").upper()
                        if not register:
                            print(f"      [SKIP] {prop_name}: no ModbusRegister qualifier", flush=True)
                            continue

                        plc4x_type = _to_plc4x(data_type)
                        asset_safe = sanitize_id(asset_name)
                        tag_name   = f"{asset_safe}_{sm_safe}_{prop_name}"

                        reg_num = safe_int(register, 0)
                        if 30001 <= reg_num <= 39999:
                            reg_type   = "input-register"
                            plc4x_addr = reg_num - 30000
                        else:
                            reg_type   = "holding-register"
                            plc4x_addr = reg_num - 40000

                        if tag_name not in tag_names:
                            tag_names.add(tag_name)
                            consumer["tags"].append({
                                "name":  tag_name,
                                "value": f"{reg_type}:{plc4x_addr}:{plc4x_type}"
                            })

                        jt_id = f"extract_{tag_name}"
                        if jt_id not in jsonata_ids:
                            jsonata_transformers.append({
                                "uniqueId":  jt_id,
                                "queryPath": f"{jt_id}.jsonata",
                                "inputType":  "JsonString",
                                "outputType": "JsonString"
                            })
                            jsonata_expr_files[f"{jt_id}.jsonata"] = f"$number({tag_name})"
                            jsonata_ids.add(jt_id)

                        sink_id = f"{asset_safe}_{sm_safe}_{prop_name}"
                        if sink_id not in sink_ids:
                            sink_ids.add(sink_id)
                            aas_sinks.append({
                                "uniqueId":         sink_id,
                                "submodelEndpoint": sm_endpoint,
                                "idShortPath":      f"{dp_smc_id_short}.{prop_name}{path_suffix}",
                                "api":              "DotAAS-V3"
                            })

                        timer_id = f"timer_{polling}ms"
                        if timer_id not in timer_consumers:
                            timer_consumers[timer_id] = {
                                "uniqueId": timer_id,
                                "fixedRate": True,
                                "delay": 0,
                                "period": polling
                            }
                            
                        datasinks = [sink_id]
                        influx_id = _get_influxdb_sink_id(quals, asset_safe, sm_safe, prop_name, influxdb_sinks)
                        if influx_id:
                            datasinks.append(influx_id)

                        routes.append({
                            "datasource":  consumer["uniqueId"],
                            "transformers": ["plc4x-to-json", jt_id],
                            "datasinks":   datasinks,
                            "trigger":     "timer",
                            "triggerData": {"timerName": timer_id}
                        })
                        print(f"      [MODBUS] {prop_name}  reg={register} → {reg_type}:{plc4x_addr}:{plc4x_type}", flush=True)

                elif protocol == "mqtt":
                    broker = _resolve_host(comm_cfg.get("Broker") or "mosquitto")
                    port   = safe_int(comm_cfg.get("Port"), 1883)

                    for dp in dp_smc.get("value", []):
                        prop_name, value_elem, path_suffix = unwrap_datapoint(dp)
                        if not prop_name or value_elem is None:
                            continue
                        quals = {**shared_sink_quals, **get_qualifiers(value_elem)}
                        topic = _q(quals, "MqttTopic")
                        if not topic:
                            print(f"      [SKIP] {prop_name}: no MqttTopic qualifier", flush=True)
                            continue

                        json_path = quals.get("MqttJsonPath")
                        cid       = f"mqtt_{sanitize_id(topic)}"

                        mqtt_consumers.append({
                            "uniqueId":   cid,
                            "serverUrl":  broker,
                            "serverPort": port,
                            "topic":      topic
                        })

                        transformer = None
                        if json_path:
                            jt_id = f"extract_{cid}"
                            expr  = json_path.lstrip("$").lstrip(".")
                            if jt_id not in jsonata_ids:
                                jsonata_transformers.append({
                                    "uniqueId":  jt_id,
                                    "queryPath": f"{jt_id}.jsonata",
                                    "inputType":  "JsonString",
                                    "outputType": "JsonString"
                                })
                                jsonata_expr_files[f"{jt_id}.jsonata"] = expr
                                jsonata_ids.add(jt_id)
                            transformer = jt_id

                        asset_safe = sanitize_id(asset_name)
                        sink_id = f"{sm_safe}_{prop_name}"
                        aas_sinks.append({
                            "uniqueId":         sink_id,
                            "submodelEndpoint": sm_endpoint,
                            "idShortPath":      f"{dp_smc_id_short}.{prop_name}{path_suffix}",
                            "api":              "DotAAS-V3"
                        })
                        datasinks = [sink_id]
                        influx_id = _get_influxdb_sink_id(quals, asset_safe, sm_safe, prop_name, influxdb_sinks)
                        if influx_id:
                            datasinks.append(influx_id)

                        route = {"datasource": cid, "datasinks": datasinks, "trigger": "event"}
                        if transformer:
                            route["transformers"] = [transformer]
                        routes.append(route)
                        print(f"      [MQTT] {prop_name}  topic={topic}", flush=True)

                elif protocol == "http":
                    endpoint_url = comm_cfg.get("EndpointURL") or ""
                    if not endpoint_url:
                        print(f"    [SKIP] No EndpointURL for HTTP protocol", flush=True)
                        continue

                    for dp in dp_smc.get("value", []):
                        prop_name, value_elem, path_suffix = unwrap_datapoint(dp)
                        if not prop_name or value_elem is None:
                            continue
                        quals     = {**shared_sink_quals, **get_qualifiers(value_elem)}
                        json_path = _q(quals, "HttpJsonPath")
                        cid       = f"http_{sm_safe}_{prop_name}"

                        http_consumers.append({
                            "uniqueId":  cid,
                            "serverUrl": endpoint_url
                        })

                        transformer = None
                        if json_path:
                            jt_id = f"extract_{cid}"
                            expr  = json_path.lstrip("$").lstrip(".")
                            jsonata_files[f"{jt_id}.json"] = expr
                            transformer = jt_id

                        sink_id = f"{sm_safe}_{prop_name}"
                        aas_sinks.append({
                            "uniqueId":         sink_id,
                            "submodelEndpoint": sm_endpoint,
                            "idShortPath":      f"{dp_smc_id_short}.{prop_name}{path_suffix}",
                            "api":              "DotAAS-V3"
                        })
                        
                        timer_id = f"timer_{polling}ms"
                        if timer_id not in timer_consumers:
                            timer_consumers[timer_id] = {
                                "uniqueId": timer_id,
                                "fixedRate": True,
                                "delay": 0,
                                "period": polling
                            }
                            
                        asset_safe = sanitize_id(asset_name)
                        datasinks = [sink_id]
                        influx_id = _get_influxdb_sink_id(quals, asset_safe, sm_safe, prop_name, influxdb_sinks)
                        if influx_id:
                            datasinks.append(influx_id)

                        route = {"datasource": cid, "datasinks": datasinks,
                                 "trigger": "timer", "triggerData": {"timerName": timer_id}}
                        if transformer:
                            route["transformers"] = [transformer]
                        routes.append(route)
                        print(f"      [HTTP] {prop_name}  url={endpoint_url}", flush=True)

                elif protocol == "opcua":
                    server_url = _resolve_url(comm_cfg.get("ServerURL") or "opc.tcp://ext-simulator:4840")

                    opcua_host    = "localhost"
                    opcua_port    = 4840
                    path_to_svc   = ""
                    if "://" in server_url:
                        remainder = server_url.split("://", 1)[1]
                        if "/" in remainder:
                            host_port, path_to_svc = remainder.split("/", 1)
                            path_to_svc = path_to_svc.rstrip("/")
                        else:
                            host_port = remainder.rstrip("/")
                        if ":" in host_port:
                            opcua_host, p = host_port.rsplit(":", 1)
                            opcua_port = safe_int(p, 4840)
                        else:
                            opcua_host = host_port

                    pub_interval = safe_int(comm_cfg.get("PublishingInterval"), polling)
                    username     = comm_cfg.get("Username") or ""
                    password     = comm_cfg.get("Password") or ""

                    for dp in dp_smc.get("value", []):
                        prop_name, value_elem, path_suffix = unwrap_datapoint(dp)
                        if not prop_name or value_elem is None:
                            continue
                        quals   = {**shared_sink_quals, **get_qualifiers(value_elem)}
                        node_id = _q(quals, "OpcuaNodeId")
                        if not node_id:
                            print(f"      [SKIP] {prop_name}: no OpcuaNodeId qualifier", flush=True)
                            continue

                        asset_safe = sanitize_id(asset_name)

                        node_key = (opcua_host, opcua_port, path_to_svc, node_id)
                        if node_key not in opcua_by_node:
                            cid = f"opcua_{sanitize_id(opcua_host)}_{sanitize_id(node_id)}"
                            entry = {
                                "uniqueId":                    cid,
                                "serverUrl":                   opcua_host,
                                "serverPort":                  opcua_port,
                                "pathToService":               path_to_svc,
                                "nodeInformation":             node_id,
                                "requestedPublishingInterval": pub_interval
                            }
                            if username:
                                entry["username"] = username
                                entry["password"] = password
                            opcua_consumers.append(entry)
                            has_opcua = True
                            route = {
                                "datasource":   cid,
                                "transformers": ["dataValueToJson", "opcua-extract-value"],
                                "datasinks":    [],
                                "trigger":      "event"
                            }
                            routes.append(route)
                            opcua_by_node[node_key] = route
                        else:
                            route = opcua_by_node[node_key]

                        sink_id = f"{asset_safe}_{sm_safe}_{prop_name}"
                        if sink_id not in sink_ids:
                            sink_ids.add(sink_id)
                            aas_sinks.append({
                                "uniqueId":         sink_id,
                                "submodelEndpoint": sm_endpoint,
                                "idShortPath":      f"{dp_smc_id_short}.{prop_name}{path_suffix}",
                                "api":              "DotAAS-V3"
                            })
                        route["datasinks"].append(sink_id)
                        influx_id = _get_influxdb_sink_id(quals, asset_safe, sm_safe, prop_name, influxdb_sinks)
                        if influx_id:
                            route["datasinks"].append(influx_id)
                        print(f"      [OPC-UA] {prop_name}  node={node_id}  pub={pub_interval}ms", flush=True)

                elif protocol == "kafka":
                    broker_url = _resolve_url(comm_cfg.get("BrokerUrl") or "kafka:9092")
                    group_id   = comm_cfg.get("GroupId") or "databridge"
                    max_poll   = safe_int(comm_cfg.get("MaxPollRecords"), 5000)
                    seek_raw   = (comm_cfg.get("SeekTo") or "latest").lower()
                    seek_to    = "END" if seek_raw == "latest" else "BEGINNING"

                    if ":" in broker_url:
                        kafka_host, kafka_port_str = broker_url.rsplit(":", 1)
                        kafka_port = safe_int(kafka_port_str, 9092)
                    else:
                        kafka_host = broker_url
                        kafka_port = 9092

                    for dp in dp_smc.get("value", []):
                        prop_name, value_elem, path_suffix = unwrap_datapoint(dp)
                        if not prop_name or value_elem is None:
                            continue
                        quals     = {**shared_sink_quals, **get_qualifiers(value_elem)}
                        topic     = quals.get("KafkaTopic")
                        if not topic:
                            print(f"      [SKIP] {prop_name}: no KafkaTopic qualifier", flush=True)
                            continue

                        json_path  = quals.get("KafkaJsonPath")
                        asset_safe = sanitize_id(asset_name)
                        cid        = f"kafka_{sanitize_id(topic)}"

                        if topic not in kafka_by_topic:
                            consumer_entry = {
                                "uniqueId":       cid,
                                "serverUrl":      kafka_host,
                                "serverPort":     kafka_port,
                                "topic":          topic,
                                "maxPollRecords": max_poll,
                                "groupId":        group_id,
                                "consumersCount": 1,
                                "seekTo":         seek_to
                            }
                            kafka_consumers.append(consumer_entry)

                            transformer = None
                            if json_path:
                                jt_id = f"extract_{cid}"
                                expr  = json_path.lstrip("$").lstrip(".")
                                if jt_id not in jsonata_ids:
                                    jsonata_transformers.append({
                                        "uniqueId":   jt_id,
                                        "queryPath":  f"{jt_id}.jsonata",
                                        "inputType":  "JsonString",
                                        "outputType": "JsonString"
                                    })
                                    jsonata_expr_files[f"{jt_id}.jsonata"] = expr
                                    jsonata_ids.add(jt_id)
                                transformer = jt_id

                            route = {"datasource": cid, "datasinks": [], "trigger": "event"}
                            if transformer:
                                route["transformers"] = [transformer]
                            routes.append(route)
                            kafka_by_topic[topic] = route
                        else:
                            route = kafka_by_topic[topic]

                        sink_id = f"{asset_safe}_{sm_safe}_{prop_name}"
                        if sink_id not in sink_ids:
                            sink_ids.add(sink_id)
                            aas_sinks.append({
                                "uniqueId":         sink_id,
                                "submodelEndpoint": sm_endpoint,
                                "idShortPath":      f"{dp_smc_id_short}.{prop_name}{path_suffix}",
                                "api":              "DotAAS-V3"
                            })
                        route["datasinks"].append(sink_id)
                        influx_id = _get_influxdb_sink_id(quals, asset_safe, sm_safe, prop_name, influxdb_sinks)
                        if influx_id:
                            route["datasinks"].append(influx_id)
                        print(f"      [KAFKA] {prop_name}  topic={topic}  path={json_path}", flush=True)

                else:
                    print(f"    [SKIP] Unknown protocol '{protocol}'", flush=True)

        print(flush=True)

    configs = {}
    if plc4x_consumers:       configs["plc4xconsumer.json"]      = plc4x_consumers
    if has_plc4x:
        configs["plc4xtransformer.json"] = [{"uniqueId": "plc4x-to-json", "autoUnbox": "true"}]

    jackson_entries = []
    if has_plc4x:
        jackson_entries.append({"uniqueId": "plc4x-to-json", "operation": "marshal", "jacksonModules": ""})
    if has_opcua:
        jackson_entries.append({"uniqueId": "dataValueToJson", "operation": "marshal",
                                 "jacksonModules": "com.fasterxml.jackson.datatype.jsr310.JavaTimeModule"})
        jsonata_transformers.append({
            "uniqueId":   "opcua-extract-value",
            "queryPath":  "opcua-extract-value.jsonata",
            "inputType":  "JsonString",
            "outputType": "JsonString"
        })
        configs["opcua-extract-value.jsonata"] = "value.value"
    if jackson_entries:
        configs["jsonjacksontransformer.json"] = jackson_entries

    if mqtt_consumers:        configs["mqttconsumer.json"]       = mqtt_consumers
    if http_consumers:        configs["httpconsumer.json"]       = http_consumers
    if opcua_consumers:       configs["opcuaconsumer.json"]      = opcua_consumers
    if kafka_consumers:       configs["kafkaconsumer.json"]      = kafka_consumers
    if influxdb_sinks:        configs["influxdbproducer.json"]   = influxdb_sinks
    if timer_consumers:       configs["timerconsumer.json"]      = list(timer_consumers.values())
    if aas_sinks:             configs["aasserver.json"]          = aas_sinks
    if routes:                configs["routes.json"]             = routes
    if jsonata_transformers:  configs["jsonatatransformer.json"] = jsonata_transformers
    configs.update(jsonata_expr_files)

    print(f"Summary: {len(routes)} routes | {len(aas_sinks)} sinks | "
          f"{len(configs)} config files", flush=True)
    return configs

def write_configs(out_dir: str, configs: dict):
    os.makedirs(out_dir, exist_ok=True)
    for filename, content in configs.items():
        path = os.path.join(out_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(content, (list, dict)):
                json.dump(content, f, indent=2)
            else:
                f.write(str(content))
        print(f"  [WRITE] {path}  ({len(content) if isinstance(content, list) else '—'})", flush=True)

def start_docker_container(config_dir: str, aas_server_url: str):
    abs_config = os.path.abspath(config_dir)
    print(f"\nStarting BaSyx DataBridge container ({DOCKER_IMAGE}) ...", flush=True)

    subprocess.run(["docker", "rm", "-f", DOCKER_CONTAINER],
                   capture_output=True)

    net_result = subprocess.run(
        ["docker", "network", "ls", "--filter", "name=basyx-network", "--format", "{{.Name}}"],
        capture_output=True, text=True
    )
    network = net_result.stdout.strip().splitlines()
    network = network[0] if network else "host"

    cmd = [
        "docker", "run", "-d",
        "--name", DOCKER_CONTAINER,
        "--network", network,
        "-v", f"{abs_config}:/usr/share/config",
        "-e", f"AAS_SERVER_URL={aas_server_url}",
        DOCKER_IMAGE
    ]
    print(f"  CMD: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  Container started: {result.stdout.strip()}", flush=True)
        return True, result.stdout.strip()
    else:
        print(f"  [ERROR] {result.stderr.strip()}", flush=True)
        return False, result.stderr.strip()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate official BaSyx DataBridge configs from AAS server"
    )
    parser.add_argument("--server",       default=AAS_SERVER_URL,
                        help="AAS server URL (default: AAS_SERVER_URL env or http://aas-env:8081)")
    parser.add_argument("--out",          default=OUTPUT_DIR,
                        help="Output directory for config files")
    parser.add_argument("--start-docker", action="store_true",
                        help="Start the official BaSyx DataBridge Docker container after generating configs")
    args = parser.parse_args()

    print("=" * 60, flush=True)
    print("generate_configuration_offbasyx", flush=True)
    print("Official BaSyx DataBridge — Config Generator", flush=True)
    print("=" * 60, flush=True)
    print(f"AAS Server : {args.server}", flush=True)
    print(f"Output dir : {args.out}",    flush=True)
    print(flush=True)

    configs = build_official_configs(args.server)

    if not configs:
        print("[WARN] No config files generated. "
              "Make sure your AAS has structured submodels with CommunicationConfiguration SMCs.",
              flush=True)
        sys.exit(1)

    write_configs(args.out, configs)
    print("\n✅ Config files written.", flush=True)

    if args.start_docker:
        ok, msg = start_docker_container(args.out, args.server)
        sys.exit(0 if ok else 1)
