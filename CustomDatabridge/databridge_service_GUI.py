# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt
import json
import time
import os
import threading
import requests
import base64
import struct
import math
import queue
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

try:
    from CustomDatabridge.features import verify_modbus_write
except ImportError:
    try:
        from features import verify_modbus_write  # type: ignore
    except ImportError:
        verify_modbus_write = None  # type: ignore

                                                                           
               
                                                                           
modbus_write_queue = queue.PriorityQueue()
mqtt_message_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="MQTT-Handler")
modbus_writer_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="Modbus-Writer")

api_stats = defaultdict(int)
api_stats_lock = threading.Lock()
api_stats_start_time = time.time()

CONFIG_DIR = "./databridge_GUI"
if not os.path.exists(CONFIG_DIR):
    CONFIG_DIR = "."

def load_json(filename):
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        print(f"[ERROR] Config file not found: {path} (PWD: {os.getcwd()})", flush=True)
        return []
    with open(path, 'r') as f:
        data = json.load(f)
        print(f"[DEBUG] Loaded {len(data)} items from {path}", flush=True)
        return data

print("Loading DataBridge configuration...", flush=True)
routes = load_json("routes.json")
datasources = load_json("datasources.json")
datasinks = load_json("datasinks.json")
transformers = load_json("transformers.json")
write_routes_raw = load_json("write_routes.json") or []

print("\n--- DataBridge Configuration Loaded (via generate_databridge_config.py) ---", flush=True)
print(f"Routes:      {len(routes)}", flush=True)
print(f"Datasources: {len(datasources)}", flush=True)
print(f"Datasinks:   {len(datasinks)}", flush=True)
print("--- Route Details ---", flush=True)

                                     
source_map = {item['uniqueId']: item for item in datasources}
sink_map = {item['uniqueId']: item for item in datasinks}

                              
log_file_path = "/app/databridge_routes.log"
with open(log_file_path, "w") as log_file:
    header = "--- Route Details (Generated) ---\n"
    print(header.strip(), flush=True)
    log_file.write(header)

    for r in routes:
        src = source_map.get(r['dataSource'])
        snk = sink_map.get(r['dataSink'])
        
        src_info = "Unknown"
        if src:
                                       
            if src.get('protocol') == 'modbus':
                src_info = f"Modbus://{src.get('host')}:{src.get('port')}/Reg{src.get('register')}"
            elif src.get('protocol') == 'mqtt':
                 src_info = f"MQTT://{src.get('topic')}"
                 
        snk_info = "Unknown"
        if snk:
                                     
            if 'aas_id_short' in snk:
                snk_info = f"AAS::{snk.get('aas_id_short')}"
            elif 'topic' in snk:
                snk_info = f"MQTT::{snk.get('topic')}"
            
                                                                            
            snk_info += " & InfluxDB"
                
        line = f"[*] {src_info}  -->  {snk_info}"
        print(line, flush=True)
        log_file.write(line + "\n")

    footer = "-----------------------------------------------------------------------\n"
    print(footer.strip(), flush=True)
    log_file.write(footer)

print(f"[INFO] Route details written to {log_file_path}", flush=True)

                                                                           
                   
                                                                           
                                                            
try:
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
                               
    mqtt_client = mqtt.Client()

mqtt_connected = False

def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    try:
        if rc == 0:
            print("Connected to MQTT Broker", flush=True)
            mqtt_connected = True
            
            print(f"[DEBUG] Processing {len(routes)} routes in on_connect subscription loop.", flush=True)
            if len(routes) > 0:
                 print(f"[DEBUG] Last Route ID: {routes[-1].get('uniqueId')}", flush=True)

            all_topics = set()
            

            for route in routes:
                if route.get('uniqueId') == 'Route_Control_Battery_Power':
                    source_chk = source_map.get(route['dataSource'])
                    sink_chk = sink_map.get(route['dataSink'])
                    print(f"[DEBUG_LOOP] Inspecting Route_Control_Battery_Power. Source: {source_chk is not None} ({route['dataSource']}), Sink: {sink_chk is not None} ({route['dataSink']})", flush=True)
                    if source_chk:
                        print(f"[DEBUG_LOOP] Source Protocol: {source_chk.get('protocol')}", flush=True)

                source = source_map.get(route['dataSource'])
                sink = sink_map.get(route['dataSink'])
                
                if source and source.get('protocol') == 'mqtt' and sink:
                    topic = source.get('topic')
                    if topic:
                        if topic not in mqtt_topic_sink_map:
                            mqtt_topic_sink_map[topic] = []
                        if sink not in mqtt_topic_sink_map[topic]:
                            mqtt_topic_sink_map[topic].append(sink)
                        
                        if topic not in all_topics:
                            all_topics.add(topic)
                            print(f"[MQTT] Subscribing to external topic: {topic}", flush=True)
                            client.subscribe(topic)
                
                elif source and source.get('protocol') == 'modbus' and sink and 'topic' in sink:
                    topic = sink['topic']
                    if topic:
                        if topic not in mqtt_topic_sink_map:
                            mqtt_topic_sink_map[topic] = []
                        if sink not in mqtt_topic_sink_map[topic]:
                            mqtt_topic_sink_map[topic].append(sink)

                        if topic not in all_topics:
                            all_topics.add(topic)
                            print(f"[MQTT] Subscribing to Modbus topic: {topic}", flush=True)
                            client.subscribe(topic)
            
            if all_topics:
                print(f"[MQTT] Subscribed to {len(all_topics)} topics for unified data ingestion", flush=True)

        else:
            print(f"Failed to connect to MQTT, return code {rc}", flush=True)

    except Exception as e:
        print(f"[CRASH] Error in on_connect: {e}", flush=True)

mqtt_client.on_connect = on_connect

                                                
mqtt_topic_sink_map = {}

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode())
        value = payload.get('value')
        
        print(f"[MQTT→] Received '{topic}': {value}", flush=True)
        
        sinks = mqtt_topic_sink_map.get(topic, [])
        if sinks and value is not None:
            for sink in sinks:
                mqtt_message_pool.submit(route_data_to_sinks_async, sink, value)
        elif not sinks:
            print(f"[MQTT→] No sink for '{topic}'", flush=True)
    except json.JSONDecodeError as e:
        print(f"[MQTT→] Invalid JSON on '{topic}': {e}", flush=True)
    except Exception as e:
        print(f"[MQTT→] Error processing '{topic}': {e}", flush=True)

mqtt_client.on_message = on_message

if datasinks:
    broker_host = datasinks[0].get('host', 'mosquitto')
    broker_port = datasinks[0].get('port', 1883)
    print(f"Connecting to MQTT Broker at {broker_host}:{broker_port}...")
    try:
        mqtt_client.connect(broker_host, broker_port)
        mqtt_client.loop_start()

        try:
            from aas_change_listener import AASChangeListener
            wr_index = {
                (r["submodelId"], r["aasIdShort"]): r
                for r in write_routes_raw
                if r.get("submodelId") and r.get("aasIdShort")
            }
            if wr_index:
                aas_url = os.getenv("AAS_SERVER_URL",
                                     "http://aas-env:8081")
                _aas_listener = AASChangeListener(
                    write_routes=wr_index,
                    aas_server_url=aas_url,
                    mqtt_client=mqtt_client,
                )
                _aas_listener.subscribe()
                print(f"[AAS_LISTEN] {len(wr_index)} write-route(s) "
                      f"registered.", flush=True)
            else:
                print("[AAS_LISTEN] no writable DataPoints — "
                      "skipping AAS-event subscription.", flush=True)
        except Exception as exc:
            print(f"[AAS_LISTEN] init failed: {exc}", flush=True)
        
                                                                                         
                                                                             
        all_topics = set()
        
        for route in routes:
            source = source_map.get(route['dataSource'])
            sink = sink_map.get(route['dataSink'])
            
                                                   
            if source and source.get('protocol') == 'mqtt' and sink:
                topic = source.get('topic')
                if topic:
                    if topic not in mqtt_topic_sink_map:
                        mqtt_topic_sink_map[topic] = []
                    mqtt_topic_sink_map[topic].append(sink)
                    
                    if topic not in all_topics:
                        all_topics.add(topic)
                        print(f"[MQTT] Subscribing to external topic: {topic}", flush=True)
                        mqtt_client.subscribe(topic)
            
                                                               
                                                                   
            elif source and source.get('protocol') == 'modbus' and sink and 'topic' in sink:
                topic = sink['topic']
                if topic:
                    if topic not in mqtt_topic_sink_map:
                        mqtt_topic_sink_map[topic] = []
                    mqtt_topic_sink_map[topic].append(sink)

                    if topic not in all_topics:
                        all_topics.add(topic)
                        print(f"[MQTT] Subscribing to Modbus topic: {topic}", flush=True)
                        mqtt_client.subscribe(topic)
        
        if mqtt_topic_sink_map:
            print(f"[MQTT] Subscribed to {len(all_topics)} topics for unified data ingestion", flush=True)
        
    except Exception as e:
        print(f"Error connecting to MQTT: {e}")

                                                                           
                       
                                                                           
INFLUX_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUX_ORG = os.getenv("INFLUXDB_ORG")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET", "hems")

influx_client = None
write_api = None

if INFLUX_TOKEN and INFLUX_ORG:
    try:
        influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        write_api = influx_client.write_api(write_options=SYNCHRONOUS)
        print(f"Connected to InfluxDB at {INFLUX_URL} (Org: {INFLUX_ORG}, Bucket: {INFLUX_BUCKET})")
    except Exception as e:
        print(f"Error connecting to InfluxDB: {e}")

                                                                           
                  
                                                                           

                         
modbus_clients = {}
modbus_locks = {}
clients_lock = threading.Lock()

def get_modbus_client(host, port):
    key = f"{host}:{port}"
    with clients_lock:
        if key not in modbus_clients:
                                               
            client = ModbusTcpClient(host, port=port, timeout=1.0)
            if client.connect():
                 modbus_clients[key] = client
                 modbus_locks[key] = threading.Lock()
            else:
                modbus_clients[key] = client
                modbus_locks[key] = threading.Lock()
        return modbus_clients[key], modbus_locks[key]

def safe_float(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(',', '.'))
        except ValueError:
            pass
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def update_aas(sink, value):
    try:
        sm_id = sink.get('aas_submodel_id')
        id_short = sink.get('aas_id_short')
        
        if not sm_id or not id_short:
            return

        encoded_id = base64.urlsafe_b64encode(sm_id.encode()).decode().rstrip("=")
        server_url = os.getenv("AAS_SERVER_URL", "http://aas-env:8081")
        url_elm = f"{server_url}/submodels/{encoded_id}/submodel-elements/{id_short}"
        
        resp_get = requests.get(url_elm, timeout=2.0)
        print(f"[AAS_API] GET {url_elm} → {resp_get.status_code}", flush=True)
        
        with api_stats_lock:
            api_stats['aas_get'] += 1
        
        if resp_get.status_code == 200:
            element_data = resp_get.json()
            
            value_type = element_data.get("valueType", "xs:string")
            is_numeric_type = value_type in ["xs:float", "xs:double", "xs:int", "xs:integer", "xs:long", "xs:short", "xs:byte"]
            
            if is_numeric_type:
               try:
                   element_data["value"] = safe_float(value)
               except:
                   element_data["value"] = value
            elif value_type == "xs:boolean":
                 element_data["value"] = bool(value)
            else:
                element_data["value"] = str(value)

            headers = {"Content-Type": "application/json"}
            resp_put = requests.put(url_elm, json=element_data, headers=headers, timeout=2.0)
            print(f"[AAS_API] PUT {url_elm} → {resp_put.status_code} (value={value}, type={value_type})", flush=True)
            
            with api_stats_lock:
                api_stats['aas_put'] += 1
                if resp_put.status_code == 200:
                    api_stats['aas_put_success'] += 1
                else:
                    api_stats['aas_put_failed'] += 1
        else:
            print(f"[AAS_API] GET Failed for {id_short}: {resp_get.status_code}", flush=True)
            with api_stats_lock:
                api_stats['aas_get_failed'] += 1
             
    except Exception as e:
        print(f"[AAS_API] Error updating AAS: {e}", flush=True)
        with api_stats_lock:
            api_stats['aas_errors'] += 1

def write_to_influx(sink, value):
    if not write_api:
        return
    try:
        sensor_id = sink.get('aas_id_short', 'unknown')
        
        topic = sink.get('topic', '')
        asset_name = 'unknown'
        if topic.startswith('aas/'):
             parts = topic.split('/')
             if len(parts) >= 3:
                 asset_name = parts[1]
        
        bucket      = sink.get('influx_database')      or INFLUX_BUCKET
        org         = sink.get('influx_org')           or INFLUX_ORG
        measurement = sink.get('influx_measurement')   or "telemetry"

        point = Point(measurement) \
            .tag("sensor_id", sensor_id) \
            .tag("asset", asset_name) \
            .field("value", safe_float(value))

        write_api.write(bucket=bucket, org=org, record=point)

        print(f"[INFLUX_API] WRITE bucket={bucket} measurement={measurement} "
              f"tags={{sensor_id={sensor_id}, asset={asset_name}}} "
              f"fields={{value={value}}} → SUCCESS", flush=True)

        with api_stats_lock:
            api_stats['influx_write'] += 1
            api_stats['influx_write_success'] += 1

    except Exception as e:
        print(f"[INFLUX_API] WRITE → FAILED: {e}", flush=True)
        with api_stats_lock:
            api_stats['influx_write'] += 1
            api_stats['influx_write_failed'] += 1

def write_to_modbus(sink, value):
    try:
        host = sink.get('host')
        port = sink.get('port')
        register = sink.get('register')
        slave_id = sink.get('slave_id', 1)
        data_type = sink.get('dataType', 'float32')

        if not host or not port or register is None:
            print(f"[MODBUS_API] Missing config in sink: {sink['uniqueId']}", flush=True)
            return

        client, lock = get_modbus_client(host, port)
        with lock:
            if client:
                if data_type == 'int16':
                     builder = struct.pack('>h', int(safe_float(value)))
                     registers = struct.unpack('>H', builder)
                     client.write_registers(register, registers, device_id=slave_id)
                     written_scalar = int(safe_float(value))
                else:
                     builder = struct.pack('>f', safe_float(value))
                     registers = struct.unpack('>HH', builder)
                     client.write_registers(register, registers, device_id=slave_id)
                     written_scalar = safe_float(value)

                print(f"[MODBUS_API] WRITE {host}:{port} reg={register} slave={slave_id} type={data_type} value={value} → SUCCESS", flush=True)

                with api_stats_lock:
                    api_stats['modbus_write'] += 1
                    api_stats['modbus_write_success'] += 1

                if sink.get('verifyWriteBack') and verify_modbus_write is not None:
                    tol = float(sink.get('verifyTolerance', 0.001))
                    delay_s = float(sink.get('verifyReadbackDelayMs', 20)) / 1000.0
                    result = verify_modbus_write(
                        client,
                        register=register,
                        slave_id=slave_id,
                        data_type=data_type,
                        written_value=written_scalar,
                        tolerance=tol,
                        readback_delay_s=delay_s,
                    )
                    sink['lastWriteVerification'] = result.as_dict()
                    print(f"[MODBUS_VERIFY] {result.format()}", flush=True)
                    with api_stats_lock:
                        api_stats[f'modbus_verify_{result.status.lower()}'] += 1
            else:
                print(f"[MODBUS_API] WRITE {host}:{port} → FAILED: Client not connected", flush=True)
                with api_stats_lock:
                    api_stats['modbus_write'] += 1
                    api_stats['modbus_write_failed'] += 1

    except Exception as e:
        print(f"[MODBUS_API] WRITE {host}:{port} reg={register} → FAILED: {e}", flush=True)
        with api_stats_lock:
            api_stats['modbus_write'] += 1
            api_stats['modbus_write_failed'] += 1

def write_to_modbus_priority(sink, value, priority=5):
    timestamp = time.time()
    modbus_write_queue.put((priority, timestamp, sink, value))

def modbus_writer_worker():
    print("[ModbusWriter] Worker started", flush=True)
    while True:
        try:
            priority, timestamp, sink, value = modbus_write_queue.get(timeout=1.0)
            age = time.time() - timestamp
            print(f"[ModbusWriter] Processing (age={age:.2f}s, p={priority})", flush=True)
            write_to_modbus(sink, value)
            modbus_write_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[ModbusWriter] Error: {e}", flush=True)

def write_to_opcua(sink, value):
    server_url = sink.get('server', '')
    node_id    = sink.get('node_id', '')
    if not server_url or not node_id:
        print(f"[OPCUA_WRITE] Missing server/node_id in sink: {sink.get('uniqueId')}", flush=True)
        return
    try:
        from asyncua.sync import ua
        client = _get_opcua_client(server_url)
        if client is None:
            return
        node = client.get_node(node_id)
        try:
            current_variant = node.read_data_value().Value
            dv = ua.DataValue(ua.Variant(type(current_variant.Value)(value), current_variant.VariantType))
        except Exception:
            dv = ua.DataValue(ua.Variant(float(value), ua.VariantType.Float))
        node.write_value(dv)
        print(f"[OPCUA_WRITE] {server_url} node={node_id} value={value} → SUCCESS", flush=True)
        with api_stats_lock:
            api_stats.setdefault('opcua_write', 0)
            api_stats.setdefault('opcua_write_success', 0)
            api_stats['opcua_write'] += 1
            api_stats['opcua_write_success'] += 1
    except Exception as exc:
        print(f"[OPCUA_WRITE] {server_url} node={node_id} → FAILED: {exc}", flush=True)
        with _opcua_lock:
            _opcua_clients.pop(server_url, None)
        with api_stats_lock:
            api_stats.setdefault('opcua_write', 0)
            api_stats.setdefault('opcua_write_failed', 0)
            api_stats['opcua_write'] += 1
            api_stats['opcua_write_failed'] += 1

def write_to_http(sink, value):
    url    = sink.get('url', '')
    method = sink.get('http_method', 'PUT').upper()
    if not url:
        print(f"[HTTP_WRITE] Missing url in sink: {sink.get('uniqueId')}", flush=True)
        return
    try:
        import requests as _requests
        resp = _requests.request(method, url, json={"value": value}, timeout=5)
        resp.raise_for_status()
        print(f"[HTTP_WRITE] {method} {url} value={value} → {resp.status_code}", flush=True)
        with api_stats_lock:
            api_stats.setdefault('http_write', 0)
            api_stats.setdefault('http_write_success', 0)
            api_stats['http_write'] += 1
            api_stats['http_write_success'] += 1
    except Exception as exc:
        print(f"[HTTP_WRITE] {method} {url} → FAILED: {exc}", flush=True)
        with api_stats_lock:
            api_stats.setdefault('http_write', 0)
            api_stats.setdefault('http_write_failed', 0)
            api_stats['http_write'] += 1
            api_stats['http_write_failed'] += 1

def route_data_to_sinks_async(sink, value):
    value = _apply_transform(value, sink)
    if 'aas_submodel_id' in sink:
        update_aas(sink, value)

    if sink.get('protocol') == 'modbus' or sink.get('type') == 'modbus':
        write_to_modbus_priority(sink, value, priority=1)
    elif sink.get('protocol') == 'opcua':
        write_to_opcua(sink, value)
    elif sink.get('protocol') == 'http':
        write_to_http(sink, value)
    elif sink.get('protocol') == 'bacnet':
        write_to_bacnet(sink, value)
    elif sink.get('protocol') == 'ocpp':
        write_to_ocpp(sink, value)
    elif sink.get('protocol') == 'dlms':
        write_to_dlms(sink, value)

    write_to_influx(sink, value)

def _apply_transform(value, sink):
    formula = (sink.get('transform_formula') or '').strip()
    if not formula:
        return value
    if 'x' not in formula:
        print(f"[TRANSFORM] formula={formula!r} fehlt 'x' — Rohwert wird unveraendert weitergeleitet",
              flush=True)
        return value
    try:
        _math_ctx = {
            'x': value,
            'sqrt': math.sqrt, 'log': math.log, 'log10': math.log10,
            'log2': math.log2, 'exp': math.exp, 'pow': math.pow,
            'abs': abs, 'round': round,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
            'atan2': math.atan2,
            'degrees': math.degrees, 'radians': math.radians,
            'floor': math.floor, 'ceil': math.ceil,
            'pi': math.pi, 'e': math.e,
        }
        result = eval(formula, {'__builtins__': {}}, _math_ctx)
        return round(float(result), 6)
    except Exception as exc:
        print(f"[TRANSFORM] formula={formula!r} x={value} Fehler: {exc}", flush=True)
        return value

def route_data_to_sinks(sink, value):

    value = _apply_transform(value, sink)

    if 'aas_submodel_id' in sink:
        update_aas(sink, value)

    ext_topic  = sink.get('external_mqtt_topic')
    ext_broker = sink.get('external_mqtt_broker')
    if ext_topic and ext_broker:
        try:
            payload = json.dumps({"value": value, "timestamp": time.time()})
            if ext_broker in ('mosquitto', 'localhost', '127.0.0.1'):
                mqtt_client.publish(ext_topic, payload)
                print(f"[EXT_MQTT] PUBLISH topic={ext_topic} value={value}", flush=True)
            else:
                try:
                    ext_client = mqtt.Client()
                    ext_client.connect(ext_broker, 1883, keepalive=5)
                    ext_client.publish(ext_topic, payload)
                    ext_client.disconnect()
                    print(f"[EXT_MQTT] PUBLISH {ext_broker}/{ext_topic} value={value}", flush=True)
                except Exception as e:
                    print(f"[EXT_MQTT] Error publishing to {ext_broker}: {e}", flush=True)
        except Exception as e:
            print(f"[EXT_MQTT] Error: {e}", flush=True)

    proto = sink.get('protocol') or sink.get('type') or ''
    if proto == 'modbus':
        write_to_modbus(sink, value)
    elif proto == 'opcua':
        write_to_opcua(sink, value)
    elif proto == 'http':
        write_to_http(sink, value)
    elif proto == 'bacnet':
        write_to_bacnet(sink, value)
    elif proto == 'ocpp':
        write_to_ocpp(sink, value)
    elif proto == 'dlms':
        write_to_dlms(sink, value)

    if sink.get('enable_influx', False):
        write_to_influx(sink, value)

                                                                           
                   
                                                                           

def process_route(route):
    try:
        source = source_map.get(route['dataSource'])
        sink = sink_map.get(route['dataSink'])
        
        if source and source.get('protocol') == 'modbus':
            val = None
            try:
                client, lock = get_modbus_client(source['host'], source['port'])
                
                with lock:
                    if client:
                        address = source['register']
                        slave = source.get('slave_id', 1)
                        is_input = (source.get('register_type') == 'input')
                        data_type = source.get('dataType', 'float32')
                        
                        count = 2
                        if data_type in ['int16', 'uint16']:
                            count = 1
                        elif data_type in ['float64', 'int64', 'uint64']:
                            count = 4

                        rr = None
                        if is_input:
                            rr = client.read_input_registers(address, count=count, device_id=slave)
                        else:
                            rr = client.read_holding_registers(address, count=count, device_id=slave)
                        
                        if rr and not rr.isError():
                            if data_type == 'float32':
                                raw = struct.pack('>HH', rr.registers[0], rr.registers[1])
                                val = struct.unpack('>f', raw)[0]
                            elif data_type == 'int16':
                                val = float(rr.registers[0])
                            elif data_type == 'uint16':
                                val = float(rr.registers[0])
                            elif data_type == 'int32':
                                raw = struct.pack('>HH', rr.registers[0], rr.registers[1])
                                val = float(struct.unpack('>i', raw)[0])
                            elif data_type == 'float64':
                                raw = struct.pack('>HHHH', rr.registers[0], rr.registers[1], rr.registers[2], rr.registers[3])
                                val = struct.unpack('>d', raw)[0]
                            else:
                                raw = struct.pack('>HH', rr.registers[0], rr.registers[1])
                                val = struct.unpack('>f', raw)[0]

                            val = round(val, 2)
                            
                            with api_stats_lock:
                                api_stats['modbus_read'] += 1
                                api_stats['modbus_read_success'] += 1
            except Exception as e:
                with api_stats_lock:
                    api_stats['modbus_read'] += 1
                    api_stats['modbus_read_failed'] += 1

            if val is not None:
                topic = sink['topic']
                payload = json.dumps({"value": val, "timestamp": time.time()})
                mqtt_client.publish(topic, payload)

                print(f"[MQTT_API] PUBLISH topic={topic} payload={{value={val}}}", flush=True)

                with api_stats_lock:
                    api_stats['mqtt_publish'] += 1

                route_data_to_sinks(sink, val)

        elif source and source.get('protocol') == 'http':
            val = _poll_http(source)
            if val is not None:
                topic = sink['topic']
                mqtt_client.publish(
                    topic,
                    json.dumps({"value": val, "timestamp": time.time()}),
                )
                print(f"[HTTP_API] {source.get('url')} "
                      f"json_path={source.get('json_path')!r}  → {val}  "
                      f"→ MQTT {topic}", flush=True)
                with api_stats_lock:
                    api_stats['http_read'] += 1
                    api_stats['http_read_success'] += 1
                    api_stats['mqtt_publish'] += 1
                route_data_to_sinks(sink, val)

        elif source and source.get('protocol') == 'opcua':
            val = _poll_opcua(source)
            if val is not None:
                topic = sink['topic']
                mqtt_client.publish(
                    topic,
                    json.dumps({"value": val, "timestamp": time.time()}),
                )
                print(f"[OPCUA] node={source.get('node_id')} → {val} "
                      f"→ MQTT {topic}", flush=True)
                route_data_to_sinks(sink, val)

        elif source and source.get('protocol') == 'bacnet':
            val = _poll_bacnet(source)
            if val is not None:
                topic = sink['topic']
                mqtt_client.publish(topic, json.dumps({"value": val, "timestamp": time.time()}))
                print(f"[BACNET] {source.get('object_id')} → {val} → MQTT {topic}", flush=True)
                route_data_to_sinks(sink, val)

        elif source and source.get('protocol') == 'ocpp':
            val = _poll_ocpp(source)
            if val is not None:
                topic = sink['topic']
                mqtt_client.publish(topic, json.dumps({"value": val, "timestamp": time.time()}))
                print(f"[OCPP] CP={source.get('charge_point_id')} "
                      f"measurand={source.get('measurand')} → {val} → MQTT {topic}", flush=True)
                route_data_to_sinks(sink, val)

        elif source and source.get('protocol') == 'dlms':
            val = _poll_dlms(source)
            if val is not None:
                topic = sink['topic']
                mqtt_client.publish(topic, json.dumps({"value": val, "timestamp": time.time()}))
                print(f"[DLMS] OBIS={source.get('obis_code')} → {val} → MQTT {topic}", flush=True)
                route_data_to_sinks(sink, val)

    except Exception as e:
        print(f"Error processing route {route['uniqueId']}: {e}", flush=True)

try:
    from http_auth_polling import poll_http as _auth_poll_http
except Exception as _exc:
    _auth_poll_http = None
    print(f"[HTTP_API] auth-polling module not loaded: {_exc}", flush=True)

_opcua_clients: dict = {}
_opcua_lock = threading.Lock()

def _get_opcua_client(server_url: str):
    with _opcua_lock:
        if server_url in _opcua_clients:
            return _opcua_clients[server_url]
        try:
            from asyncua.sync import Client as _OpcuaClient
            client = _OpcuaClient(url=server_url)
            client.connect()
            _opcua_clients[server_url] = client
            print(f"[OPCUA] Connected to {server_url}", flush=True)
            return client
        except Exception as exc:
            print(f"[OPCUA] Connection failed {server_url}: {exc}", flush=True)
            return None

def _poll_opcua(source: dict):
    server_url = source.get('server', '')
    node_id    = source.get('node_id', '')
    if not server_url or not node_id:
        return None
    try:
        client = _get_opcua_client(server_url)
        if client is None:
            return None
        node = client.get_node(node_id)
        val  = node.read_value()
        return round(float(val), 6)
    except Exception as exc:
        print(f"[OPCUA] Read error node={node_id} server={server_url}: {exc}",
              flush=True)
        with _opcua_lock:
            _opcua_clients.pop(server_url, None)
        return None

def _kafka_consumer_loop(source: dict, sink: dict):
    broker    = source.get('broker', 'kafka:9092')
    topic     = source.get('topic', '')
    group_id  = source.get('group_id', 'databridge')
    json_path = (source.get('json_path') or '').strip().lstrip('$').lstrip('.')
    seek_to   = source.get('seek_to', 'latest')
    sec_proto = source.get('security_protocol', 'PLAINTEXT')

    if not topic:
        print(f"[KAFKA] No topic in source {source.get('uniqueId')}", flush=True)
        return

    while True:
        try:
            from kafka import KafkaConsumer
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=[broker],
                group_id=group_id,
                auto_offset_reset=seek_to if seek_to in ('latest', 'earliest') else 'latest',
                security_protocol=sec_proto,
                value_deserializer=lambda m: m.decode('utf-8', errors='replace'),
            )
            print(f"[KAFKA] Consumer ready: topic={topic} broker={broker}", flush=True)
            for msg in consumer:
                try:
                    raw = msg.value
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        data = raw
                    val = data
                    if json_path and isinstance(data, dict):
                        for part in json_path.split('.'):
                            if part and isinstance(val, dict):
                                val = val.get(part)
                            else:
                                val = None
                                break
                    if val is not None:
                        try:
                            val = float(val)
                        except (TypeError, ValueError):
                            continue
                        topic_out = sink.get('topic', '')
                        mqtt_client.publish(
                            topic_out,
                            json.dumps({"value": val, "timestamp": time.time()}),
                        )
                        route_data_to_sinks(sink, val)
                except Exception as exc:
                    print(f"[KAFKA] Message error topic={topic}: {exc}", flush=True)
        except Exception as exc:
            print(f"[KAFKA] Consumer error (retry in 10s) topic={topic}: {exc}",
                  flush=True)
            time.sleep(10)

def _start_kafka_consumers():
    kafka_pairs = [
        (source_map[r['dataSource']], sink_map[r['dataSink']])
        for r in routes
        if (r.get('dataSource') in source_map
            and source_map[r['dataSource']].get('protocol') == 'kafka'
            and r.get('dataSink') in sink_map)
    ]
    if not kafka_pairs:
        return
    try:
        import kafka  # noqa: F401
    except ImportError:
        print("[KAFKA] kafka-python not installed — Kafka routes skipped", flush=True)
        return
    for src, snk in kafka_pairs:
        t = threading.Thread(
            target=_kafka_consumer_loop, args=(src, snk),
            daemon=True, name=f"Kafka-{src.get('topic', 'unknown')}",
        )
        t.start()
        print(f"[KAFKA] Started consumer thread: topic={src.get('topic')} "
              f"broker={src.get('broker')}", flush=True)

def _poll_http(source: dict):
    if _auth_poll_http is None:
        return None
    val = _auth_poll_http(source)
    if val is None:
        with api_stats_lock:
            api_stats['http_read'] += 1
            api_stats['http_read_failed'] += 1
        return None
    with api_stats_lock:
        api_stats['http_read'] += 1
        api_stats['http_read_success'] += 1
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return None

def _poll_bacnet(source: dict):
    host    = source.get('host', '')
    port    = source.get('port', 47808)
    obj_id  = source.get('object_id', '')
    _raw_prop = source.get('property_id', 'presentValue') or 'presentValue'
    prop_id = _raw_prop[0].lower() + _raw_prop[1:]
    if not host or not obj_id:
        return None
    try:
        import asyncio, concurrent.futures
        async def _read():
            from bacpypes3.ipv4.app import NormalApplication
            from bacpypes3.app import DeviceObject
            from bacpypes3.pdu import IPv4Address
            device = DeviceObject(
                objectIdentifier=("device", 599),
                objectName="DataBridgeClient",
                maxApduLengthAccepted=1024,
                segmentationSupported="noSegmentation",
            )
            local_addr = IPv4Address("0.0.0.0")
            app = NormalApplication(device, local_addr)
            try:
                await asyncio.sleep(0.3)
                result = await app.read_property(
                    f"{host}:{port}", obj_id, prop_id
                )
                val = result[0] if isinstance(result, (tuple, list)) else result
                return float(val)
            finally:
                app.close()
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            return round(pool.submit(asyncio.run, _read()).result(timeout=10), 6)
    except ImportError:
        print("[BACNET] bacpypes3 not installed — pip install bacpypes3", flush=True)
        return None
    except Exception as exc:
        print(f"[BACNET] Read {host}:{port} {obj_id}.{prop_id} failed: {exc}", flush=True)
        return None

def write_to_bacnet(sink, value):
    host    = sink.get('host', '')
    port    = sink.get('port', 47808)
    obj_id  = sink.get('object_id', '')
    prop_id = sink.get('property_id', 'presentValue')
    if not host or not obj_id:
        print(f"[BACNET_WRITE] Missing host/object_id in sink: {sink.get('uniqueId')}", flush=True)
        return
    try:
        import asyncio, concurrent.futures
        async def _write():
            from bacpypes3.ipv4.app import NormalApplication
            from bacpypes3.app import DeviceObject
            from bacpypes3.pdu import IPv4Address
            device = DeviceObject(
                objectIdentifier=("device", 599),
                objectName="DataBridgeClient",
                maxApduLengthAccepted=1024,
                segmentationSupported="noSegmentation",
            )
            local_addr = IPv4Address("0.0.0.0")
            app = NormalApplication(device, local_addr)
            try:
                await asyncio.sleep(0.3)
                await app.write_property(
                    f"{host}:{port}", obj_id,
                    prop_id, float(value), priority=8,
                )
            finally:
                app.close()
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            pool.submit(asyncio.run, _write()).result(timeout=10)
        print(f"[BACNET_WRITE] {host}:{port} {obj_id}.{prop_id} = {value} → SUCCESS", flush=True)
        with api_stats_lock:
            api_stats.setdefault('bacnet_write', 0); api_stats.setdefault('bacnet_write_success', 0)
            api_stats['bacnet_write'] += 1;          api_stats['bacnet_write_success'] += 1
    except ImportError:
        print("[BACNET_WRITE] bacpypes3 not installed", flush=True)
    except Exception as exc:
        print(f"[BACNET_WRITE] {host}:{port} {obj_id} → FAILED: {exc}", flush=True)
        with api_stats_lock:
            api_stats.setdefault('bacnet_write', 0); api_stats.setdefault('bacnet_write_failed', 0)
            api_stats['bacnet_write'] += 1;          api_stats['bacnet_write_failed'] += 1

OCPP_CS_PORT     = int(os.getenv("OCPP_CS_PORT", "9000"))
_ocpp_cs_cache:  dict = {}
_ocpp_cs_lock    = threading.Lock()
_ocpp_cp_conns:  dict = {}
_ocpp_cs_loop    = None
_ocpp_cs_started = False

def _ensure_ocpp_cs_started():
    global _ocpp_cs_started, _ocpp_cs_loop
    if _ocpp_cs_started:
        return
    _ocpp_cs_started = True

    async def _on_connect(websocket, path):
        cp_id = path.strip("/") or "unknown"
        try:
            from ocpp.v16 import ChargePoint
            from ocpp.routing import on
            from ocpp.v16 import call_result
            from ocpp.v16.enums import Action, RegistrationStatus, AuthorizationStatus
            from datetime import datetime as _dt

            class _CS(ChargePoint):
                @on(Action.BootNotification)
                def on_boot(self, **kwargs):
                    return call_result.BootNotificationPayload(
                        current_time=_dt.utcnow().isoformat(),
                        interval=10, status=RegistrationStatus.accepted,
                    )
                @on(Action.Heartbeat)
                def on_heartbeat(self, **kwargs):
                    return call_result.HeartbeatPayload(current_time=_dt.utcnow().isoformat())
                @on(Action.MeterValues)
                def on_meter_values(self, connector_id, meter_value, **kwargs):
                    for mv in meter_value:
                        for sv in mv.get("sampledValue", []):
                            k = (self.id, sv.get("measurand", ""), sv.get("phase", ""))
                            try:
                                with _ocpp_cs_lock:
                                    _ocpp_cs_cache[k] = float(sv["value"])
                            except Exception:
                                pass
                    return call_result.MeterValuesPayload()
                @on(Action.StatusNotification)
                def on_status(self, **kwargs):
                    return call_result.StatusNotificationPayload()
                @on(Action.Authorize)
                def on_authorize(self, **kwargs):
                    from ocpp.v16.datatypes import IdTagInfo
                    return call_result.AuthorizePayload(
                        id_tag_info=IdTagInfo(status=AuthorizationStatus.accepted)
                    )
                @on(Action.StartTransaction)
                def on_start_tx(self, **kwargs):
                    from ocpp.v16.datatypes import IdTagInfo
                    return call_result.StartTransactionPayload(
                        transaction_id=1,
                        id_tag_info=IdTagInfo(status=AuthorizationStatus.accepted),
                    )
                @on(Action.StopTransaction)
                def on_stop_tx(self, **kwargs):
                    return call_result.StopTransactionPayload()

            cp = _CS(cp_id, websocket)
            with _ocpp_cs_lock:
                _ocpp_cp_conns[cp_id] = cp
            print(f"[OCPP_CS] CP connected: {cp_id}", flush=True)
            try:
                await cp.start()
            finally:
                with _ocpp_cs_lock:
                    _ocpp_cp_conns.pop(cp_id, None)
                print(f"[OCPP_CS] CP disconnected: {cp_id}", flush=True)
        except Exception as exc:
            print(f"[OCPP_CS] Handler error {cp_id}: {exc}", flush=True)

    async def _server_loop():
        global _ocpp_cs_loop
        try:
            import websockets
            async with websockets.serve(
                _on_connect, "0.0.0.0", OCPP_CS_PORT,
                subprotocols=["ocpp1.6"],
            ):
                print(f"[OCPP_CS] Central System listening on port {OCPP_CS_PORT}", flush=True)
                await asyncio.Event().wait()
        except Exception as exc:
            print(f"[OCPP_CS] Server error: {exc}", flush=True)

    def _run():
        global _ocpp_cs_loop
        import asyncio
        _ocpp_cs_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_ocpp_cs_loop)
        _ocpp_cs_loop.run_until_complete(_server_loop())

    t = threading.Thread(target=_run, daemon=True, name="ocpp-cs")
    t.start()

    try:
        import aas_change_listener as _acl
        _acl._ocpp_write_proxy = write_to_ocpp
    except Exception:
        pass

def _poll_ocpp(source: dict):
    _ensure_ocpp_cs_started()
    key = (source.get('charge_point_id', ''), source.get('measurand', ''), source.get('phase', ''))
    with _ocpp_cs_lock:
        return _ocpp_cs_cache.get(key)

def write_to_ocpp(sink, value):
    _ensure_ocpp_cs_started()
    cp_id   = sink.get('charge_point_id', '')
    command = (sink.get('ocpp_command') or 'ChangeConfiguration').strip()
    key     = (sink.get('ocpp_config_key') or 'MaxChargingCurrentSoftLimit').strip()

    with _ocpp_cs_lock:
        cp = _ocpp_cp_conns.get(cp_id)
    if cp is None:
        print(f"[OCPP_WRITE] CP '{cp_id}' not connected", flush=True)
        return

    try:
        import asyncio
        from ocpp.v16 import call

        async def _send():
            if command == 'ChangeConfiguration':
                await cp.call(call.ChangeConfigurationPayload(key=key, value=str(value)))
            elif command == 'SetChargingProfile':
                from ocpp.v16.datatypes import ChargingProfile, ChargingSchedule, ChargingSchedulePeriod
                from ocpp.v16.enums import ChargingProfileKindType, ChargingRateUnitType
                sched = ChargingSchedule(
                    charging_rate_unit=ChargingRateUnitType.amps,
                    charging_schedule_period=[ChargingSchedulePeriod(start_period=0, limit=float(value))],
                )
                profile = ChargingProfile(
                    charging_profile_id=1, stack_level=0,
                    charging_profile_purpose="TxDefaultProfile",
                    charging_profile_kind=ChargingProfileKindType.absolute,
                    charging_schedule=sched,
                )
                await cp.call(call.SetChargingProfilePayload(connector_id=0, cs_charging_profiles=profile))

        if _ocpp_cs_loop and not _ocpp_cs_loop.is_closed():
            asyncio.run_coroutine_threadsafe(_send(), _ocpp_cs_loop).result(timeout=5)
            print(f"[OCPP_WRITE] CP={cp_id} {command} key={key} value={value} → OK", flush=True)
            with api_stats_lock:
                api_stats.setdefault('ocpp_write', 0); api_stats.setdefault('ocpp_write_success', 0)
                api_stats['ocpp_write'] += 1;          api_stats['ocpp_write_success'] += 1
    except ImportError:
        print("[OCPP_WRITE] ocpp library not installed — pip install ocpp websockets", flush=True)
    except Exception as exc:
        print(f"[OCPP_WRITE] CP={cp_id} {command} → FAILED: {exc}", flush=True)
        with api_stats_lock:
            api_stats.setdefault('ocpp_write', 0); api_stats.setdefault('ocpp_write_failed', 0)
            api_stats['ocpp_write'] += 1;          api_stats['ocpp_write_failed'] += 1

def _dlms_session(host, port, client_id, logical_device, auth_level, password, action):
    try:
        from gurux_dlms import GXDLMSClient, GXReplyData
        from gurux_net import GXNet, NetworkType
        from gurux_dlms.enums import InterfaceType, Authentication
    except ImportError:
        raise RuntimeError("gurux-dlms / gurux-net not installed — pip install gurux-dlms gurux-net")

    auth_map = {"none": Authentication.NONE, "low": Authentication.LOW, "high": Authentication.HIGH}
    auth = auth_map.get((auth_level or "none").lower(), Authentication.NONE)

    media  = GXNet(NetworkType.TCP, host, int(port))
    client = GXDLMSClient(True, int(client_id), int(logical_device or 1),
                          auth, password or None, InterfaceType.WRAPPER)
    try:
        media.open()
        reply = GXReplyData()
        for pdu in client.aareRequest():
            media.send(pdu)
        media.receive(reply)
        client.parseAareResponse(reply.data)
        reply.clear()
        return action(client, media)
    finally:
        try:
            for pdu in client.releaseRequest():
                media.send(pdu)
        except Exception:
            pass
        media.close()

def _poll_dlms(source: dict):
    host      = source.get('host', '')
    port      = source.get('port', 4059)
    obis      = source.get('obis_code', '')
    attribute = int(source.get('attribute', 2))
    if not host or not obis:
        return None
    try:
        def _read(client, media):
            from gurux_dlms.objects import GXDLMSData
            from gurux_dlms import GXReplyData
            obj = GXDLMSData(obis)
            reply = GXReplyData()
            for pdu in client.read(obj, attribute):
                media.send(pdu)
                reply.clear()
                media.receive(reply)
            client.updateValue(obj, attribute, client.parseGetResponse(reply.data))
            return obj.value

        val = _dlms_session(host, port,
                            source.get('client_id', 16), source.get('logical_device', 1),
                            source.get('auth_level', 'none'), source.get('password', ''),
                            _read)
        return round(float(val), 6) if val is not None else None
    except Exception as exc:
        print(f"[DLMS] Read {host}:{port} OBIS={obis} failed: {exc}", flush=True)
        return None

def write_to_dlms(sink, value):
    host      = sink.get('host', '')
    port      = sink.get('port', 4059)
    obis      = sink.get('obis_code', '')
    attribute = int(sink.get('attribute', 2))
    if not host or not obis:
        print(f"[DLMS_WRITE] Missing host/obis in sink: {sink.get('uniqueId')}", flush=True)
        return
    try:
        def _write(client, media):
            from gurux_dlms.objects import GXDLMSData
            from gurux_dlms import GXReplyData
            obj = GXDLMSData(obis)
            obj.value = float(value)
            reply = GXReplyData()
            for pdu in client.write(obj, attribute):
                media.send(pdu)
                reply.clear()
                media.receive(reply)

        _dlms_session(host, port,
                      sink.get('client_id', 16), sink.get('logical_device', 1),
                      sink.get('auth_level', 'none'), sink.get('password', ''),
                      _write)
        print(f"[DLMS_WRITE] {host}:{port} OBIS={obis} = {value} → SUCCESS", flush=True)
        with api_stats_lock:
            api_stats.setdefault('dlms_write', 0); api_stats.setdefault('dlms_write_success', 0)
            api_stats['dlms_write'] += 1;          api_stats['dlms_write_success'] += 1
    except Exception as exc:
        print(f"[DLMS_WRITE] {host}:{port} OBIS={obis} → FAILED: {exc}", flush=True)
        with api_stats_lock:
            api_stats.setdefault('dlms_write', 0); api_stats.setdefault('dlms_write_failed', 0)
            api_stats['dlms_write'] += 1;          api_stats['dlms_write_failed'] += 1

def poll_loop():
                                               
                                                                                  
    read_pool = ThreadPoolExecutor(max_workers=5)
    print("Parallel Modbus Poller started with 5 workers.", flush=True)

    while True:
                                       
        futures = [read_pool.submit(process_route, route) for route in routes]
        
                                                          
                                                                    
        for f in futures:
            f.result()
        
        time.sleep(0.5)                       

def api_stats_reporter():
    print("[API_STATS] Statistics reporter started", flush=True)
    while True:
        time.sleep(60)
        
        with api_stats_lock:
            uptime = time.time() - api_stats_start_time
            uptime_str = f"{int(uptime//3600)}h {int((uptime%3600)//60)}m"
            
            stats_msg = (
                f"[API_STATS] Uptime: {uptime_str} | "
                f"AAS: {api_stats.get('aas_get', 0)} GET ({api_stats.get('aas_get_failed', 0)} failed), "
                f"{api_stats.get('aas_put', 0)} PUT ({api_stats.get('aas_put_success', 0)} success, {api_stats.get('aas_put_failed', 0)} failed) | "
                f"InfluxDB: {api_stats.get('influx_write', 0)} WRITE ({api_stats.get('influx_write_success', 0)} success, {api_stats.get('influx_write_failed', 0)} failed) | "
                f"Modbus: {api_stats.get('modbus_read', 0)} READ ({api_stats.get('modbus_read_success', 0)} success, {api_stats.get('modbus_read_failed', 0)} failed), "
                f"{api_stats.get('modbus_write', 0)} WRITE ({api_stats.get('modbus_write_success', 0)} success, {api_stats.get('modbus_write_failed', 0)} failed) | "
                f"MQTT: {api_stats.get('mqtt_publish', 0)} PUBLISH"
            )
            print(stats_msg, flush=True)

stats_thread = threading.Thread(target=api_stats_reporter, daemon=True, name="API-Stats-Reporter")
stats_thread.start()
print("[Init] Started API Statistics Reporter Thread", flush=True)

for i in range(3):
    worker_thread = threading.Thread(target=modbus_writer_worker, daemon=True, name=f"ModbusWriter-{i}")
    worker_thread.start()
    print(f"[Init] Started Modbus Writer Thread {i}", flush=True)

_start_kafka_consumers()

if any(source_map.get(r.get('dataSource', ''), {}).get('protocol') == 'ocpp'
       for r in routes):
    _ensure_ocpp_cs_started()
    print(f"[Init] Started OCPP Central System on port {OCPP_CS_PORT}", flush=True)

if __name__ == "__main__":
    t = threading.Thread(target=poll_loop)
    t.start()
    print("Polling thread started.", flush=True)
                            
    while True:
        time.sleep(10)
