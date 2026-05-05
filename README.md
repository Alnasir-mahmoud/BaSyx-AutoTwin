# BaSyx-AutoTwin

> **Automated Digital Twin binding for physical systems using BaSyx Asset Administration Shell (AAS)**

BaSyx-AutoTwin is a full-stack platform that **automatically creates, connects, and monitors Digital Twins** of physical assets — bridging the gap between real-world devices and their standardized digital representations based on the **IEC 63278 / IDTA Asset Administration Shell**.

---

## What is BaSyx-AutoTwin?

In Industry 4.0, a **Digital Twin** is a live digital representation of a physical asset (machine, sensor, energy system, …). Creating and maintaining this digital-physical binding is typically a manual, error-prone process.

**BaSyx-AutoTwin automates exactly this — from sensor to dashboard in one GUI:**

| # | What happens | Technology |
|---|---|---|
| 1 | Connect physical device | Modbus · MQTT · OPC-UA · Kafka · HTTP |
| 2 | DataBridge routes live data automatically | Custom Python Bridge / BaSyx DataBridge |
| 3 | Measurements are stored | **InfluxDB v2** (time-series) |
| 4 | Dashboards are provisioned automatically | **Grafana** (timeseries · gauge · stat · bargauge) |
| 5 | Digital Twin is created in the AAS server | **BaSyx AAS** (IEC 63278 / IDTA) |
| 6 | Monitor & control in the browser | **BaSyx Web UI** with custom plugins |

Everything is configured through the **Studio GUI** — no manual JSON editing, no command line.

### Why a GUI?

Connecting a physical system to a Digital Twin normally requires:
- Manually writing AAS submodels
- Configuring DataBridge routes (JSON)
- Setting up InfluxDB buckets and Grafana datasources
- Manually linking all services together

**BaSyx-AutoTwin handles all of this in a single guided workflow — step by step through the GUI.**

---

## Core Concepts

```
┌─────────────────────────────────────────────────────────────┐
│                     Physical World                          │
│   Modbus PLC · MQTT Sensor · OPC-UA Device · Kafka Stream   │
└───────────────────────┬─────────────────────────────────────┘
                        │  automated binding
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    DataBridge Layer                         │
│   Custom Python Bridge  ·  Official BaSyx DataBridge (Java) │
└──────────┬────────────────────────────┬─────────────────────┘
           │                            │
           ▼                            ▼
┌──────────────────┐          ┌──────────────────────┐
│  BaSyx AAS Server│          │    InfluxDB v2        │
│  Digital Twin    │          │  (time-series data)   │
│  Submodels       │          └──────────┬───────────┘
│  Registries      │                     │
└──────────┬───────┘                     ▼
           │                   ┌──────────────────────┐
           ▼                   │       Grafana         │
┌──────────────────┐           │  auto-provisioned     │
│  BaSyx Web UI    │◀──────────│  dashboards           │
│  + AAS Plugins   │           └──────────────────────┘
└──────────────────┘
           ▲
┌──────────────────┐
│  BaSyx-AutoTwin  │  ← Studio GUI  (port 5000)
│  Studio GUI      │     configure · generate · deploy
└──────────────────┘
```

---

## Key Features

### Automated Binding
- **One-click Digital Twin** — define an asset, select a protocol, AAS + DataBridge + Grafana are deployed automatically
- **Multi-protocol** — Modbus TCP, MQTT, OPC-UA, Kafka, HTTP Polling in one interface
- **IDTA-compliant submodels** — auto-generated from official templates (AssetInterfacesDescription · AssetInterfacesMappingConfiguration · TimeSeries)

### Data Storage & Visualization
- **InfluxDB v2** — all measurements are automatically stored as time-series
- **Grafana** — dashboards automatically provisioned per asset and per protocol, no manual configuration
- **4 panel types** selectable per data point: `timeseries` · `gauge` · `stat` · `bargauge`

### Bidirectional Control
- **AAS → Physical device** — changes made in the BaSyx Web UI are written back to the real device in real time (`aas_change_listener.py` subscribes to AAS MQTT update events and dispatches writes)
- **Write-back protocols** — Modbus TCP · MQTT · OPC-UA · BACnet · OCPP · DLMS · HTTP PUT/POST
- **ContainerManager AAS** — Docker containers as AAS properties: Start / Stop / Restart / Logs in the browser
- **WebIframeViewer** — Grafana dashboards embedded inside AAS property views

### Easy Deployment
- **Studio GUI** — guided 4-step workflow, no JSON editing, no command line
- **One-command start** — `start.sh` / `start.bat` detects IP, scans ports, starts everything
- **Windows + Linux** supported

---

## Supported Protocols

The technology used depends on the selected DataBridge:

| Protocol | Official BaSyx DataBridge (Java) | Custom Python DataBridge |
|---|---|---|
| Modbus TCP | Apache PLC4X | pymodbus |
| MQTT | Apache Camel + Paho | paho-mqtt |
| OPC-UA | Apache Camel + Milo | asyncua |
| Kafka | Apache Camel + Kafka | kafka-python |
| HTTP Polling | Apache Camel + HTTP | requests |

---

## Quick Start

### Windows
```bat
start.bat
```

### Linux / macOS
```bash
chmod +x start.sh
./start.sh
```

The startup script auto-detects the host LAN IP, scans for free ports, writes `.env` + `GUI/connection.json`, runs `docker compose up -d --build` and prints all service URLs.

```bash
./start.sh          # normal start
./start.sh clean    # tear down + full rebuild
./start.sh status   # show running containers, no restart
```

**Requirements:** Docker Engine + Compose v2 · Python 3

---

## Studio Workflow

Open `http://<HOST_IP>:5000` after startup.

| Step | What happens |
|---|---|
| **1 — Connection** | Host IP + ports (auto-filled) |
| **2 — Submodels** | Define submodel names for the asset |
| **3 — Data Sources** | Configure protocol + data points per submodel |
| **4 — Deploy** | AAS is created, DataBridge started, Grafana dashboards provisioned automatically |

Each data point can be assigned a Grafana panel type: `timeseries` · `gauge` · `stat` · `bargauge`

---

## GUI Usage Guide

Open the Studio at `http://<HOST_IP>:5000`. The guided workflow has four steps.

### Step 1 — Connection

Configure how the Studio reaches the other services.

- **Host IP** — the LAN IP of the machine running Docker (auto-filled by the start script)
- **Ports** — pre-filled with defaults; change only if you modified `docker-compose.yml`
- Click **Save Connection** — the settings are stored in `GUI/connection.json` and used by all subsequent API calls

> If you ran `start.sh` / `start.bat`, IP and ports are already filled in.

### Step 2 — Submodels

Define the logical structure of the Digital Twin.

- Enter the **Asset name** (used as the AAS ID and Grafana dashboard title)
- Add one or more **Submodel names** (e.g. `Temperatures`, `Electrical`, `Status`)
- Each submodel groups related data points; it becomes an IDTA-compliant submodel in the AAS

### Step 3 — Data Sources

Configure where the live data comes from and what to do with it.

For each submodel you can add multiple **data points**:

| Field | Description |
|---|---|
| **Measurement name** | Unique identifier for this value (used as InfluxDB measurement + AAS property ID) |
| **Protocol** | `Modbus TCP` · `MQTT` · `OPC-UA` · `Kafka` · `HTTP Polling` |
| **Protocol settings** | Host/port/register for Modbus; broker/topic for MQTT; endpoint/node for OPC-UA; etc. |
| **Unit** | Physical unit (e.g. `°C`, `V`, `A`) — shown in Grafana panel title and AAS property |
| **Description** | Human-readable label (used as Grafana panel title) |
| **Grafana panel type** | `timeseries` · `gauge` · `stat` · `bargauge` — choose the best visualization per value |

**Protocol-specific settings:**

| Protocol | Required fields |
|---|---|
| Modbus TCP | PLC host, port (default 502), register address, register type (holding/input/coil) |
| MQTT | Broker host, port (default 1883), topic, optional username/password |
| OPC-UA | Server URL (opc.tcp://…), node ID |
| Kafka | Bootstrap server, topic, consumer group |
| HTTP Polling | URL, polling interval (seconds), optional auth header, JSON path to value |

### Step 4 — Deploy

Choose a DataBridge and deploy everything in one click.

**Select DataBridge:**
- **Official BaSyx DataBridge (Java)** — Apache Camel-based; uses PLC4X for Modbus, Paho for MQTT, Milo for OPC-UA
- **Custom Python DataBridge** — lightweight Python service; recommended when the Java bridge has compatibility issues (e.g. THIES firmware quirks)

**Click Deploy** — the following happens automatically:

1. **AAS created** — Asset Administration Shell with all submodels is built and uploaded to the BaSyx AAS Environment
2. **IDTA submodels generated** — `AssetInterfacesDescription`, `AssetInterfacesMappingConfiguration`, and `TimeSeries` submodels are generated from official IDTA templates and uploaded
3. **InfluxDB provisioned** — a bucket is created for this asset; the DataBridge will write into it
4. **DataBridge configured and started** — route configuration (JSON) is generated and the DataBridge Docker container is started
5. **Grafana provisioned** — InfluxDB datasource registered in Grafana; a dashboard with one panel per data point is created (panel types as selected in Step 3)

After deploy, the asset is live: data flows from the physical device → DataBridge → InfluxDB + AAS → Grafana + BaSyx Web UI.

### Additional Features

#### Container Manager AAS

The **Container Manager** is a special AAS that represents all running Docker containers as AAS properties.

- Open BaSyx Web UI (`http://<HOST_IP>:3000`) → navigate to the `ContainerManager` shell
- The `ContainerControlPlugin` renders a control panel per container: **Start / Stop / Restart / View Logs**
- All actions call the `container-api` REST service (port 8090) which manages the Docker daemon

#### Grafana Dashboard Embedded in BaSyx Web UI

The `WebIframeViewer` plugin embeds a Grafana dashboard directly inside an AAS property view.

- The AAS property stores a Grafana dashboard URL as its value
- When opened in the BaSyx Web UI, the plugin renders it as a live inline iframe — no separate browser tab needed

#### IDTA Submodel Templates

The `generate_idta_submodels.py` module generates submodels that conform to official IDTA specifications:

| Submodel | IDTA ID | Purpose |
|---|---|---|
| AssetInterfacesDescription (AID) | IDTA 02017-1-1 | Describes the communication interfaces of the asset (protocol, endpoint, data types, security) |
| AssetInterfacesMappingConfiguration (AIMC) | IDTA 02027-1-0 | Maps the AID interface properties to the AAS submodel elements (source → sink relations) |
| TimeSeries | IDTA 02008-1-1 | Links the AAS property to its time-series data in InfluxDB (endpoint, query, segments) |

These submodels are validated against the official IDTA template files in `IDTA-Templates/`.

#### Bidirectional Control — Writing back to the Physical Device

BaSyx-AutoTwin is **not read-only**. The `aas_change_listener` component runs alongside the Custom Python DataBridge and enables full control of the physical device through the Digital Twin.

**How it works:**

```
BaSyx Web UI  →  user edits a property value
                 ↓
             BaSyx AAS publishes MQTT update event
                 ↓
         aas_change_listener catches the event
                 ↓
         looks up the data source config for that property
                 ↓
         writes the new value to the physical device
```

**Supported write-back protocols:**

| Protocol | What is written |
|---|---|
| Modbus TCP | `write_registers` — float32 / int16 / uint16 encoded as register words |
| MQTT | `publish` to the configured topic |
| OPC-UA | `write_value` on the configured node |
| BACnet | `write_property` via bacpypes3 |
| OCPP | command forwarded to the OCPP Central System proxy |
| DLMS/COSEM | `write` to the configured OBIS object |
| HTTP | `PUT` or `POST` to the configured URL |

This makes it possible to, for example, set a setpoint on a PLC, switch a relay, or send a command to a charging station — all from the BaSyx Web UI, without any additional integration work.

#### Hardware Simulator

For development and testing without physical hardware, a hardware simulator is included (`simulation/`).

- Simulates Modbus registers, MQTT topics, and OPC-UA nodes with realistic sensor values
- Start/stop via the Container Manager AAS or directly via Docker

---

## DataBridge Comparison

### Protocol support per DataBridge

| Protocol | Custom Python DataBridge | Official BaSyx DataBridge (Java) |
|---|---|---|
| Modbus TCP | AAS + InfluxDB + Grafana + Control | AAS only |
| MQTT | AAS + InfluxDB + Grafana + Control | AAS only |
| OPC-UA | AAS + InfluxDB + Grafana + Control | AAS only |
| HTTP/REST | AAS + InfluxDB + Grafana + Control | AAS only |
| Kafka | AAS + InfluxDB + Grafana + Control | AAS only |
| BACnet/IP | AAS + InfluxDB + Grafana + Control | not supported |
| OCPP 1.6 | AAS + InfluxDB + Grafana + Control | not supported |
| DLMS/COSEM | AAS + InfluxDB + Grafana + Control | not supported |

**Control** = write-back from AAS to the physical device (change a value in the BaSyx Web UI → the device receives the command).

---

## Testing with JSON Configs

The `test-configs/` folder contains ready-to-use configuration files for testing each protocol without a real device. They are pre-wired to use the hardware simulator (`ext-simulator`) and work out of the box.

### Config format by protocol

#### Modbus TCP

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): AAS only

```json
{
  "protocol": "modbus",
  "host": "192.168.1.100",
  "port": 502,
  "slaveId": 1,
  "polling": 1000,
  "datapoints": [
    {
      "address": "30001",
      "type": "FLOAT32",
      "byteOrder": "AB CD",
      "description": "Temperature",
      "unit": "C",
      "direction": "Read",
      "vizType": "gauge"
    },
    {
      "address": "40001",
      "type": "FLOAT32",
      "byteOrder": "AB CD",
      "description": "Setpoint_SP",
      "unit": "C",
      "direction": "ReadWrite",
      "vizType": "gauge"
    }
  ]
}
```

| Field | Description |
|---|---|
| `host` | PLC IP address |
| `port` | Modbus TCP port (default `502`) |
| `slaveId` | Modbus slave / unit ID |
| `polling` | Read interval in milliseconds |
| `address` | Register address — `3xxxx` = input register, `4xxxx` = holding register |
| `type` | `FLOAT32` · `INT16` · `UINT16` · `BOOL` |
| `byteOrder` | `AB CD` (big-endian) or `CD AB` (little-endian) |
| `direction` | `Read` (monitor only) or `ReadWrite` (also enables write-back) |

---

#### MQTT

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): AAS only

```json
{
  "protocol": "mqtt",
  "broker": "mosquitto",
  "port": 1883,
  "qos": 0,
  "datapoints": [
    {
      "topic": "sensor/temperature",
      "description": "Temperature",
      "type": "FLOAT32",
      "unit": "C",
      "jsonPath": "value",
      "direction": "Read",
      "vizType": "gauge"
    },
    {
      "topic": "control/setpoint",
      "description": "Setpoint_SP",
      "type": "FLOAT32",
      "unit": "C",
      "jsonPath": "value",
      "direction": "ReadWrite",
      "vizType": "gauge"
    }
  ]
}
```

| Field | Description |
|---|---|
| `broker` | MQTT broker hostname or IP |
| `port` | MQTT port (default `1883`) |
| `qos` | Quality of Service: `0`, `1`, or `2` |
| `topic` | MQTT topic to subscribe/publish |
| `jsonPath` | Key to extract from JSON payload (e.g. `"value"`) — omit for plain numeric payload |
| `direction` | `Read` or `ReadWrite` |

---

#### OPC-UA

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): AAS only

```json
{
  "protocol": "opcua",
  "serverUrl": "opc.tcp://192.168.1.100:4840/",
  "datapoints": [
    {
      "nodeId": "ns=2;i=1001",
      "description": "Temperature",
      "type": "FLOAT32",
      "unit": "C",
      "samplingInterval": 500,
      "direction": "Read",
      "vizType": "gauge"
    },
    {
      "nodeId": "ns=2;i=2001",
      "description": "Setpoint_SP",
      "type": "FLOAT32",
      "unit": "C",
      "samplingInterval": 500,
      "direction": "ReadWrite",
      "vizType": "gauge"
    }
  ]
}
```

| Field | Description |
|---|---|
| `serverUrl` | OPC-UA server endpoint (`opc.tcp://...`) |
| `nodeId` | OPC-UA node identifier (`ns=2;i=1001` or `ns=2;s=MyNode`) |
| `samplingInterval` | Subscription sampling interval in milliseconds |
| `direction` | `Read` or `ReadWrite` |

---

#### HTTP / REST

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): AAS only

```json
{
  "protocol": "http",
  "baseUrl": "http://192.168.1.100:8080",
  "method": "GET",
  "polling": 5000,
  "datapoints": [
    {
      "address": "/api/sensor/temperature",
      "description": "Temperature",
      "type": "FLOAT32",
      "unit": "C",
      "jsonPath": "value",
      "direction": "Read",
      "vizType": "gauge"
    },
    {
      "address": "/api/control/setpoint",
      "description": "Setpoint_SP",
      "type": "FLOAT32",
      "unit": "C",
      "jsonPath": "value",
      "direction": "ReadWrite",
      "method": "PUT",
      "vizType": "gauge"
    }
  ]
}
```

| Field | Description |
|---|---|
| `baseUrl` | Base URL of the REST API |
| `method` | Default HTTP method for reads: `GET` |
| `polling` | Poll interval in milliseconds |
| `address` | URL path appended to `baseUrl` |
| `jsonPath` | JSON key to extract from response body |
| `method` (per datapoint) | Override method for write: `PUT` or `POST` |
| `direction` | `Read` or `ReadWrite` |

---

#### Kafka

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): AAS only

```json
{
  "protocol": "kafka",
  "broker": "kafka:9092",
  "groupId": "databridge",
  "seekTo": "latest",
  "datapoints": [
    {
      "topic": "sensors.temperature",
      "description": "Temperature",
      "type": "FLOAT32",
      "unit": "C",
      "jsonPath": "value",
      "direction": "Read",
      "vizType": "timeseries"
    }
  ]
}
```

| Field | Description |
|---|---|
| `broker` | Kafka bootstrap server (`host:port`) |
| `groupId` | Kafka consumer group ID |
| `seekTo` | `latest` (only new messages) or `earliest` (replay from beginning) |
| `topic` | Kafka topic to consume |
| `jsonPath` | JSON key to extract from the message value |

---

#### BACnet/IP

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): not supported

```json
{
  "protocol": "bacnet",
  "host": "192.168.1.100",
  "port": 47808,
  "deviceInstance": 100,
  "timeout": 3000,
  "datapoints": [
    {
      "objectId": "analogInput:0",
      "propertyId": "presentValue",
      "description": "ZoneTemperature",
      "type": "FLOAT32",
      "unit": "C",
      "direction": "Read",
      "vizType": "gauge"
    },
    {
      "objectId": "analogOutput:0",
      "propertyId": "presentValue",
      "description": "TempSetpoint_SP",
      "type": "FLOAT32",
      "unit": "C",
      "direction": "ReadWrite",
      "vizType": "gauge"
    }
  ]
}
```

| Field | Description |
|---|---|
| `host` | BACnet device IP |
| `port` | BACnet/IP UDP port (default `47808`) |
| `deviceInstance` | BACnet device instance number |
| `timeout` | Request timeout in milliseconds |
| `objectId` | BACnet object identifier (e.g. `analogInput:0`, `binaryOutput:2`) |
| `propertyId` | BACnet property — typically `presentValue` |

---

#### OCPP 1.6

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): not supported

```json
{
  "protocol": "ocpp",
  "serverUrl": "ws://databridge_GUI:9000",
  "chargePointId": "CP001",
  "ocppVersion": "1.6",
  "polling": 10000,
  "datapoints": [
    {
      "measurand": "Power.Active.Import",
      "description": "ChargingPower",
      "type": "FLOAT32",
      "unit": "kW",
      "direction": "Read",
      "vizType": "timeseries"
    },
    {
      "measurand": "MaxChargingCurrent",
      "description": "MaxChargingCurrent_SP",
      "type": "FLOAT32",
      "unit": "A",
      "direction": "ReadWrite",
      "ocppCommand": "ChangeConfiguration",
      "ocppConfigKey": "MaxChargingCurrent",
      "vizType": "gauge"
    }
  ]
}
```

| Field | Description |
|---|---|
| `serverUrl` | WebSocket URL of the OCPP Central System (the DataBridge acts as CS) |
| `chargePointId` | OCPP charge point identity string |
| `ocppVersion` | `1.6` |
| `measurand` | OCPP measurand name from the MeterValues message |
| `ocppCommand` | Command for write-back (e.g. `ChangeConfiguration`, `RemoteStartTransaction`) |
| `ocppConfigKey` | Configuration key for `ChangeConfiguration` commands |

---

#### DLMS/COSEM

Custom Python DataBridge: AAS + InfluxDB + Grafana + Control
Official BaSyx DataBridge (Java): not supported

```json
{
  "protocol": "dlms",
  "host": "192.168.1.100",
  "port": 4059,
  "clientId": 16,
  "logicalDevice": 1,
  "authLevel": "none",
  "datapoints": [
    {
      "obisCode": "1.0.1.7.0.255",
      "attribute": 2,
      "description": "ActivePower",
      "type": "FLOAT64",
      "unit": "W",
      "direction": "Read",
      "vizType": "timeseries"
    },
    {
      "obisCode": "0.1.24.3.0.255",
      "attribute": 2,
      "description": "PowerLimit_SP",
      "type": "FLOAT64",
      "unit": "W",
      "direction": "ReadWrite",
      "vizType": "gauge"
    }
  ]
}
```

| Field | Description |
|---|---|
| `host` | Meter IP address |
| `port` | TCP port — WRAPPER mode default `4059` |
| `clientId` | DLMS client ID (default `16`) |
| `logicalDevice` | Logical device address (default `1`) |
| `authLevel` | `none` · `low` · `high` |
| `obisCode` | OBIS code of the data object (e.g. `1.0.1.7.0.255`) |
| `attribute` | COSEM attribute index (default `2` = value) |

---

### vizType field

The `vizType` field is used on every datapoint and tells the Grafana dashboard builder which panel type to render. If omitted, `timeseries` is used.

| Value | Panel type | Best for |
|---|---|---|
| `timeseries` | Line chart over time | Power, current, continuously changing values |
| `gauge` | Circular gauge with threshold zones | Temperatures, percentages, setpoints |
| `stat` | Single large value | Voltages, energy totals, status values |
| `bargauge` | Horizontal bar with fill | Fan speed, duty cycle, capacity |

---

### Data types

The `type` field is used across all protocols:

| Type | Description |
|---|---|
| `FLOAT32` | 32-bit IEEE 754 float (most common) |
| `FLOAT64` | 64-bit double (used with DLMS) |
| `INT16` | Signed 16-bit integer |
| `UINT16` | Unsigned 16-bit integer |
| `INT32` | Signed 32-bit integer |
| `BOOL` | Boolean (0 or 1) |

### direction field

| Value | Behaviour |
|---|---|
| `Read` | DataBridge reads the value from the device and writes it to AAS + InfluxDB |
| `ReadWrite` | Same as Read, plus: changes made in the BaSyx Web UI are written back to the physical device |

---

## Services

| Container | Port | Role |
|---|---|---|
| `aas-env` | 8081 | BaSyx AAS Environment (Digital Twin storage) |
| `aas-registry` | 8082 | AAS Registry |
| `sm-registry` | 8083 | Submodel Registry |
| `aas-discovery` | 8084 | AAS Discovery |
| `aas-ui` | 3000 | BaSyx Web UI with custom plugins |
| `databridge_GUI` | — | Custom Python DataBridge |
| `databridge-official` | — | Official BaSyx DataBridge (Java) |
| `influxdb` | 8086 | Time-series database |
| `grafana` | 3001 | Dashboard visualization |
| `mosquitto` | 1883 | MQTT Broker |
| `container-api-basyx` | 8090 | Docker container control API |
| `simulator` | — | Hardware simulator (development/testing) |

---

## Custom AAS Web UI Plugins

| Plugin | Semantic ID | Function |
|---|---|---|
| `ContainerControlPlugin` | `https://example.com/plugins/container-control` | Start / Stop / Restart / Logs for Docker containers directly in the AAS Web UI |
| `WebIframeViewer` | `https://example.com/plugins/web-iframe-viewer` | Embeds Grafana dashboards or any URL as iframe inside an AAS property |

---

## Eclipse BaSyx Components

BaSyx-AutoTwin is built **on top of** the open-source [Eclipse BaSyx](https://www.eclipse.org/basyx/) platform. The following components are taken directly from the Eclipse BaSyx project and are used unmodified (or with configuration only):

| Component | Docker Image | Repository | License |
|---|---|---|---|
| **AAS Environment** | `eclipsebasyx/aas-environment:2.x` | [basyx-java-server-sdk](https://github.com/eclipse-basyx/basyx-java-server-sdk) | MIT |
| **AAS Registry** | `eclipsebasyx/aas-registry-log-mongodb:2.x` | [basyx-java-server-sdk](https://github.com/eclipse-basyx/basyx-java-server-sdk) | MIT |
| **Submodel Registry** | `eclipsebasyx/submodel-registry-log-mongodb:2.x` | [basyx-java-server-sdk](https://github.com/eclipse-basyx/basyx-java-server-sdk) | MIT |
| **AAS Discovery** | `eclipsebasyx/aas-discovery:2.x` | [basyx-java-server-sdk](https://github.com/eclipse-basyx/basyx-java-server-sdk) | MIT |
| **BaSyx Web UI** | `eclipsebasyx/aas-gui:v2` | [basyx-aas-web-ui](https://github.com/eclipse-basyx/basyx-aas-web-ui) | MIT |
| **DataBridge (Java)** | JAR: `databridge.component-1.0.0-SNAPSHOT.jar` | [basyx-databridge](https://github.com/eclipse-basyx/basyx-databridge) | Apache 2.0 |
| **basyx.aas Python SDK** | `pip install basyx-python-sdk` | [basyx-python-sdk](https://github.com/eclipse-basyx/basyx-python-sdk) | MIT |

### What BaSyx-AutoTwin adds on top

Everything **not** listed above was written specifically for this project:

| Component | Location | Description |
|---|---|---|
| Studio GUI | `GUI/` | Flask web app — AAS builder, DataBridge configurator, Grafana provisioner |
| Custom Python DataBridge | `CustomDatabridge/` | Lightweight protocol bridge (Modbus/MQTT/OPC-UA/Kafka/HTTP) written in Python |
| Grafana auto-provisioner | `GUI/grafana_provisioner.py`, `GUI/grafana_dashboard_builder.py` | Builds and pushes Grafana dashboards via API |
| IDTA submodel generator | `GUI/generate_idta_submodels.py` | Generates AID + AIMC + TimeSeries submodels from official IDTA templates |
| InfluxDB provisioner | `GUI/influxdb_provisioner.py` | Creates buckets and tokens via InfluxDB API |
| ContainerManager AAS | `GUI/create_container_manager_aas.py` | Docker container control as AAS properties |
| Container API | `container-api/` | REST API that proxies Docker Engine commands |
| BaSyx Web UI plugins | `custom-aas-web-ui/` | `ContainerControlPlugin` + `WebIframeViewer` added to the BaSyx Web UI |
| IDTA Validator | `validator/` | Validates generated submodels against official IDTA template files |
| Hardware Simulator | `simulation/` | Simulates Modbus/MQTT/OPC-UA sensor data for testing |
| Start scripts | `start.sh`, `start.bat`, `start.ps1` | Bootstrap: IP detection, port scan, `.env` + `connection.json` generation |

### Maintenance note

When upgrading BaSyx components, refer to the upstream repositories listed above. The `basyx/` configuration folder contains runtime properties for each BaSyx service — changes to the upstream API may require updating these files. The `databridge/Dockerfile` uses a SNAPSHOT JAR; see the comment in that file for the known Modbus polling issue with the milestone release.

---

## Project Structure

```
├── GUI/                      Studio web app (Flask)
│   ├── app.py                AAS builder + REST API
│   ├── grafana_dashboard_builder.py
│   ├── grafana_provisioner.py
│   ├── generate_idta_submodels.py
│   ├── static/               CSS + JavaScript frontend
│   └── templates/            HTML (Jinja2)
├── CustomDatabridge/         Python DataBridge service
├── databridge/               Official BaSyx DataBridge (Java JARs)
├── custom-aas-web-ui/        BaSyx Web UI + custom plugins
├── container-api/            REST API for Docker container control
├── thies-proxy/              Modbus proxy (THIES sensor firmware workaround)
├── simulation/               Hardware simulator for testing
├── validator/                IDTA submodel template validator
├── basyx/                    BaSyx service configuration
├── IDTA-Templates/           Official IDTA submodel templates (.aasx)
├── start.sh                  Linux/macOS bootstrap
├── start.bat / start.ps1     Windows bootstrap
└── docker-compose.yml
```

---

## Acknowledgement

This research was developed at the  
**Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes**.

This research was funded by the Ministry of Finance and Science of Saarland as part of the **"EnFoSaar"** project, financed through the Transformation Programme for Research and Knowledge Transfer Saar.
