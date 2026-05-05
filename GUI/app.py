# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from flask import Flask, render_template, request, jsonify
import sys
import os
import time
import json
import base64
import requests
import concurrent.futures
import basyx.aas.model as model
from basyx.aas.adapter import json as basyx_json
from basyx.aas.adapter.aasx import AASXWriter, AASXReader

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import connection as connection_settings
from qualifier_vocabulary import make_qualifier
from influxdb_provisioner import InfluxProvisioner
from grafana_provisioner import GrafanaProvisioner
from grafana_dashboard_builder import PropertySpec

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/connection', methods=['GET'])
def api_connection_get():
    return jsonify({
        "configured": connection_settings.is_configured(),
        "data":       connection_settings.load(),
        "defaults": {
            "host":  connection_settings.DEFAULT_HOST,
            "ports": connection_settings.DEFAULT_PORTS,
        },
    })

@app.route('/api/connection', methods=['POST'])
def api_connection_save():
    payload = request.json or {}
    saved = connection_settings.save(payload)
    return jsonify({"status": "success", "data": saved})

@app.route('/api/grafana/provision', methods=['POST'])
def api_grafana_provision():
    payload = request.json or {}
    asset_name = (payload.get("asset_name") or "").strip()
    raw_props  = payload.get("properties") or []
    if not asset_name:
        return jsonify({"status": "error",
                        "message": "asset_name is required"}), 400
    properties = [
        PropertySpec(
            name=p.get("name", ""),
            bucket=p.get("bucket", ""),
            measurement=p.get("measurement", ""),
            unit=p.get("unit", ""),
            description=p.get("description", ""),
        ) for p in raw_props if p.get("name")
    ]
    if not properties:
        return jsonify({"status": "error",
                        "message": "no properties supplied"}), 400

    prov = GrafanaProvisioner()
    result = prov.provision_for_asset(asset_name, properties)
    if result is None:
        return jsonify({
            "status":  "error",
            "message": f"Grafana at {prov.url} not reachable or upload failed.",
        }), 502
    return jsonify({"status": "success", "data": result})

@app.route('/api/influxdb/query', methods=['POST', 'OPTIONS'])
def api_influxdb_query_proxy():
    cors_headers = {
        'Access-Control-Allow-Origin':  '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, Accept',
    }
    if request.method == 'OPTIONS':
        return ('', 204, cors_headers)

    from influxdb_provisioner import DEFAULT_TOKEN
    org   = request.args.get('org', '')
    token = DEFAULT_TOKEN
    body  = request.get_data()

    influx_internal = connection_settings.get_url("influxdb")
    url = f"{influx_internal}/api/v2/query"
    if org:
        url += f"?org={org}"

    try:
        resp = requests.post(
            url,
            headers={
                'Authorization':  f'Token {token}',
                'Content-Type':   'application/vnd.flux',
                'Accept':         'application/csv',
            },
            data=body,
            timeout=15,
        )
        return (resp.content, resp.status_code,
                {**cors_headers,
                 'Content-Type': resp.headers.get('Content-Type', 'text/csv')})
    except Exception as exc:
        return (str(exc), 502, cors_headers)

@app.route('/api/influxdb/defaults', methods=['GET'])
def api_influxdb_defaults():
    from influxdb_provisioner import DEFAULT_TOKEN, DEFAULT_ORG
    return jsonify({
        "endpoint": connection_settings.get_url("influxdb", external=True),
        "host":     connection_settings.load().get("host", "localhost"),
        "port":     connection_settings.load()["ports"]["influxdb"],
        "token":    DEFAULT_TOKEN,
        "org":      DEFAULT_ORG,
        "bucket":   "hems",
    })

@app.route('/api/influxdb/provision', methods=['POST'])
def api_influxdb_provision():
    payload = request.json or {}
    asset_name = (payload.get("asset_name") or "").strip()
    if not asset_name:
        return jsonify({"status": "error",
                        "message": "asset_name is required"}), 400
    prov = InfluxProvisioner()
    result = prov.provision_for_asset(asset_name)
    if result is None:
        return jsonify({
            "status":  "error",
            "message": f"InfluxDB at {prov.url} not reachable or bucket "
                       f"creation failed.",
        }), 502
    return jsonify({"status": "success", "data": result})

def safe_int(val, default=0):
    try:
        if val is None or val == '': return default
        return int(val)
    except (ValueError, TypeError):
        return default

import re

def sanitize_id_short(name):
    if not name: return "Unnamed"
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if sanitized and sanitized[0].isdigit():
        sanitized = "n" + sanitized
    return sanitized

def create_property_with_qualifiers(prop_data):
    id_short = sanitize_id_short(prop_data.get('name') or "Property_Unnamed")
    val_type = model.datatypes.Float if prop_data.get('type') == 'xs:float' else model.datatypes.String
    
    prop = model.Property(id_short=id_short, value_type=val_type)
    config = prop_data.get('config', {})
    if not config: return prop

    protocol = config.get('protocol', '')

    def _add(qname, value):
        if value is None or str(value).strip() == "":
            return
        prop.qualifier.add(make_qualifier(qname, value))

    if protocol == 'modbus':
        _add("ModbusRegister",     config.get('register', ''))
        _add("ModbusRegisterType", config.get('regType', 'Holding Register'))
        _add("ModbusDataType",     config.get('dataType', 'FLOAT32'))
        _add("ModbusIP",           config.get('host', ''))
        _add("ModbusPort",         safe_int(config.get('port', '502'), 502))
        _add("ModbusSlaveID",      safe_int(config.get('slaveId', '1'), 1))

    elif protocol == 'mqtt':
        _add("MqttBroker", config.get('broker', ''))
        _add("MqttPort",   safe_int(config.get('port', '1883'), 1883))
        _add("MqttTopic",  config.get('register', config.get('addr', '')))

    elif protocol == 'http':
        _add("HttpUrl",      config.get('url', ''))
        _add("HttpJsonPath", config.get('register', config.get('jsonPath', '')))

    elif protocol == 'opcua':
        _add("OpcuaServer", config.get('serverUrl', ''))
        _add("OpcuaNodeId", config.get('register', config.get('nodeId', '')))

    mqtt = config.get('mqtt', {})
    if mqtt.get('active'):
        _add("SinkMqttTopic",  mqtt.get('topic', ''))
        _add("SinkMqttBroker", mqtt.get('broker', ''))
        if mqtt.get('port'):
            _add("SinkMqttPort", safe_int(mqtt['port'], 1883))

    influx = config.get('influx', {})
    if influx.get('active'):
        _add("InfluxServerUrl",   influx.get('endpoint', ''))
        _add("InfluxBucket",      influx.get('database', ''))
        _add("InfluxMeasurement", influx.get('measurement', ''))

    return prop

_AID_SEM_CACHE = {}

_AID_FALLBACK = {
    '__submodel__':       'https://admin-shell.io/idta/AssetInterfacesDescription/1/0',
    '__interface__':      'https://www.w3.org/2019/wot/td#',
    '__property__':       'https://www.w3.org/2019/wot/td#PropertyAffordance',
    '__form__':           'https://www.w3.org/2019/wot/hypermedia#Form',
    'title':              'https://www.w3.org/2019/wot/td#title',
    'base':               'https://www.w3.org/2019/wot/td#base',
    'EndpointMetadata':   'https://admin-shell.io/idta/AssetInterfacesDescription/1/0/EndpointMetadata',
    'InteractionMetadata':'https://admin-shell.io/idta/AssetInterfacesDescription/1/0/InteractionMetadata',
    'contentType':        'https://www.w3.org/2019/wot/hypermedia#forContentType',
    'securityDefinitions':'https://www.w3.org/2019/wot/td#securityDefinitions',
    'nosec_sc':           'https://www.w3.org/2019/wot/security#NoSecurityScheme',
    'scheme':             'https://www.w3.org/2019/wot/security#scheme',
    'security':           'https://www.w3.org/2019/wot/td#security',
    'properties':         'https://www.w3.org/2019/wot/td#properties',
    'observable':         'https://www.w3.org/2019/wot/td#isObservable',
    'type':               'https://www.w3.org/2019/wot/json-schema#type',
    'unit':               'https://schema.org/unitCode',
    'forms':              'https://www.w3.org/2019/wot/td#hasForm',
    'href':               'https://www.w3.org/2019/wot/hypermedia#hasTarget',
    'modv_function':      'https://modbus.org/wot/modv#function',
    'modv_entity':        'https://modbus.org/wot/modv#entity',
    'modv_type':          'https://modbus.org/wot/modv#type',
    'mqv_controlPacket':  'https://www.w3.org/2019/wot/mqtt#controlPacket',
    'mqv_retain':         'https://www.w3.org/2019/wot/mqtt#retain',
    'mqv_qos':            'https://www.w3.org/2019/wot/mqtt#qos',
    'htv_methodName':     'https://www.w3.org/2011/http#mthd',
}

def _ext_ref(iri):
    return model.ExternalReference(
        (model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE, value=iri),)
    )

def _load_aid_sem_map():
    if _AID_SEM_CACHE:
        return _AID_SEM_CACHE

    template_path = os.path.join(
        os.path.dirname(__file__), "IDTA-templates",
        "IDTA 02017-1-0_Template_Asset Interfaces Description.aasx"
    )

    sem_map = {}

    if not os.path.exists(template_path):
        print("[AID] Template not found — using fallback IRIs.")
    else:
        try:
            with AASXReader(template_path) as reader:
                store = model.DictObjectStore()
                reader.read_into(store, model.DictObjectStore())

            base_sm = next((o for o in store if isinstance(o, model.Submodel)), None)
            if base_sm:
                if base_sm.semantic_id:
                    sem_map['__submodel__'] = base_sm.semantic_id

                def walk(elem):
                    if hasattr(elem, 'semantic_id') and elem.semantic_id:
                        sem_map[elem.id_short] = elem.semantic_id
                    if hasattr(elem, 'value'):
                        for child in elem.value:
                            walk(child)

                for iface in base_sm.submodel_element:
                    if iface.semantic_id:
                        sem_map['__interface__'] = iface.semantic_id

                    if hasattr(iface, 'value'):
                        for child in iface.value:
                            walk(child)

                    def find(elem, id_short):
                        if hasattr(elem, 'value'):
                            for c in elem.value:
                                if c.id_short == id_short:
                                    return c
                                r = find(c, id_short)
                                if r:
                                    return r
                        return None

                    props_el = find(iface, 'properties')
                    if props_el and hasattr(props_el, 'value'):
                        p_tmpl = next(iter(props_el.value), None)
                        if p_tmpl and p_tmpl.semantic_id:
                            sem_map['__property__'] = p_tmpl.semantic_id
                        if p_tmpl:
                            forms_el = find(p_tmpl, 'forms')
                            if forms_el and hasattr(forms_el, 'value'):
                                f_tmpl = next(iter(forms_el.value), None)
                                if f_tmpl and f_tmpl.semantic_id:
                                    sem_map['__form__'] = f_tmpl.semantic_id

            from_template = [k for k in sem_map if not k.startswith('__')]
            print(f"[AID] Template loaded — {len(from_template)} semantic IDs from template: {from_template}")

        except Exception as e:
            print(f"[AID] Template error ({e}) — using fallback IRIs.")

    fallback_used = []
    for key, iri in _AID_FALLBACK.items():
        if key not in sem_map:
            sem_map[key] = _ext_ref(iri)
            fallback_used.append(key)
    if fallback_used:
        print(f"[AID] Fallback IRIs used for: {fallback_used}")

    _AID_SEM_CACHE.update(sem_map)
    return _AID_SEM_CACHE

def generate_aid_submodel(submodels_data):
    S = _load_aid_sem_map()

    def prop(id_short, value, key=None, value_type=model.datatypes.String):
        return model.Property(
            id_short=sanitize_id_short(id_short),
            value_type=value_type,
            value=value,
            semantic_id=S.get(key or id_short)
        )

    def smc(id_short, key=None):
        return model.SubmodelElementCollection(
            id_short=sanitize_id_short(id_short),
            semantic_id=S.get(key or id_short)
        )

    aid_sm = model.Submodel(
        id_short="AssetInterfacesDescription",
        id_=f"https://example.com/submodels/aid_{int(time.time())}",
        semantic_id=S.get('__submodel__')
    )

    PROTO_LABELS = {'modbus': 'Modbus TCP', 'mqtt': 'MQTT', 'http': 'HTTP/REST', 'opcua': 'OPC-UA'}

    iface_idx = 0

    for sm_item in submodels_data:
        sm_name = sm_item.get('name', 'Interface')
        cfg     = sm_item.get('config', {})

        protocols_map = cfg.get('protocols', {})
        if protocols_map:
            proto_entries = [
                (proto, pd.get('source', {}), pd.get('targetData', []))
                for proto, pd in protocols_map.items()
                if pd.get('targetData')
            ]
        else:
            proto_entries = [(
                cfg.get('protocol', 'modbus'),
                cfg.get('source', {}),
                cfg.get('targetData', [])
            )]

        for protocol, source, rows in proto_entries:
            if not rows:
                continue

            idx = iface_idx
            iface_idx += 1

            iface = smc(f"Interface{idx:02d}", '__interface__')
            iface.value.add(prop("title", f"{PROTO_LABELS.get(protocol, protocol)} — {sm_name}"))

            ep = smc("EndpointMetadata")

            if protocol == 'modbus':
                host     = source.get('host', 'modbus-server-basyx')
                port     = source.get('port', '5020')
                slave    = source.get('slaveId', '1')
                base_uri = f"modbus+tcp://{host}:{port}/{slave}/"
                ctype    = "application/octet-stream"
            elif protocol == 'mqtt':
                broker   = source.get('broker', 'mosquitto')
                port     = source.get('port', '1883')
                base_uri = f"mqtt://{broker}:{port}/"
                ctype    = "application/json"
            elif protocol == 'http':
                url      = source.get('url', 'http://localhost/')
                base_uri = url.rstrip('/') + '/'
                ctype    = "application/json"
            elif protocol == 'opcua':
                base_uri = source.get('serverUrl', 'opc.tcp://localhost:4840')
                ctype    = "application/opcua+uabinary"
            else:
                base_uri = f"{protocol}://localhost/"
                ctype    = "application/json"

            ep.value.add(prop("base",        base_uri))
            ep.value.add(prop("contentType", ctype))

            sec_defs = smc("securityDefinitions")
            nosec    = smc("nosec_sc")
            nosec.value.add(prop("scheme", "nosec"))
            sec_defs.value.add(nosec)
            ep.value.add(sec_defs)
            ep.value.add(prop("security", "nosec_sc"))
            iface.value.add(ep)

            im        = smc("InteractionMetadata")
            props_smc = smc("properties")

            for row in rows:
                raw_name  = row.get('description') or row.get('addr') or 'property'
                prop_id   = sanitize_id_short(raw_name)
                addr      = str(row.get('addr', ''))
                data_type = row.get('type', 'FLOAT32')
                unit_val  = row.get('unit', '')

                dt_low = data_type.lower()
                if any(t in dt_low for t in ('int', 'uint', 'coil', 'discrete')):
                    xs_type = "integer"
                elif 'bool' in dt_low:
                    xs_type = "boolean"
                elif any(t in dt_low for t in ('string', 'str')):
                    xs_type = "string"
                else:
                    xs_type = "float"

                p_smc = smc(prop_id, '__property__')
                p_smc.value.add(prop("title",      raw_name))
                p_smc.value.add(prop("observable", "false"))
                p_smc.value.add(prop("type",       xs_type))
                if unit_val:
                    p_smc.value.add(prop("unit", unit_val))

                forms = smc("forms")
                form  = smc("form_00", '__form__')

                if protocol == 'modbus':
                    reg_type = row.get('regType', 'Holding Register').lower()
                    if 'coil' in reg_type:
                        func, entity = "readCoils", "Coils"
                    elif 'input register' in reg_type:
                        func, entity = "readInputRegisters", "InputRegisters"
                    elif 'discrete' in reg_type:
                        func, entity = "readDiscreteInputs", "DiscreteInputs"
                    else:
                        func, entity = "readHoldingRegisters", "HoldingRegisters"

                    form.value.add(prop("href",          addr))
                    form.value.add(prop("contentType",   "application/octet-stream"))
                    form.value.add(prop("modv_function", func))
                    form.value.add(prop("modv_entity",   entity))
                    form.value.add(prop("modv_type",     data_type))

                elif protocol == 'mqtt':
                    form.value.add(prop("href",              addr))
                    form.value.add(prop("contentType",       "application/json"))
                    form.value.add(prop("mqv_controlPacket", "SUBSCRIBE"))
                    form.value.add(prop("mqv_retain",        "false"))
                    form.value.add(prop("mqv_qos",           str(source.get('qos', '0'))))

                elif protocol == 'http':
                    form.value.add(prop("href",           addr))
                    form.value.add(prop("contentType",    "application/json"))
                    form.value.add(prop("htv_methodName", source.get('method', 'GET')))

                elif protocol == 'opcua':
                    form.value.add(prop("href",        addr))
                    form.value.add(prop("contentType", "application/opcua+uabinary"))

                forms.value.add(form)
                p_smc.value.add(forms)
                props_smc.value.add(p_smc)

            im.value.add(props_smc)
            iface.value.add(im)
            aid_sm.submodel_element.add(iface)

    return aid_sm if aid_sm.submodel_element else None

PROTOCOL_LABELS = {
    'modbus': 'Modbus TCP', 'mqtt': 'MQTT', 'http': 'HTTP/REST',
    'opcua': 'OPC-UA', 'kafka': 'Kafka',
    'bacnet': 'BACnet/IP', 'ocpp': 'OCPP', 'dlms': 'DLMS/COSEM',
}
PROTOCOL_SMC_NAMES = {
    'modbus': 'Modbus', 'mqtt': 'MQTT', 'http': 'HTTP',
    'opcua': 'OPCUA', 'kafka': 'Kafka',
    'bacnet': 'BACnet', 'ocpp': 'OCPP', 'dlms': 'DLMS',
}

def _add_string_prop(parent, id_short, value):
    if value is None or not str(value).strip():
        return
    parent.value.add(model.Property(
        id_short=sanitize_id_short(id_short),
        value_type=model.datatypes.String,
        value=str(value),
    ))

def _build_connection_smc(protocol, source):
    conn = model.SubmodelElementCollection(id_short="Connection")
    _add_string_prop(conn, 'Protocol', PROTOCOL_LABELS.get(protocol, protocol))
    if protocol == 'modbus':
        for k, v in [('Host',            source.get('host')),
                     ('Port',            source.get('port')),
                     ('SlaveID',         source.get('slaveId')),
                     ('PollingInterval', source.get('polling'))]:
            _add_string_prop(conn, k, v)
    elif protocol == 'mqtt':
        for k, v in [('Broker', source.get('broker')),
                     ('Port',   source.get('port')),
                     ('QoS',    source.get('qos'))]:
            _add_string_prop(conn, k, v)
    elif protocol == 'http':
        for k, v in [('EndpointURL',     source.get('url') or source.get('baseUrl')),
                     ('Method',          source.get('method')),
                     ('PollingInterval', source.get('polling'))]:
            _add_string_prop(conn, k, v)
        _AUTH_LABEL_MAP = {
            'none':                       'none',
            'bearer token':               'bearer',
            'basic auth':                 'basic',
            'api key (header)':           'api_key_header',
            'api key (query)':            'api_key_query',
            'oauth2 client-credentials':  'oauth2_cc',
            'bearer':                     'bearer',
            'basic':                      'basic',
            'api_key_header':             'api_key_header',
            'api_key_query':              'api_key_query',
            'oauth2_cc':                  'oauth2_cc',
        }
        raw_auth = (source.get('authType') or 'none').strip().lower()
        auth_type = _AUTH_LABEL_MAP.get(raw_auth, 'none')
        _add_string_prop(conn, 'HttpAuthType', auth_type)
        if auth_type == 'bearer':
            _add_string_prop(conn, 'HttpBearerToken',
                             source.get('bearerToken'))
        elif auth_type == 'api_key_header':
            _add_string_prop(conn, 'HttpApiKey',       source.get('apiKey'))
            _add_string_prop(conn, 'HttpApiKeyHeader',
                             source.get('apiKeyHeader') or 'X-API-Key')
        elif auth_type == 'api_key_query':
            _add_string_prop(conn, 'HttpApiKey',      source.get('apiKey'))
            _add_string_prop(conn, 'HttpApiKeyQuery',
                             source.get('apiKeyQuery') or 'apikey')
        elif auth_type == 'oauth2_cc':
            _add_string_prop(conn, 'OAuth2TokenUrl',
                             source.get('oauthTokenUrl'))
            _add_string_prop(conn, 'OAuth2ClientId',
                             source.get('clientId'))
            _add_string_prop(conn, 'OAuth2ClientSecret',
                             source.get('clientSecret'))
            _add_string_prop(conn, 'OAuth2Scope',
                             source.get('scope'))
        elif auth_type == 'basic':
            _add_string_prop(conn, 'HttpUsername', source.get('username'))
            _add_string_prop(conn, 'HttpPassword', source.get('password'))
        _add_string_prop(conn, 'HttpQueryParams',
                         source.get('queryParams'))
    elif protocol == 'opcua':
        for k, v in [('ServerURL',          source.get('serverUrl')),
                     ('SecurityPolicy',     source.get('securityPolicy')),
                     ('SecurityMode',       source.get('securityMode')),
                     ('AuthType',           source.get('authType')),
                     ('Username',           source.get('username')),
                     ('Password',           source.get('password')),
                     ('PublishingInterval', source.get('publishingInterval')),
                     ('SamplingInterval',   source.get('samplingInterval'))]:
            _add_string_prop(conn, k, v)
    elif protocol == 'kafka':
        for k, v in [('BrokerUrl',        source.get('brokerUrl')),
                     ('GroupId',          source.get('groupId')),
                     ('MaxPollRecords',   source.get('maxPollRecords')),
                     ('SeekTo',           source.get('seekTo')),
                     ('SecurityProtocol', source.get('securityProto'))]:
            _add_string_prop(conn, k, v)
    elif protocol == 'bacnet':
        for k, v in [('Host',           source.get('host')),
                     ('Port',           source.get('port', '47808')),
                     ('DeviceInstance', source.get('deviceInstance')),
                     ('Network',        source.get('network', '0')),
                     ('PollingInterval',source.get('polling')),
                     ('Timeout',        source.get('timeout'))]:
            _add_string_prop(conn, k, v)
    elif protocol == 'ocpp':
        for k, v in [('ServerURL',      source.get('serverUrl')),
                     ('ChargePointId',  source.get('chargePointId')),
                     ('OCPPVersion',    source.get('ocppVersion', 'OCPP 1.6')),
                     ('Password',       source.get('password')),
                     ('PollingInterval',source.get('polling'))]:
            _add_string_prop(conn, k, v)
    elif protocol == 'dlms':
        for k, v in [('Host',          source.get('host')),
                     ('Port',          source.get('port', '4059')),
                     ('LogicalDevice', source.get('logicalDevice', '1')),
                     ('ClientAddress', source.get('clientAddress', '16')),
                     ('AuthType',      source.get('authType', 'None')),
                     ('Password',      source.get('password')),
                     ('PollingInterval',source.get('polling')),
                     ('Timeout',       source.get('timeout'))]:
            _add_string_prop(conn, k, v)
    return conn

def _build_datapoints_smc(protocol, rows, asset_name=""):
    grafana_url   = (connection_settings.get_url("grafana", external=True)
                     if asset_name else None)
    dashboard_uid = f"aas-{asset_name.lower()}-{protocol}" if asset_name else None
    plugin_sid    = model.ExternalReference((
        model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE,
                   value=WEB_IFRAME_PLUGIN_SID),))

    dp_smc = model.SubmodelElementCollection(id_short="DataPoints")
    for dp_idx, row in enumerate(rows):
        raw_name  = (row.get('name') or row.get('description') or row.get('addr')
                     or f"DataPoint_{dp_idx}")
        prop_id   = sanitize_id_short(raw_name) or f"DataPoint_{dp_idx}"
        addr      = str(row.get('addr', ''))
        data_type = row.get('type', 'FLOAT32')
        unit      = row.get('unit', '')

        value_prop = model.Property(id_short="Value",
                                     value_type=model.datatypes.Float)

        def add_q(qtype, value, vtype=None):
            if value is None or not str(value).strip():
                return
            value_prop.qualifier.add(
                make_qualifier(qtype, value, value_type=vtype))

        if protocol == 'modbus':
            add_q('ModbusRegister', addr)
            add_q('ModbusType',     row.get('byteOrder', 'AB CD'))
            add_q('ModbusDataType', data_type)
        elif protocol == 'mqtt':
            add_q('MqttTopic',    addr)
            add_q('MqttJsonPath', row.get('jsonPath', ''))
        elif protocol == 'http':
            add_q('HttpJsonPath', addr)
            add_q('HttpFormat',   row.get('format', 'JSON'))
        elif protocol == 'opcua':
            add_q('OpcuaNodeId',           addr)
            add_q('OpcuaSamplingInterval', row.get('samplingInterval', ''))
        elif protocol == 'kafka':
            add_q('KafkaTopic',    addr)
            add_q('KafkaJsonPath', row.get('jsonPath', ''))
        elif protocol == 'bacnet':
            add_q('BACnetObjectId',  addr)
            add_q('BACnetPropertyId',row.get('propertyId', 'PresentValue'))
        elif protocol == 'ocpp':
            add_q('OCPPMeasurand', addr)
            add_q('OCPPPhase',     row.get('phase', ''))
        elif protocol == 'dlms':
            add_q('DLMSObisCode', addr)
            add_q('DLMSAttribute',row.get('attribute', '2'))
        add_q('DataType', data_type)
        if unit:
            add_q('Unit', unit)

        direction = (row.get('direction') or 'Read').strip()
        if direction not in ('Read', 'Write', 'ReadWrite'):
            direction = 'Read'
        add_q('Direction', direction)

        transform = (row.get('transform') or '').strip()
        if transform:
            add_q('TransformFormula', transform)

        desc_text = (row.get('description') or '').strip()
        if desc_text:
            try:
                value_prop.description = model.MultiLanguageTextType({"en": desc_text})
            except Exception:
                pass

        semantic_id_str = (row.get('semanticId') or '').strip()

        dp_wrapper = model.SubmodelElementCollection(id_short=prop_id)
        if semantic_id_str:
            dp_wrapper.semantic_id = model.ExternalReference((
                model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE,
                          value=semantic_id_str),
            ))
        dp_wrapper.value.add(value_prop)

        if grafana_url and dashboard_uid:
            panel_url = (
                f"{grafana_url}/d-solo/{dashboard_uid}"
                f"?orgId=1&panelId={dp_idx + 1}&refresh=5s&theme=light&kiosk=tv"
            )
            dashboard_prop = model.Property(
                id_short="Dashboard",
                value_type=model.datatypes.String,
                value=panel_url,
                semantic_id=plugin_sid,
            )
            dp_wrapper.value.add(dashboard_prop)

        dp_smc.value.add(dp_wrapper)
    return dp_smc

WEB_IFRAME_PLUGIN_SID = "https://example.com/plugins/web-iframe-viewer"

def _build_visualizations_smc(asset_name: str,
                              property_names: list[str]) -> "model.SubmodelElementCollection | None":
    if not property_names:
        return None

    grafana_url = connection_settings.get_url("grafana", external=True)
    dashboard_uid = f"aas-{asset_name.lower()}"
    sid_ref = model.ExternalReference(
        (model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE,
                    value=WEB_IFRAME_PLUGIN_SID),)
    )

    smc = model.SubmodelElementCollection(id_short="Visualizations")
    for idx, name in enumerate(property_names):
        panel_url = (
            f"{grafana_url}/d-solo/{dashboard_uid}"
            f"?orgId=1&panelId={idx + 1}&refresh=5s&theme=light&kiosk=tv"
        )
        prop = model.Property(
            id_short=sanitize_id_short(name),
            value_type=model.datatypes.String,
            value=panel_url,
            semantic_id=sid_ref,
        )
        smc.value.add(prop)
    return smc

def _build_datasinks_smc(sinks):
    extra = sinks.get('extra', {}) or {}
    influx = extra.get('influx', {}) or {}
    mqtt_sink = extra.get('mqtt',   {}) or {}
    if not (influx.get('active') or mqtt_sink.get('active')):
        return None

    ds = model.SubmodelElementCollection(id_short="DataSinks")

    if influx.get('active'):
        i = model.SubmodelElementCollection(id_short="InfluxDB")
        endpoint = (influx.get('endpoint')
                    or f"http://{influx.get('host', 'influxdb')}:"
                       f"{influx.get('port', '8086')}")
        _add_string_prop(i, 'ServerUrl',   endpoint)
        _add_string_prop(i, 'Token',       influx.get('token'))
        _add_string_prop(i, 'Org',         influx.get('org'))
        _add_string_prop(i, 'Bucket',      influx.get('database'))
        _add_string_prop(i, 'Measurement', influx.get('measurement'))
        ds.value.add(i)

    if mqtt_sink.get('active'):
        m = model.SubmodelElementCollection(id_short="MQTT")
        _add_string_prop(m, 'Broker', mqtt_sink.get('broker'))
        _add_string_prop(m, 'Port',   mqtt_sink.get('port'))
        _add_string_prop(m, 'Topic',  mqtt_sink.get('topic'))
        ds.value.add(m)

    return ds

def _build_dashboards_submodel(asset_name: str, protocols: list) -> model.Submodel:
    safe_name   = sanitize_id_short(asset_name or "AAS")
    grafana_url = connection_settings.get_url("grafana", external=True)
    plugin_sid  = model.ExternalReference((
        model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE,
                   value=WEB_IFRAME_PLUGIN_SID),))

    sm = model.Submodel(
        id_short="Dashboards",
        id_=f"https://example.com/submodels/{safe_name.lower()}/dashboards",
    )
    overview_uid = f"aas-{asset_name.lower()}"
    sm.submodel_element.add(model.Property(
        id_short="Overview",
        value_type=model.datatypes.String,
        value=f"{grafana_url}/d/{overview_uid}?orgId=1&refresh=5s&kiosk",
        semantic_id=plugin_sid,
    ))
    for protocol in protocols:
        proto_uid  = f"aas-{asset_name.lower()}-{protocol}"
        prop_id    = PROTOCOL_SMC_NAMES.get(protocol, protocol.capitalize())
        sm.submodel_element.add(model.Property(
            id_short=prop_id,
            value_type=model.datatypes.String,
            value=f"{grafana_url}/d/{proto_uid}?orgId=1&refresh=5s&kiosk",
            semantic_id=plugin_sid,
        ))
    return sm

def create_structured_submodel(sm_name, sm_config, asset_prefix=""):
    safe_name  = sanitize_id_short(sm_name or "UnnamedSubmodel")
    id_segment = (f"{asset_prefix.lower()}/{safe_name.lower()}"
                  if asset_prefix else safe_name.lower())
    sm = model.Submodel(
        id_short=safe_name,
        id_=f"https://example.com/submodels/{id_segment}",
    )

    protocols_map = sm_config.get('protocols', {}) or {}
    if protocols_map:
        proto_entries = [
            (p, pd.get('source', {}), pd.get('targetData', []))
            for p, pd in protocols_map.items()
            if pd.get('targetData')
        ]
    else:
        rows = sm_config.get('targetData', [])
        proto_entries = [(sm_config.get('protocol', 'modbus'),
                          sm_config.get('source', {}), rows)] if rows else []

    grafana_url = (connection_settings.get_url("grafana", external=True)
                   if asset_prefix else None)
    plugin_sid = model.ExternalReference((
        model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE,
                   value=WEB_IFRAME_PLUGIN_SID),))

    for protocol, source, rows in proto_entries:
        proto_smc = model.SubmodelElementCollection(
            id_short=PROTOCOL_SMC_NAMES.get(protocol, protocol.capitalize()),
        )
        proto_smc.value.add(_build_connection_smc(protocol, source))
        proto_smc.value.add(_build_datapoints_smc(protocol, rows,
                                                   asset_name=asset_prefix))
        if grafana_url and rows:
            proto_uid = f"aas-{asset_prefix.lower()}-{protocol}"
            proto_smc.value.add(model.Property(
                id_short="AllDashboards",
                value_type=model.datatypes.String,
                value=f"{grafana_url}/d/{proto_uid}?orgId=1&refresh=5s&kiosk",
                semantic_id=plugin_sid,
            ))
        sm.submodel_element.add(proto_smc)

    sinks_smc = _build_datasinks_smc(sm_config.get('sinks', {}) or {})
    if sinks_smc is not None:
        sm.submodel_element.add(sinks_smc)

    return sm

def deploy_to_server(obj_store, server_url=None):
    if server_url is None:
        server_url = connection_settings.get_url("aas")

    registry_url = connection_settings.get_url("aas_registry").rstrip("/")

    external_repo_url = os.getenv(
        "AAS_SERVER_EXTERNAL_URL",
        connection_settings.get_url("aas", external=True),
    )

    headers = {'Content-Type': 'application/json'}
    objects = [
        obj for obj in obj_store
        if isinstance(obj, (model.Submodel, model.AssetAdministrationShell))
    ]

    def _deploy_one(obj):
        errs = []
        obj_id_str = str(obj.id)
        endpoint   = 'shells' if isinstance(obj, model.AssetAdministrationShell) else 'submodels'
        encoded_id = base64.urlsafe_b64encode(obj_id_str.encode()).decode().rstrip("=")

        try:
            requests.delete(f"{server_url}/{endpoint}/{encoded_id}", timeout=5)
        except Exception:
            pass

        json_data = json.dumps(obj, cls=basyx_json.AASToJsonEncoder)
        try:
            r = requests.post(f"{server_url}/{endpoint}", data=json_data,
                              headers=headers, timeout=10)
            if r.status_code in (200, 201):
                print(f"[DEPLOY] OK  {obj.id_short}  ({r.status_code})", flush=True)
            else:
                msg = f"{obj.id_short}: HTTP {r.status_code} — {r.text[:300]}"
                print(f"[DEPLOY] FAIL  {msg}", flush=True)
                errs.append(msg)
        except Exception as e:
            errs.append(f"{obj.id_short}: {e}")

        if registry_url and isinstance(obj, model.AssetAdministrationShell):
            shell_href = f"{external_repo_url}/shells/{encoded_id}"
            descriptor = {
                "id":      obj_id_str,
                "idShort": obj.id_short,
                "assetInformation": {
                    "assetKind":     "Instance",
                    "globalAssetId": str(obj.asset_information.global_asset_id),
                },
                "endpoints": [{
                    "protocolInformation": {"href": shell_href},
                    "interface": "AAS-3.0",
                }],
            }
            try:
                requests.delete(f"{registry_url}/shell-descriptors/{encoded_id}",
                                timeout=5)
                rr = requests.post(f"{registry_url}/shell-descriptors",
                                   json=descriptor, headers=headers, timeout=10)
                print(f"[REGISTRY] {'OK' if rr.status_code in (200,201) else 'FAIL'} "
                      f"{obj.id_short}  ({rr.status_code})", flush=True)
            except Exception as e:
                print(f"[REGISTRY] Error registering {obj.id_short}: {e}", flush=True)

        return errs

    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(_deploy_one, objects):
            errors.extend(result)
    return errors

@app.route('/api/parse_device_config', methods=['POST'])
def parse_device_config():
    payload = request.json or {}
    try:
        raw = payload.get('content')
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ValueError("JSON muss ein Objekt sein")
        configs = _parse_device_json(raw)
        return jsonify({'status': 'success', 'configs': configs})
    except (json.JSONDecodeError, ValueError) as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400

def _parse_device_json(raw):
    ctx = raw.get('@context', '')
    if isinstance(ctx, list):
        ctx = ' '.join(str(c) for c in ctx)
    is_wot = (
        ('w3.org/wot' in ctx or 'w3.org/2019/wot' in ctx or 'w3.org/2022/wot' in ctx)
        or isinstance(raw.get('properties'), dict) and any(
            isinstance(v, dict) and 'forms' in v
            for v in raw.get('properties', {}).values()
        )
    )
    if is_wot:
        return _parse_wot_td(raw)
    if raw.get('format') == 'multi-protocol' and isinstance(raw.get('sources'), list):
        return [_parse_simple_device_format(s) for s in raw['sources'] if isinstance(s, dict)]
    return [_parse_simple_device_format(raw)]

def _proto_from_url(url):
    u = (url or '').lower()
    if u.startswith('modbus'):  return 'modbus'
    if u.startswith('mqtt'):    return 'mqtt'
    if u.startswith('http'):    return 'http'
    if u.startswith('opc.tcp') or u.startswith('opcua'): return 'opcua'
    return None

def _split_host_port(url, default_port):
    import re
    url = re.sub(r'^[a-z+.]+://', '', url).split('/')[0]
    if ':' in url:
        host, _, port = url.rpartition(':')
        try:
            return host, int(port)
        except ValueError:
            pass
    return url, default_port

_WOT_TYPE_MAP = {
    'xsd:float': 'FLOAT32', 'float32': 'FLOAT32', 'float': 'FLOAT32', 'number': 'FLOAT32',
    'xsd:double': 'FLOAT64', 'float64': 'FLOAT64', 'double': 'FLOAT64',
    'xsd:int': 'INT32', 'int32': 'INT32', 'int': 'INT32', 'integer': 'INT32',
    'xsd:short': 'INT16', 'int16': 'INT16',
    'xsd:unsignedshort': 'UINT16', 'uint16': 'UINT16',
    'xsd:unsignedint': 'UINT32', 'uint32': 'UINT32',
    'xsd:long': 'INT64', 'int64': 'INT64',
    'xsd:unsignedlong': 'UINT64', 'uint64': 'UINT64',
    'xsd:boolean': 'BOOL', 'bool': 'BOOL', 'boolean': 'BOOL',
    'xsd:string': 'STRING', 'string': 'STRING',
    'xsd:byte': 'BYTE', 'byte': 'BYTE',
}

def _map_type(t):
    return _WOT_TYPE_MAP.get((t or '').lower(), 'FLOAT32')

def _parse_wot_td(raw):
    import re
    base = raw.get('base', '')
    buckets = {}

    for prop_name, prop_val in (raw.get('properties') or {}).items():
        if not isinstance(prop_val, dict):
            continue
        unit     = prop_val.get('unit', '')
        wot_type = prop_val.get('type', 'number')
        forms    = prop_val.get('forms') or []
        if isinstance(forms, dict):
            forms = [forms]

        for form in forms:
            if not isinstance(form, dict):
                continue
            href         = form.get('href', '')
            content_type = form.get('contentType', '')
            form_keys    = ' '.join(str(k) for k in form)

            proto = _proto_from_url(href)
            if not proto:
                if 'modv:' in form_keys:   proto = 'modbus'
                elif 'mqv:' in form_keys:  proto = 'mqtt'
                elif 'htv:' in form_keys:  proto = 'http'
                elif 'opc' in content_type.lower(): proto = 'opcua'
                else: proto = _proto_from_url(base) or 'modbus'

            if proto not in buckets:
                src = {}
                if _proto_from_url(base) == proto or not src:
                    if proto == 'modbus':
                        host, port = _split_host_port(base, 502)
                        m = re.search(r'://[^/]+/(\d+)', base)
                        slave = m.group(1) if m else '1'
                        src = {'host': host, 'port': str(port), 'slaveId': slave, 'polling': '1000'}
                    elif proto == 'mqtt':
                        host, port = _split_host_port(base, 1883)
                        src = {'broker': host, 'port': str(port), 'qos': '0'}
                    elif proto == 'http':
                        host, port = _split_host_port(base, 80)
                        path = re.sub(r'^[a-z+.]+://[^/]+', '', base).rstrip('/')
                        src = {'baseUrl': f"http://{host}:{port}{path}", 'method': 'GET', 'polling': '5000'}
                    elif proto == 'opcua':
                        src = {'serverUrl': base}
                buckets[proto] = {'source': src, 'rows': []}

            modv_type = form.get('modv:type', '')
            row = {
                'description': prop_name,
                'unit':        unit,
                'addr':        href,
                'type':        _map_type(modv_type or wot_type),
                'direction':   'Read',
            }
            if proto == 'modbus':
                row['byteOrder'] = 'AB CD'
            elif proto in ('mqtt', 'http', 'kafka'):
                row['jsonPath'] = form.get('mqv:jsonPath', form.get('htv:jsonPath', ''))
            elif proto == 'opcua':
                row['samplingInterval'] = '250'

            buckets[proto]['rows'].append(row)

    return [
        {'protocol': proto, 'source': b['source'], 'targetData': b['rows']}
        for proto, b in buckets.items()
    ]

def _parse_simple_device_format(raw):
    proto = (raw.get('protocol') or raw.get('type') or '').lower()
    if not proto:
        if any(k in raw for k in ('slaveId', 'slave_id', 'unitId', 'modbusHost')):
            proto = 'modbus'
        elif any(k in raw for k in ('broker', 'mqttBroker', 'mqtt_broker')):
            proto = 'mqtt'
        elif any(k in raw for k in ('serverUrl', 'server_url', 'opcuaServer')):
            proto = 'opcua'
        elif any(k in raw for k in ('baseUrl', 'base_url', 'endpoint', 'url')):
            proto = 'http'
        else:
            proto = 'modbus'

    src = {}
    if proto == 'modbus':
        src = {
            'host':     raw.get('host') or raw.get('ip') or raw.get('address') or '',
            'port':     str(raw.get('port') or '502'),
            'slaveId':  str(raw.get('slaveId') or raw.get('slave_id') or raw.get('unitId') or '1'),
            'polling':  str(raw.get('polling') or raw.get('pollingInterval') or '1000'),
        }
    elif proto == 'mqtt':
        src = {
            'broker': raw.get('broker') or raw.get('host') or '',
            'port':   str(raw.get('port') or '1883'),
            'qos':    str(raw.get('qos') or '0'),
        }
    elif proto == 'http':
        src = {
            'baseUrl': raw.get('baseUrl') or raw.get('base_url') or raw.get('url') or raw.get('endpoint') or '',
            'method':  raw.get('method') or 'GET',
            'polling': str(raw.get('polling') or '5000'),
        }
    elif proto == 'opcua':
        src = {'serverUrl': raw.get('serverUrl') or raw.get('server_url') or ''}
    elif proto == 'kafka':
        src = {
            'brokerUrl': raw.get('broker') or raw.get('brokerUrl') or raw.get('bootstrap_servers') or '',
            'groupId':   raw.get('groupId') or raw.get('group_id') or 'databridge',
            'seekTo':    raw.get('seekTo') or raw.get('seek_to') or 'latest',
        }
    elif proto == 'bacnet':
        src = {
            'host':           raw.get('host') or raw.get('ip') or '',
            'port':           str(raw.get('port') or '47808'),
            'deviceInstance': str(raw.get('deviceInstance') or raw.get('device_instance') or '0'),
            'timeout':        str(raw.get('timeout') or '3000'),
        }
    elif proto == 'ocpp':
        src = {
            'serverUrl':     raw.get('serverUrl') or raw.get('server_url') or '',
            'chargePointId': raw.get('chargePointId') or raw.get('charge_point_id') or 'CP001',
            'ocppVersion':   raw.get('ocppVersion') or raw.get('ocpp_version') or '1.6',
            'polling':       str(raw.get('polling') or '10000'),
        }
    elif proto == 'dlms':
        src = {
            'host':          raw.get('host') or raw.get('ip') or '',
            'port':          str(raw.get('port') or '4059'),
            'clientId':      str(raw.get('clientId') or raw.get('client_id') or '16'),
            'logicalDevice': str(raw.get('logicalDevice') or raw.get('logical_device') or '1'),
            'authLevel':     str(raw.get('authLevel') or raw.get('auth_level') or 'none'),
            'password':      str(raw.get('password') or ''),
        }

    dp_list = (raw.get('datapoints') or raw.get('registers') or raw.get('properties')
               or raw.get('measurements') or raw.get('sensors') or raw.get('signals') or [])
    if isinstance(dp_list, dict):
        dp_list = [{'description': k, **v} for k, v in dp_list.items()]

    target_data = []
    for dp in dp_list:
        if not isinstance(dp, dict):
            continue
        addr = str(dp.get('address') or dp.get('addr') or dp.get('register')
                   or dp.get('topic') or dp.get('nodeId') or dp.get('node_id')
                   or dp.get('objectId') or dp.get('object_id')
                   or dp.get('measurand') or dp.get('obisCode') or dp.get('obis_code') or '')
        row = {
            'addr':        addr,
            'type':        _map_type(dp.get('type') or dp.get('dataType') or dp.get('data_type')),
            'description': str(dp.get('description') or dp.get('name') or dp.get('label') or ''),
            'unit':        str(dp.get('unit') or ''),
            'direction':   str(dp.get('direction') or 'Read'),
        }
        if proto == 'modbus':
            row['byteOrder'] = str(dp.get('byteOrder') or 'AB CD')
        elif proto in ('mqtt', 'http', 'kafka'):
            row['jsonPath'] = str(dp.get('jsonPath') or dp.get('json_path') or '')
        elif proto == 'opcua':
            row['samplingInterval'] = str(dp.get('samplingInterval') or '250')
        elif proto == 'bacnet':
            row['addr']       = str(dp.get('objectId') or dp.get('object_id') or addr)
            row['propertyId'] = str(dp.get('propertyId') or dp.get('property_id') or 'presentValue')
        elif proto == 'ocpp':
            row['addr']    = str(dp.get('measurand') or addr)
            row['phase']   = str(dp.get('phase') or '')
            if dp.get('ocppCommand'):
                row['ocppCommand']   = str(dp['ocppCommand'])
                row['ocppConfigKey'] = str(dp.get('ocppConfigKey') or '')
        elif proto == 'dlms':
            row['addr']      = str(dp.get('obisCode') or dp.get('obis_code') or addr)
            row['attribute'] = str(dp.get('attribute') or '2')
        target_data.append(row)

    return {'protocol': proto, 'source': src, 'targetData': target_data}

@app.route('/api/create_aas', methods=['POST'])
def create_aas():
    data = request.json
    asset_data     = data.get('asset', {})
    submodels_data = data.get('submodels', [])
    influx_auto    = bool(data.get('influxAuto'))
    grafana_auto   = bool(data.get('grafanaAuto'))
    custom_db      = bool(data.get('deployCustomDataBridge'))
    full_idta      = bool(data.get('generateIDTA') or data.get('generateAID'))

    obj_store = model.DictObjectStore()
    created_submodels = []

    asset_prefix = sanitize_id_short(asset_data.get('name') or "")

    influx_provisioned: dict | None = None
    if influx_auto:
        prov = InfluxProvisioner()
        influx_provisioned = prov.provision_for_asset(
            asset_data.get('name') or 'asset')
        if influx_provisioned is None:
            print(f"[InfluxDB] Auto-provision failed (host={prov.url}); "
                  f"continuing without InfluxDB qualifiers.")
        else:
            print(f"[InfluxDB] Provisioned bucket "
                  f"{influx_provisioned['InfluxBucket']} at "
                  f"{influx_provisioned['InfluxServerUrl']}")
            server = influx_provisioned['InfluxServerUrl']
            host, _, port = server.replace('http://','').replace('https://','').partition(':')
            for sm_item in submodels_data:
                cfg = sm_item.setdefault('config', {})
                sinks = cfg.setdefault('sinks', {}).setdefault('extra', {})
                influx_cfg = sinks.setdefault('influx', {})
                influx_cfg['active']      = True
                influx_cfg['host']        = host or 'influxdb'
                influx_cfg['port']        = port.split('/')[0] or '8086'
                influx_cfg['endpoint']    = server
                influx_cfg['token']       = influx_provisioned['InfluxToken']
                influx_cfg['org']         = influx_provisioned['InfluxOrg']
                influx_cfg['database']    = influx_provisioned['InfluxBucket']
                influx_cfg.setdefault(
                    'measurement', sm_item.get('name') or 'measurement')

    asset_name = asset_data.get('name') or "AAS_Default"

    for sm_item in submodels_data:
        name      = sm_item.get('name')
        sm_config = sm_item.get('config', {})
        if name == 'AssetInterfacesDescription':
            continue
        sm = create_structured_submodel(name, sm_config, asset_prefix)
        obj_store.add(sm)
        created_submodels.append(sm)

    if grafana_auto:
        _active_protocols = []
        for sm_item in submodels_data:
            cfg = sm_item.get('config', {}) or {}
            for proto, pd in (cfg.get('protocols') or {}).items():
                if pd.get('targetData') and proto not in _active_protocols:
                    _active_protocols.append(proto)
        if _active_protocols:
            _dash_sm = _build_dashboards_submodel(asset_name, _active_protocols)
            obj_store.add(_dash_sm)
            created_submodels.append(_dash_sm)

    safe_asset_name = sanitize_id_short(asset_name)
    asset_id = asset_data.get('id') or f"https://example.com/ids/aas/{safe_asset_name.lower()}"
    aas = model.AssetAdministrationShell(
        id_short=safe_asset_name,
        id_=asset_id,
        asset_information=model.AssetInformation(asset_kind=model.AssetKind.INSTANCE, global_asset_id=asset_id)
    )
    for sm in created_submodels:
        aas.submodel.add(model.ModelReference.from_referable(sm))
    obj_store.add(aas)

    filepath = os.path.join(os.path.dirname(__file__), "generated_aas.aasx")
    with AASXWriter(filepath) as writer:
        writer.write_all_aas_objects(part_name="/aasx/aasx", objects=obj_store, file_store=model.DictObjectStore(), write_json=False)
    
    errors = deploy_to_server(obj_store)
    if errors:
        return jsonify({"status": "error", "message": "Deploy failed: " + "; ".join(errors)}), 500

    idta_summary = None
    if full_idta:
        try:
            from generate_idta_submodels import generate_and_upload as _gen_idta
            idta_summary = _gen_idta(
                connection_settings.get_url("aas"),
                dry_run=False,
                print_json=False,
                orchestrator_url=connection_settings.get_url("orchestrator"),
            )
            print(f"[IDTA] {idta_summary.get('generated', 0)} submodels "
                  f"generated, {idta_summary.get('uploaded', 0)} uploaded.")
        except Exception as exc:
            print(f"[IDTA] Generation failed: {exc}")
            idta_summary = {"error": str(exc)}

    grafana_result = None
    if grafana_auto:
        from influxdb_provisioner import (DEFAULT_TOKEN as _IDF_TOKEN,
                                          DEFAULT_ORG as _IDF_ORG,
                                          _sanitize_bucket)
        bucket = (influx_provisioned['InfluxBucket'] if influx_provisioned
                  else _sanitize_bucket(asset_name))
        token  = (influx_provisioned['InfluxToken']  if influx_provisioned
                  else _IDF_TOKEN)
        org    = (influx_provisioned['InfluxOrg']    if influx_provisioned
                  else _IDF_ORG)
        properties: list[PropertySpec] = []
        protocols_properties: dict[str, list[PropertySpec]] = {}
        for sm_item in submodels_data:
            cfg = sm_item.get('config', {}) or {}
            for proto, pd in (cfg.get('protocols') or {}).items():
                proto_props: list[PropertySpec] = []
                for row in pd.get('targetData') or []:
                    name = sanitize_id_short(
                        row.get('name') or row.get('description') or row.get('addr') or '')
                    if not name:
                        continue
                    spec = PropertySpec(
                        name=name,
                        bucket=bucket,
                        measurement=name,
                        unit=row.get('unit', ''),
                        description=row.get('description', ''),
                        viz_type=row.get('vizType', 'timeseries'),
                    )
                    properties.append(spec)
                    proto_props.append(spec)
                if proto_props:
                    protocols_properties.setdefault(proto, []).extend(proto_props)
        prov_g = GrafanaProvisioner()
        print(f"[Grafana] URL={prov_g.url}  reachable={prov_g.is_reachable()}"
              f"  properties={len(properties)}")
        if properties:
            grafana_result = prov_g.provision_for_asset(
                asset_name, properties, token=token, org=org,
            )
            if grafana_result:
                print(f"[Grafana] Overview dashboard uploaded with "
                      f"{len(properties)} panels: "
                      f"{grafana_result.get('fullUrl')}")
            else:
                print("[Grafana] Overview provisioning failed.")

            proto_results = prov_g.provision_protocol_dashboards(
                asset_name, protocols_properties, token=token, org=org,
            )
            if proto_results:
                print(f"[Grafana] Per-protocol dashboards: "
                      f"{list(proto_results.keys())}")
                if grafana_result:
                    grafana_result["protocols"] = proto_results
        else:
            print("[Grafana] No properties found — check submodel config has "
                  "targetData rows with description/addr.")

    custom_db_result = None
    if custom_db:
        container_api = os.getenv("CONTAINER_API_URL",
                                  "http://container-api-basyx:8090")
        try:
            r = requests.post(
                f"{container_api}/containers/databridge_GUI/restart",
                timeout=15,
            )
            res = r.json()
            if res.get("success"):
                custom_db_result = {
                    "status": "restarted",
                    "container": "databridge_GUI",
                }
                print("[CustomDataBridge] Container restarted; "
                      "generator will re-scan AAS on startup.")
            else:
                custom_db_result = {
                    "status": "error",
                    "error":  res.get("error", "Unknown"),
                }
                print(f"[CustomDataBridge] Restart failed: "
                      f"{custom_db_result['error']}")
        except Exception as exc:
            custom_db_result = {"status": "error", "error": str(exc)}
            print(f"[CustomDataBridge] container-api unreachable: {exc}")

    aas_ui_base = connection_settings.get_url("ui", external=True)
    main_aas_url = (aas_ui_base
                    + f"/?aasId={base64.urlsafe_b64encode(asset_id.encode()).decode().rstrip('=')}")

    cm_url = None
    try:
        from create_container_manager_aas import build_aas as _cm_build, save_aasx as _cm_save
        cm_aas, cm_sm = _cm_build()
        cm_errors = deploy_to_server(model.DictObjectStore([cm_aas, cm_sm]))
        if not cm_errors:
            try:
                _cm_save(cm_aas, cm_sm)
            except Exception:
                pass
            cm_url = (aas_ui_base
                      + f"/?aasId={base64.urlsafe_b64encode(cm_aas.id.encode()).decode().rstrip('=')}")
    except Exception as exc:
        print(f"[ContainerManager] Auto-deploy failed: {exc}")

    response = {"status": "success",
                "message": "AAS deployed successfully.",
                "aasUrl": main_aas_url}
    if cm_url:
        response["containerManagerUrl"] = cm_url
    if idta_summary:
        response["idta"] = idta_summary
    if grafana_result:
        response["grafana"] = grafana_result
    if influx_provisioned:
        response["influxdb"] = influx_provisioned
    if custom_db_result:
        response["customDataBridge"] = custom_db_result
    return jsonify(response)

_PROTOCOL_TEMPLATES = {
    "modbus": {
        "protocol": "modbus",
        "description": "Modbus TCP — ext-Simulator Beispiel (Port 5020)",
        "host": "ext-simulator", "port": 5020, "slaveId": 1, "polling": 1000,
        "datapoints": [
            {"address": "30001", "description": "BatterySoc",         "type": "FLOAT32", "unit": "%",   "byteOrder": "AB CD", "direction": "Read"},
            {"address": "30003", "description": "BatteryVoltage",     "type": "FLOAT32", "unit": "V",   "byteOrder": "AB CD", "direction": "Read"},
            {"address": "30005", "description": "BatteryCurrent",     "type": "FLOAT32", "unit": "A",   "byteOrder": "AB CD", "direction": "Read"},
            {"address": "30009", "description": "BatteryPower",       "type": "FLOAT32", "unit": "W",   "byteOrder": "AB CD", "direction": "Read"},
            {"address": "30011", "description": "SolarPower",         "type": "FLOAT32", "unit": "W",   "byteOrder": "AB CD", "direction": "Read"},
            {"address": "30041", "description": "GridPower",          "type": "FLOAT32", "unit": "W",   "byteOrder": "AB CD", "direction": "Read"},
            {"address": "30043", "description": "GridVoltage",        "type": "FLOAT32", "unit": "V",   "byteOrder": "AB CD", "direction": "Read"},
            {"address": "40001", "description": "BatteryChargePower", "type": "FLOAT32", "unit": "W",   "byteOrder": "AB CD", "direction": "ReadWrite"},
            {"address": "40003", "description": "HeatpumpPower_SP",   "type": "FLOAT32", "unit": "W",   "byteOrder": "AB CD", "direction": "ReadWrite"},
            {"address": "40005", "description": "ConveyorSpeed_SP",   "type": "FLOAT32", "unit": "m/min","byteOrder": "AB CD", "direction": "ReadWrite"},
        ],
    },
    "mqtt": {
        "protocol": "mqtt",
        "description": "MQTT — ext-Simulator via Mosquitto Broker",
        "broker": "mosquitto", "port": 1883, "qos": 0,
        "datapoints": [
            {"topic": "simulation/solar/power",          "description": "SolarPower",        "type": "FLOAT32", "unit": "W",    "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation/solar/voltage",        "description": "SolarVoltage",      "type": "FLOAT32", "unit": "V",    "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation/solar/irradiance",     "description": "SolarIrradiance",   "type": "FLOAT32", "unit": "W/m²", "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation/heatpump/power",       "description": "HeatpumpPower",     "type": "FLOAT32", "unit": "W",    "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation/heatpump/flow_temp",   "description": "HeatpumpFlowTemp",  "type": "FLOAT32", "unit": "°C",   "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation/heatpump/cop",         "description": "HeatpumpCOP",       "type": "FLOAT32", "unit": "",     "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation/control/heatpump_power","description": "HeatpumpPower_SP", "type": "FLOAT32", "unit": "W",   "jsonPath": "value", "direction": "ReadWrite"},
        ],
    },
    "http": {
        "protocol": "http",
        "description": "HTTP/REST — ext-Simulator API (Port 8082)",
        "baseUrl": "http://ext-simulator:8082", "method": "GET", "polling": 5000,
        "datapoints": [
            {"address": "/api/weather/temperature", "description": "WeatherTemperature", "type": "FLOAT32", "unit": "°C",  "jsonPath": "value", "direction": "Read"},
            {"address": "/api/weather/humidity",    "description": "WeatherHumidity",    "type": "FLOAT32", "unit": "%",   "jsonPath": "value", "direction": "Read"},
            {"address": "/api/weather/wind_speed",  "description": "WeatherWindSpeed",   "type": "FLOAT32", "unit": "m/s", "jsonPath": "value", "direction": "Read"},
            {"address": "/api/grid/power",          "description": "GridPower",          "type": "FLOAT32", "unit": "W",   "jsonPath": "value", "direction": "Read"},
            {"address": "/api/grid/voltage",        "description": "GridVoltage",        "type": "FLOAT32", "unit": "V",   "jsonPath": "value", "direction": "Read"},
            {"address": "/api/grid/frequency",      "description": "GridFrequency",      "type": "FLOAT32", "unit": "Hz",  "jsonPath": "value", "direction": "Read"},
            {"address": "/api/control/ev_charge_power", "description": "EV_ChargePower_SP", "type": "FLOAT32", "unit": "kW", "jsonPath": "value", "direction": "ReadWrite", "method": "PUT"},
        ],
    },
    "opcua": {
        "protocol": "opcua",
        "description": "OPC-UA — ext-Simulator (Port 4840)",
        "serverUrl": "opc.tcp://ext-simulator:4840/simulation/",
        "datapoints": [
            {"nodeId": "ns=2;i=1001", "description": "Robot_Joint1_Position",  "type": "FLOAT32", "unit": "°",     "samplingInterval": 500, "direction": "Read"},
            {"nodeId": "ns=2;i=1002", "description": "Robot_Joint2_Position",  "type": "FLOAT32", "unit": "°",     "samplingInterval": 500, "direction": "Read"},
            {"nodeId": "ns=2;i=1003", "description": "Robot_Speed",            "type": "FLOAT32", "unit": "mm/s",  "samplingInterval": 500, "direction": "Read"},
            {"nodeId": "ns=2;i=1004", "description": "Conveyor_Speed",         "type": "FLOAT32", "unit": "m/min", "samplingInterval": 500, "direction": "Read"},
            {"nodeId": "ns=2;i=1005", "description": "Conveyor_Running",       "type": "BOOL",    "unit": "",      "samplingInterval": 500, "direction": "Read"},
            {"nodeId": "ns=2;i=2001", "description": "BatteryChargePower_SP",  "type": "FLOAT32", "unit": "W",     "samplingInterval": 500, "direction": "ReadWrite"},
            {"nodeId": "ns=2;i=2002", "description": "HeatpumpPower_SP",       "type": "FLOAT32", "unit": "W",     "samplingInterval": 500, "direction": "ReadWrite"},
            {"nodeId": "ns=2;i=2003", "description": "ConveyorSpeed_SP",       "type": "FLOAT32", "unit": "m/min", "samplingInterval": 500, "direction": "ReadWrite"},
        ],
    },
    "kafka": {
        "protocol": "kafka",
        "description": "Kafka — ext-Simulator EV-Ladestation (Broker ext-kafka:9092)",
        "broker": "ext-kafka:9092", "groupId": "databridge", "seekTo": "latest",
        "datapoints": [
            {"topic": "simulation.ev.soc",   "description": "EV_StateOfCharge",  "type": "FLOAT32", "unit": "%",   "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation.ev.power", "description": "EV_ChargingPower",  "type": "FLOAT32", "unit": "kW",  "jsonPath": "value", "direction": "Read"},
            {"topic": "simulation.ev",       "description": "EV_SessionEnergy",  "type": "FLOAT32", "unit": "kWh", "jsonPath": "session_energy", "direction": "Read"},
            {"topic": "simulation.ev",       "description": "EV_ChargingCurrent","type": "FLOAT32", "unit": "A",   "jsonPath": "charging_current", "direction": "Read"},
        ],
    },
    "bacnet": {
        "protocol": "bacnet",
        "description": "BACnet/IP — ext-Simulator Gerät (device-instance=100, UDP 47808)",
        "host": "ext-simulator", "port": 47808, "deviceInstance": 100, "timeout": 3000,
        "datapoints": [
            {"objectId": "analogInput:0", "propertyId": "presentValue", "description": "BatterySoc",         "type": "FLOAT32", "unit": "%",     "direction": "Read"},
            {"objectId": "analogInput:1", "propertyId": "presentValue", "description": "BatteryVoltage",     "type": "FLOAT32", "unit": "V",     "direction": "Read"},
            {"objectId": "analogInput:2", "propertyId": "presentValue", "description": "SolarPower",         "type": "FLOAT32", "unit": "W",     "direction": "Read"},
            {"objectId": "analogInput:3", "propertyId": "presentValue", "description": "HeatpumpPower",      "type": "FLOAT32", "unit": "W",     "direction": "Read"},
            {"objectId": "analogInput:4", "propertyId": "presentValue", "description": "WeatherTemperature", "type": "FLOAT32", "unit": "°C",    "direction": "Read"},
            {"objectId": "analogInput:5", "propertyId": "presentValue", "description": "GridFrequency",      "type": "FLOAT32", "unit": "Hz",    "direction": "Read"},
            {"objectId": "analogOutput:0","propertyId": "presentValue", "description": "BatteryChargePower", "type": "FLOAT32", "unit": "W",     "direction": "ReadWrite"},
            {"objectId": "analogOutput:1","propertyId": "presentValue", "description": "HeatpumpPower_SP",   "type": "FLOAT32", "unit": "W",     "direction": "ReadWrite"},
            {"objectId": "analogOutput:2","propertyId": "presentValue", "description": "ConveyorSpeed_SP",   "type": "FLOAT32", "unit": "m/min", "direction": "ReadWrite"},
        ],
    },
    "ocpp": {
        "protocol": "ocpp",
        "description": "OCPP 1.6 — Ladestation CP001 (DataBridge Central System Port 9000)",
        "serverUrl": "ws://databridge_GUI:9000", "chargePointId": "CP001", "ocppVersion": "1.6",
        "datapoints": [
            {"measurand": "Energy.Active.Import.Register", "description": "SessionEnergy",    "type": "FLOAT32", "unit": "kWh", "direction": "Read"},
            {"measurand": "Power.Active.Import",           "description": "ChargingPower",    "type": "FLOAT32", "unit": "kW",  "direction": "Read"},
            {"measurand": "SoC",                           "description": "BatterySOC",       "type": "FLOAT32", "unit": "%",   "direction": "Read"},
            {"measurand": "Current.Import",                "description": "ChargingCurrent",  "type": "FLOAT32", "unit": "A",   "direction": "Read"},
            {"measurand": "Power.Active.Import", "phase": "L1", "description": "ChargingPower_L1", "type": "FLOAT32", "unit": "W", "direction": "Read"},
            {"measurand": "MaxChargingCurrentSoftLimit", "description": "MaxChargingPower_SP",
             "type": "FLOAT32", "unit": "kW", "direction": "ReadWrite",
             "ocppCommand": "ChangeConfiguration", "ocppConfigKey": "MaxChargingCurrentSoftLimit"},
            {"measurand": "HeatpumpPowerSetpoint", "description": "HeatpumpPower_SP",
             "type": "FLOAT32", "unit": "W", "direction": "ReadWrite",
             "ocppCommand": "ChangeConfiguration", "ocppConfigKey": "HeatpumpPowerSetpoint"},
        ],
    },
    "dlms": {
        "protocol": "dlms",
        "description": "DLMS/COSEM — ext-Simulator Stromzähler (TCP Port 4059)",
        "host": "ext-simulator", "port": 4059, "clientId": 16, "logicalDevice": 1, "authLevel": "none",
        "datapoints": [
            {"obisCode": "1.0.1.8.0.255",  "attribute": 2, "description": "ActiveEnergyImport",  "type": "FLOAT64", "unit": "kWh", "direction": "Read"},
            {"obisCode": "1.0.2.8.0.255",  "attribute": 2, "description": "ActiveEnergyExport",  "type": "FLOAT64", "unit": "kWh", "direction": "Read"},
            {"obisCode": "1.0.1.7.0.255",  "attribute": 2, "description": "ActivePower",          "type": "FLOAT64", "unit": "W",   "direction": "Read"},
            {"obisCode": "1.0.32.7.0.255", "attribute": 2, "description": "VoltageL1",            "type": "FLOAT64", "unit": "V",   "direction": "Read"},
            {"obisCode": "1.0.52.7.0.255", "attribute": 2, "description": "VoltageL2",            "type": "FLOAT64", "unit": "V",   "direction": "Read"},
            {"obisCode": "1.0.72.7.0.255", "attribute": 2, "description": "VoltageL3",            "type": "FLOAT64", "unit": "V",   "direction": "Read"},
            {"obisCode": "1.0.31.7.0.255", "attribute": 2, "description": "CurrentL1",            "type": "FLOAT64", "unit": "A",   "direction": "Read"},
            {"obisCode": "1.0.14.7.0.255", "attribute": 2, "description": "Frequency",            "type": "FLOAT64", "unit": "Hz",  "direction": "Read"},
            {"obisCode": "1.1.0.8.0.255",  "attribute": 2, "description": "BatterySOC_Custom",    "type": "FLOAT64", "unit": "%",   "direction": "Read"},
            {"obisCode": "0.1.24.3.0.255", "attribute": 2, "description": "BatteryChargePower_SP","type": "FLOAT64", "unit": "W",   "direction": "ReadWrite"},
            {"obisCode": "0.1.24.4.0.255", "attribute": 2, "description": "HeatpumpPower_SP",     "type": "FLOAT64", "unit": "W",   "direction": "ReadWrite"},
            {"obisCode": "0.1.24.5.0.255", "attribute": 2, "description": "ConveyorSpeed_SP",     "type": "FLOAT64", "unit": "m/min","direction": "ReadWrite"},
        ],
    },
}

@app.route('/api/download_template/<protocol>', methods=['GET'])
def download_template(protocol):
    import io
    tmpl = _PROTOCOL_TEMPLATES.get(protocol.lower())
    if not tmpl:
        return jsonify({'status': 'error', 'message': f'No template for protocol: {protocol}'}), 404
    buf = io.BytesIO(json.dumps(tmpl, indent=2, ensure_ascii=False).encode('utf-8'))
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype='application/json', as_attachment=True,
                     download_name=f'template_{protocol.lower()}.json')

@app.route('/api/download_aas', methods=['GET'])
def download_aas():
    filepath = os.path.join(os.path.dirname(__file__), "generated_aas.aasx")
    if os.path.exists(filepath):
        from flask import send_file
        return send_file(filepath, as_attachment=True, download_name="modeled_aas.aasx")
    return jsonify({"status": "error", "message": "Not found"}), 404

@app.route('/api/download_databridge_config', methods=['GET'])
def download_databridge_config():
    import io, zipfile
    from flask import send_file

    aasx_path = os.path.join(os.path.dirname(__file__), "generated_aas.aasx")
    if not os.path.exists(aasx_path):
        return jsonify({"status": "error",
                        "message": "No AAS generated yet. Click 'Generate & Upload AAS' first."}), 404

    sys.path.insert(0, os.path.dirname(__file__))
    from generate_configuration_offbasyx import build_official_configs

    aas_server_url = os.getenv("AAS_SERVER_URL", "http://aas-env:8081")
    configs = build_official_configs(aas_server_url)

    if not configs:
        return jsonify({"status": "error",
                        "message": "No DataBridge configuration could be generated. "
                                   "Make sure your submodels have protocol qualifiers."}), 400

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, content in configs.items():
            if isinstance(content, (list, dict)):
                zf.writestr(filename, json.dumps(content, indent=2))
            else:
                zf.writestr(filename, str(content))
    buf.seek(0)

    return send_file(buf, as_attachment=True,
                     download_name="databridge_configs.zip",
                     mimetype="application/zip")

@app.route('/api/deploy_databridge', methods=['POST'])
def deploy_databridge():
    container_api = os.getenv("CONTAINER_API_URL", "http://container-api-basyx:8090")
    container_name = "databridge_GUI"

    try:
        requests.post(f"{container_api}/containers/databridge-official/stop", timeout=10)
    except Exception:
        pass

    try:
        r = requests.post(f"{container_api}/containers/{container_name}/restart", timeout=15)
        res = r.json()
        if res.get("success"):
            return jsonify({"status": "success",
                            "message": f"Custom DataBridge container '{container_name}' restarted."})
        else:
            return jsonify({"status": "error",
                            "message": res.get("error", "Unknown error from container-api")}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/deploy_container_manager', methods=['POST'])
def deploy_container_manager():
    try:
        from create_container_manager_aas import build_aas, save_aasx
        aas, sm = build_aas()

        errors = deploy_to_server(model.DictObjectStore([aas, sm]))
        if errors:
            return jsonify({"status": "error",
                            "message": "Deploy failed: " + "; ".join(errors)}), 500
        try:
            save_aasx(aas, sm)
        except Exception:
            pass

        aas_url = (connection_settings.get_url("ui", external=True)
                   + f"/?aasId={base64.urlsafe_b64encode(aas.id.encode()).decode().rstrip('=')}")
        return jsonify({
            "status":  "success",
            "message": "ContainerManager AAS deployed.",
            "aasUrl":  aas_url,
            "containers": len([
                el for el in sm.submodel_element
                if el.id_short == "ManagedContainers"
            ]),
        })
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

@app.route('/api/deploy_official_databridge', methods=['POST'])
def deploy_official_databridge():
    import io, contextlib

    project_root  = os.path.join(os.path.dirname(__file__), "project_root")
    custom_db_dir = os.path.join(project_root, "CustomDatabridge")
    out_dir       = os.path.join(custom_db_dir, "official-config")

    sys.path.insert(0, custom_db_dir)
    from generate_databridge_config_GUI import (
        build_configs, build_official_configs, write_official_configs
    )

    aas_server_url = os.getenv("AAS_SERVER_URL", "http://aas-env:8081")
    container_api  = os.getenv("CONTAINER_API_URL", "http://container-api-basyx:8090")
    container_name = "databridge-official"
    log_lines      = []

    try:
        requests.post(f"{container_api}/containers/databridge_GUI/stop", timeout=10)
    except Exception:
        pass

    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sources, sinks, routes, transformers, write_routes = build_configs(aas_server_url)
            (plc4x, mqtt_c, http_c, opcua, kafka,
             aas_s, off_r, j_xfmrs, j_files) = build_official_configs(sources, sinks, routes)
        log_lines.append(buf.getvalue())

        if not off_r:
            return jsonify({
                "status":  "error",
                "message": "No routes generated. Make sure your AAS submodels have "
                           "CommunicationConfiguration SMCs with supported protocols "
                           "(Modbus, MQTT, HTTP, OPC-UA, Kafka).",
                "log":     "\n".join(log_lines)
            }), 400

        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            write_official_configs(out_dir, plc4x, mqtt_c, http_c, opcua, kafka,
                                    aas_s, off_r, j_xfmrs, j_files)
        log_lines.append(buf2.getvalue())
        log_lines.append(f"✅ Official configs written → {out_dir}  ({len(off_r)} routes)")

    except Exception as e:
        import traceback
        return jsonify({
            "status":  "error",
            "message": f"Config generation failed: {e}",
            "log":     "\n".join(log_lines) + "\n" + traceback.format_exc()
        }), 500

    log = "\n".join(log_lines)

    try:
        r = requests.post(f"{container_api}/containers/{container_name}/restart", timeout=15)
        res = r.json()
        if res.get("success"):
            return jsonify({"status": "success",
                            "message": f"Official BaSyx DataBridge deployed ({len(off_r)} routes).",
                            "log": log})
        else:
            r2 = requests.post(f"{container_api}/containers/{container_name}/start", timeout=15)
            res2 = r2.json()
            if res2.get("success"):
                return jsonify({"status": "success",
                                "message": "Official BaSyx DataBridge started.",
                                "log": log})
            return jsonify({"status": "error",
                            "message": res2.get("error", "Could not start container."),
                            "log": log}), 500
    except Exception as e:
        return jsonify({"status": "error",
                        "message": f"Configs written but container restart failed: {e}",
                        "log": log}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
