# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

from dataclasses import dataclass

import basyx.aas.model as model

WOT_TD       = "https://www.w3.org/2019/wot/td#"
WOT_HYPER    = "https://www.w3.org/2019/wot/hypermedia#"
WOT_JSON     = "https://www.w3.org/2019/wot/json-schema#"
WOT_MODBUS   = "https://www.w3.org/2019/wot/modbus#"
WOT_MQTT     = "https://www.w3.org/2019/wot/mqtt#"
WOT_HTTP     = "https://www.w3.org/2011/http#"
OPCUA_NS     = "http://opcfoundation.org/UA/#"
IDTA_TS      = "https://admin-shell.io/idta/TimeSeries/"
ECLASS       = "0173-1#02-"
PROJECT_WOT  = "https://aes.basyx.org/wot#"

@dataclass(frozen=True)
class QualifierSpec:
    iri: str
    source: str
    description: str
    value_type: type

_S = model.datatypes.String
_I = model.datatypes.Int

QUALIFIER_VOCABULARY: dict[str, QualifierSpec] = {
    "ModbusRegister":     QualifierSpec(
        WOT_MODBUS + "address", "W3C WoT Modbus Binding",
        "Modbus register address", _S),
    "ModbusRegisterType": QualifierSpec(
        WOT_MODBUS + "entity", "W3C WoT Modbus Binding",
        "Holding / Input Register / Coil / Discrete Input", _S),
    "ModbusDataType":     QualifierSpec(
        WOT_MODBUS + "type", "W3C WoT Modbus Binding",
        "FLOAT32 / INT16 / UINT16 / INT32 / BOOL / STRING …", _S),
    "ModbusType":         QualifierSpec(
        WOT_MODBUS + "byteOrder", "W3C WoT Modbus Binding",
        "Byte order: AB CD, CD AB, …", _S),
    "ModbusFunction":     QualifierSpec(
        WOT_MODBUS + "function", "W3C WoT Modbus Binding",
        "readHoldingRegisters / writeSingleRegister / …", _S),
    "ModbusIP":           QualifierSpec(
        WOT_TD + "base", "W3C WoT Thing Description",
        "Slave IP address (forms.base scope)", _S),
    "ModbusPort":         QualifierSpec(
        WOT_TD + "base", "W3C WoT Thing Description",
        "Slave TCP port", _I),
    "ModbusSlaveID":      QualifierSpec(
        WOT_MODBUS + "unitID", "W3C WoT Modbus Binding",
        "Modbus unit / slave ID", _I),

    "MqttTopic":          QualifierSpec(
        WOT_MQTT + "filter", "W3C WoT MQTT Binding",
        "MQTT topic / topic filter for SUBSCRIBE", _S),
    "MqttBroker":         QualifierSpec(
        WOT_TD + "base", "W3C WoT Thing Description",
        "MQTT broker host", _S),
    "MqttPort":           QualifierSpec(
        WOT_TD + "base", "W3C WoT Thing Description",
        "MQTT broker port", _I),
    "MqttQoS":            QualifierSpec(
        WOT_MQTT + "qos", "W3C WoT MQTT Binding",
        "Quality of Service: 0 / 1 / 2", _I),
    "MqttJsonPath":       QualifierSpec(
        WOT_JSON + "JsonPointer", "W3C WoT JSON Schema",
        "JSON pointer / path inside the payload", _S),

    "HttpUrl":            QualifierSpec(
        WOT_HTTP + "requestURI", "W3C HTTP-in-RDF Vocabulary",
        "HTTP endpoint URL", _S),
    "HttpMethod":         QualifierSpec(
        WOT_HTTP + "methodName", "W3C HTTP-in-RDF Vocabulary",
        "GET / POST / PUT / DELETE", _S),
    "HttpJsonPath":       QualifierSpec(
        WOT_JSON + "JsonPointer", "W3C WoT JSON Schema",
        "JSON pointer in HTTP response payload", _S),
    "HttpFormat":         QualifierSpec(
        WOT_HYPER + "forContentType", "W3C WoT Hypermedia",
        "Response content-type (JSON / XML / CSV)", _S),

    "HttpAuthType":       QualifierSpec(
        WOT_TD + "securityScheme", "W3C WoT Thing Description",
        "Auth strategy: none / bearer / api_key_header / "
        "api_key_query / oauth2_cc / basic", _S),
    "HttpBearerToken":    QualifierSpec(
        WOT_TD + "BearerSecurityScheme", "W3C WoT Thing Description",
        "Static Bearer token", _S),
    "HttpApiKey":         QualifierSpec(
        WOT_TD + "APIKeySecurityScheme", "W3C WoT Thing Description",
        "API-Key value", _S),
    "HttpApiKeyHeader":   QualifierSpec(
        WOT_TD + "in", "W3C WoT Thing Description",
        "Header name carrying the API key (default X-API-Key)", _S),
    "HttpApiKeyQuery":    QualifierSpec(
        WOT_TD + "in", "W3C WoT Thing Description",
        "Query-param name carrying the API key (default 'apikey')", _S),
    "OAuth2TokenUrl":     QualifierSpec(
        WOT_TD + "OAuth2SecurityScheme", "RFC 6749 §4.4",
        "OAuth2 token endpoint URL", _S),
    "OAuth2ClientId":     QualifierSpec(
        WOT_TD + "clientId", "RFC 6749 §4.4",
        "OAuth2 client identifier", _S),
    "OAuth2ClientSecret": QualifierSpec(
        WOT_TD + "clientSecret", "RFC 6749 §4.4",
        "OAuth2 client secret", _S),
    "OAuth2Scope":        QualifierSpec(
        WOT_TD + "scopes", "RFC 6749",
        "OAuth2 scope(s), space-separated", _S),
    "HttpUsername":       QualifierSpec(
        WOT_TD + "BasicSecurityScheme", "W3C WoT Thing Description",
        "HTTP Basic-auth username", _S),
    "HttpPassword":       QualifierSpec(
        WOT_TD + "BasicSecurityScheme", "W3C WoT Thing Description",
        "HTTP Basic-auth password", _S),
    "HttpQueryParams":    QualifierSpec(
        WOT_TD + "uriVariables", "W3C WoT Thing Description",
        "Extra query parameters as ``k=v&k2=v2`` string", _S),

    "OpcuaNodeId":            QualifierSpec(
        OPCUA_NS + "NodeId", "OPC Foundation",
        "OPC UA NodeId (e.g. ns=2;s=Tag.Path)", _S),
    "OpcuaServer":            QualifierSpec(
        OPCUA_NS + "EndpointUrl", "OPC Foundation",
        "OPC UA endpoint URL (opc.tcp://…)", _S),
    "OpcuaSamplingInterval":  QualifierSpec(
        OPCUA_NS + "SamplingInterval", "OPC Foundation",
        "Subscription sampling interval (ms)", _I),

    "KafkaTopic":         QualifierSpec(
        PROJECT_WOT + "kafkaTopic", "Project (no W3C binding yet)",
        "Apache Kafka topic name", _S),
    "KafkaJsonPath":      QualifierSpec(
        WOT_JSON + "JsonPointer", "W3C WoT JSON Schema",
        "JSON pointer in Kafka record value", _S),

    "AmperixSensorId":    QualifierSpec(
        PROJECT_WOT + "amperixSensorId", "Project / AMPERIX-specific",
        "AMPERIX device internal sensor identifier", _S),
    "AmperixMeasType":    QualifierSpec(
        PROJECT_WOT + "amperixMeasureType", "Project / AMPERIX-specific",
        "AMPERIX aggregation type (avg_mm_gauge_seq, …)", _S),

    "DataType":           QualifierSpec(
        WOT_JSON + "type", "W3C WoT JSON Schema",
        "Logical data type (FLOAT32, INT16, BOOL, STRING)", _S),
    "Unit":               QualifierSpec(
        ECLASS + "BAA959#005", "ECLASS Basic — Unit of measurement",
        "Engineering unit (°C, V, kg, m/s, …)", _S),
    "PollingInterval":    QualifierSpec(
        WOT_TD + "pollingInterval", "W3C WoT Thing Description",
        "Polling interval (ms) for non-event data sources", _I),
    "Direction":          QualifierSpec(
        WOT_TD + "InteractionAffordance", "W3C WoT Thing Description",
        "Data flow direction: Read | Write | ReadWrite (default: Read)",
        _S),

    "InfluxServerUrl":    QualifierSpec(
        IDTA_TS + "Endpoint/1/1", "IDTA 02008-1-1 TimeSeries",
        "InfluxDB v2 HTTP endpoint URL", _S),
    "InfluxToken":        QualifierSpec(
        IDTA_TS + "Endpoint/AccessToken/1/1", "IDTA-aligned",
        "InfluxDB v2 API token", _S),
    "InfluxOrg":          QualifierSpec(
        IDTA_TS + "Endpoint/Organisation/1/1", "IDTA-aligned",
        "InfluxDB organisation name", _S),
    "InfluxBucket":       QualifierSpec(
        IDTA_TS + "Endpoint/Bucket/1/1", "IDTA-aligned",
        "InfluxDB v2 bucket name", _S),
    "InfluxMeasurement":  QualifierSpec(
        IDTA_TS + "Metadata/Name/1/1", "IDTA 02008-1-1 TimeSeries",
        "InfluxDB measurement name", _S),

    "SinkMqttTopic":      QualifierSpec(
        WOT_MQTT + "filter", "W3C WoT MQTT Binding",
        "MQTT topic on which the value is republished", _S),
    "SinkMqttBroker":     QualifierSpec(
        WOT_TD + "base", "W3C WoT Thing Description",
        "MQTT sink broker host", _S),
    "SinkMqttPort":       QualifierSpec(
        WOT_TD + "base", "W3C WoT Thing Description",
        "MQTT sink broker port", _I),
}

ALIASES: dict[str, str] = {
    "OpcUaNodeId":           "OpcuaNodeId",
    "OPCUANodeId":           "OpcuaNodeId",
    "opcua_node_id":         "OpcuaNodeId",
    "opcua_server":          "OpcuaServer",
    "HttpPath":              "HttpJsonPath",
    "http_url":              "HttpUrl",
    "http_json_path":        "HttpJsonPath",
    "mqtt_source_topic":     "MqttTopic",
    "mqtt_source_broker":    "MqttBroker",
    "mqtt_source_port":      "MqttPort",
    "mqtt_topic":            "SinkMqttTopic",
    "mqtt_broker":           "SinkMqttBroker",
    "mqtt_port":             "SinkMqttPort",
    "influx_endpoint":       "InfluxServerUrl",
    "influx_database":       "InfluxBucket",
    "influx_measurement":    "InfluxMeasurement",
}

def canonical_name(name: str) -> str:
    if name in QUALIFIER_VOCABULARY:
        return name
    return ALIASES.get(name, name)

def get_spec(name: str) -> QualifierSpec | None:
    return QUALIFIER_VOCABULARY.get(canonical_name(name))

def get_semantic_id(name: str) -> model.ExternalReference | None:
    spec = get_spec(name)
    if spec is None:
        return None
    return model.ExternalReference(
        (model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE, value=spec.iri),)
    )

def make_qualifier(name: str, value, *, value_type=None) -> model.Qualifier:
    canonical = canonical_name(name)
    spec = QUALIFIER_VOCABULARY.get(canonical)
    vt = value_type or (spec.value_type if spec else _S)

    coerced = value
    if vt is _I:
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            coerced = 0
    else:
        coerced = "" if value is None else str(value)

    q = model.Qualifier(type_=canonical, value_type=vt, value=coerced)
    sid = get_semantic_id(canonical)
    if sid is not None:
        q.semantic_id = sid
    return q

def lookup_value(quals: dict, *names: str, default=None):
    if not quals:
        return default
    for name in names:
        canonical = canonical_name(name)
        if canonical in quals:
            return quals[canonical]
        for alias, target in ALIASES.items():
            if target == canonical and alias in quals:
                return quals[alias]
    return default
