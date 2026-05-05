# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar


import os, time, math, json, threading, logging, struct, random
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-10s] %(message)s",
    datefmt="%H:%M:%S"
)

_setpoint_lock = threading.Lock()

_setpoints: dict = {
    "battery_charge_power":    3500.0,
    "battery_discharge_limit": 5000.0,
    "heatpump_power":          2000.0,
    "solar_inverter_limit":    5000.0,
    "ev_charge_power":           11.0,
    "ev_charge_current_limit":   32.0,
    "conveyor_speed":            15.0,
    "robot_speed_limit":        500.0,
    "hvac_temp_setpoint":        22.0,
    "hvac_fan_speed_sp":         60.0,
    "ocpp_max_current":          32.0,
    "grid_power_limit":       10000.0,
    "peak_power_threshold":    8000.0,
}

_MODBUS_SETPOINTS  = {"battery_charge_power", "battery_discharge_limit"}
_MQTT_SETPOINTS    = {"heatpump_power", "solar_inverter_limit"}
_HTTP_SETPOINTS    = {"ev_charge_power", "ev_charge_current_limit"}
_OPCUA_SETPOINTS   = {"conveyor_speed", "robot_speed_limit"}
_BACNET_SETPOINTS  = {"hvac_temp_setpoint", "hvac_fan_speed_sp"}
_OCPP_SETPOINTS    = {"ocpp_max_current"}
_DLMS_SETPOINTS    = {"grid_power_limit", "peak_power_threshold"}

def set_setpoint(name: str, value: float):
    with _setpoint_lock:
        if name in _setpoints:
            old = _setpoints[name]
            _setpoints[name] = float(value)
            logging.getLogger("Setpoint").info(
                f"  {name}: {old:.2f} → {value:.2f}"
            )
            return True
    return False

def get_setpoints() -> dict:
    with _setpoint_lock:
        return dict(_setpoints)

class PhysicsModel:

    def __init__(self):
        self.t = 0.0

        self._battery_soc   = 55.0
        self._battery_temp  = 28.0
        self._hp_flow_temp  = 40.0
        self._ev_soc        = 25.0
        self._ev_energy     = 0.0
        self._room_temp     = 20.0
        self._conveyor_run  = True

    def tick(self, dt=1.0):
        self.t += dt
        sp = get_setpoints()

        charge_w = sp["battery_charge_power"]
        if charge_w < 0:
            charge_w = max(charge_w, -sp["battery_discharge_limit"])
        dsoc = (charge_w / 10_000.0) * (dt / 3600.0) * 100.0
        self._battery_soc = max(10.0, min(95.0, self._battery_soc + dsoc))

        target_temp = 28.0 + abs(charge_w) / 1000.0 * 3.0
        self._battery_temp += (target_temp - self._battery_temp) * 0.005 * dt

        hp_w = sp["heatpump_power"]
        target_flow = 30.0 + (hp_w / 8000.0) * 25.0
        self._hp_flow_temp += (target_flow - self._hp_flow_temp) * (dt / 120.0)

        ev_kw = sp["ev_charge_power"]
        if self._ev_soc < 100.0:
            d_ev = (ev_kw / 60.0) * (dt / 3600.0) * 100.0
            self._ev_soc = min(100.0, self._ev_soc + d_ev)
            self._ev_energy += ev_kw * (dt / 3600.0)

        target_room = sp["hvac_temp_setpoint"]
        self._room_temp += (target_room - self._room_temp) * (dt / 300.0)

        self._conveyor_run = sp["conveyor_speed"] > 0.5

    @property
    def battery_soc(self) -> float:
        return round(self._battery_soc, 2)

    @property
    def battery_voltage(self) -> float:
        return 44.0 + (self._battery_soc / 100.0) * 10.0

    @property
    def battery_current(self) -> float:
        sp = get_setpoints()["battery_charge_power"]
        return round(sp / max(self.battery_voltage, 1.0), 3)

    @property
    def battery_temperature(self) -> float:
        return round(self._battery_temp + random.uniform(-0.1, 0.1), 2)

    @property
    def battery_power(self) -> float:
        return get_setpoints()["battery_charge_power"]

    @property
    def solar_power(self) -> float:
        hour = (self.t / 3600.0) % 24
        if 6 <= hour <= 20:
            raw = max(0.0, 5000.0 * math.sin(math.pi * (hour - 6) / 14.0)
                      + random.uniform(-100, 100))
            return min(raw, get_setpoints()["solar_inverter_limit"])
        return 0.0

    @property
    def solar_voltage(self) -> float:
        return 380.0 + random.uniform(-2, 2) if self.solar_power > 0 else 0.0

    @property
    def solar_irradiance(self) -> float:
        return (self.solar_power / 5000.0) * 1000.0

    @property
    def heatpump_power(self) -> float:
        return get_setpoints()["heatpump_power"]

    @property
    def heatpump_flow_temp(self) -> float:
        return round(self._hp_flow_temp + 0.3 * math.sin(self.t / 30.0), 2)

    @property
    def heatpump_return_temp(self) -> float:
        hp_w = get_setpoints()["heatpump_power"]
        spread = 3.0 + (hp_w / 8000.0) * 8.0
        return round(self.heatpump_flow_temp - spread, 2)

    @property
    def heatpump_cop(self) -> float:
        hp_w = get_setpoints()["heatpump_power"]
        cop = 4.5 - (hp_w / 8000.0) * 1.5 - (self._hp_flow_temp - 30.0) / 50.0
        return round(max(1.5, cop) + random.uniform(-0.05, 0.05), 2)

    @property
    def weather_temperature(self) -> float:
        return 18.0 + 10.0 * math.sin(self.t / 3600.0) + random.uniform(-0.5, 0.5)

    @property
    def weather_humidity(self) -> float:
        return 60.0 + 20.0 * math.sin(self.t / 2000.0)

    @property
    def weather_wind_speed(self) -> float:
        return max(0.0, 5.0 + 3.0 * math.sin(self.t / 500.0) + random.uniform(-1, 1))

    @property
    def grid_power(self) -> float:
        sp = get_setpoints()
        base = 800.0
        raw = -self.solar_power + sp["heatpump_power"] + sp["ev_charge_power"] * 1000.0 + base
        return round(min(raw, sp["grid_power_limit"]), 1)

    @property
    def grid_peak_alarm(self) -> float:
        return 1.0 if self.grid_power > get_setpoints()["peak_power_threshold"] else 0.0

    @property
    def grid_voltage(self) -> float:
        load_kw = self.grid_power / 1000.0
        return round(230.0 - load_kw * 0.05 + random.uniform(-0.5, 0.5), 2)

    @property
    def grid_frequency(self) -> float:
        load_kw = max(0.0, self.grid_power / 1000.0)
        return round(50.0 - load_kw * 0.002 + random.uniform(-0.02, 0.02), 3)

    @property
    def robot_joint1_pos(self) -> float:
        sp = get_setpoints()["conveyor_speed"]
        speed_factor = sp / 15.0
        return round(45.0 * math.sin(self.t / max(1.0, 10.0 / speed_factor)), 2)

    @property
    def robot_joint2_pos(self) -> float:
        sp = get_setpoints()["conveyor_speed"]
        speed_factor = sp / 15.0
        return round(30.0 * math.cos(self.t / max(1.0, 12.0 / speed_factor)), 2)

    @property
    def robot_speed(self) -> float:
        sp = get_setpoints()
        raw = abs(sp["conveyor_speed"] * 33.0 * math.sin(self.t / 8.0))
        return round(min(raw, sp["robot_speed_limit"]), 1)

    @property
    def conveyor_speed(self) -> float:
        return get_setpoints()["conveyor_speed"]

    @property
    def ev_soc(self) -> float:
        return round(self._ev_soc, 1)

    @property
    def ev_charging_power(self) -> float:
        sp = get_setpoints()
        power_kw  = sp["ev_charge_power"]
        max_amps  = sp["ev_charge_current_limit"]
        ocpp_amps = sp["ocpp_max_current"]
        limit_amps = min(max_amps, ocpp_amps)
        power_kw   = min(power_kw, limit_amps * 230.0 / 1000.0)
        if self._ev_soc >= 100.0:
            return 0.0
        elif self._ev_soc >= 80.0:
            return round(power_kw * (100.0 - self._ev_soc) / 20.0, 3)
        return round(power_kw, 3)

    @property
    def ev_charging_current(self) -> float:
        return round((self.ev_charging_power * 1000.0) / 230.0, 2)

    @property
    def ev_session_energy(self) -> float:
        return round(self._ev_energy, 3)

    @property
    def hvac_zone_temp(self) -> float:
        return round(self._room_temp + random.uniform(-0.1, 0.1), 2)

    @property
    def hvac_supply_temp(self) -> float:
        sp = get_setpoints()["hvac_temp_setpoint"]
        return round(sp + 3.0 * math.sin(self.t / 120.0), 2)

    @property
    def hvac_return_temp(self) -> float:
        return round(self._room_temp + 1.5 + random.uniform(-0.2, 0.2), 2)

    @property
    def hvac_indoor_humidity(self) -> float:
        return round(45.0 + 10.0 * math.sin(self.t / 900.0), 1)

    @property
    def hvac_fan_speed(self) -> float:
        sp = get_setpoints()
        base_fan = sp["hvac_fan_speed_sp"]
        deviation = abs(sp["hvac_temp_setpoint"] - self._room_temp)
        return round(min(100.0, base_fan + deviation * 5.0), 1)

physics = PhysicsModel()

def physics_loop():
    dt = 0.5
    while True:
        physics.tick(dt)
        time.sleep(dt)

MODBUS_PORT = int(os.getenv("MODBUS_PORT", "5020"))

DATA_POINTS: list[tuple[str, str, "callable"]] = [
    ("BatterySoc",               "%",      lambda: physics.battery_soc),
    ("BatteryVoltage",           "V",      lambda: physics.battery_voltage),
    ("BatteryCurrent",           "A",      lambda: physics.battery_current),
    ("BatteryTemperature",       "degC",   lambda: physics.battery_temperature),
    ("BatteryPower",             "W",      lambda: physics.battery_power),
    ("SolarPower",               "W",      lambda: physics.solar_power),
    ("SolarVoltage",             "V",      lambda: physics.solar_voltage),
    ("SolarCurrent",             "A",      lambda: physics.solar_power / max(physics.solar_voltage, 1.0)),
    ("SolarIrradiance",          "W/m2",   lambda: physics.solar_irradiance),
    ("SolarYieldToday",          "kWh",    lambda: max(0.0, physics.solar_power * ((physics.t % 86400) / 3600.0) / 1000.0)),
    ("HeatpumpPower",            "W",      lambda: physics.heatpump_power),
    ("HeatpumpFlowTemp",         "degC",   lambda: physics.heatpump_flow_temp),
    ("HeatpumpReturnTemp",       "degC",   lambda: physics.heatpump_return_temp),
    ("HeatpumpCOP",              "",       lambda: physics.heatpump_cop),
    ("HeatpumpCompressorSpeed",  "%",      lambda: 60.0 + 30.0 * math.sin(physics.t / 150.0)),
    ("WeatherOutdoorTemp",       "degC",   lambda: physics.weather_temperature),
    ("WeatherHumidity",          "%",      lambda: physics.weather_humidity),
    ("WeatherWindSpeed",         "m/s",    lambda: physics.weather_wind_speed),
    ("WeatherAirPressure",       "hPa",    lambda: 1013.25 + 5.0 * math.sin(physics.t / 4000.0)),
    ("WeatherRainfall",          "mm/h",   lambda: max(0.0, 2.0 * math.sin(physics.t / 600.0))),
    ("GridPower",                "W",      lambda: physics.grid_power),
    ("GridVoltage",              "V",      lambda: physics.grid_voltage),
    ("GridFrequency",            "Hz",     lambda: physics.grid_frequency),
    ("GridReactivePower",        "VAr",    lambda: 150.0 * math.sin(physics.t / 100.0)),
    ("GridCurrent",              "A",      lambda: abs(physics.grid_power) / max(physics.grid_voltage, 1.0)),
    ("EvSoc",                    "%",      lambda: physics.ev_soc),
    ("EvChargingPower",          "kW",     lambda: physics.ev_charging_power),
    ("EvChargingCurrent",        "A",      lambda: physics.ev_charging_current),
    ("EvSessionEnergy",          "kWh",    lambda: physics.ev_session_energy),
    ("EvSessionDuration",        "s",      lambda: float(physics.t % 3600)),
    ("HvacSupplyTemp",           "degC",   lambda: physics.hvac_supply_temp),
    ("HvacReturnTemp",           "degC",   lambda: physics.hvac_return_temp),
    ("HvacIndoorHumidity",       "%",      lambda: physics.hvac_indoor_humidity),
    ("HvacFanSpeed",             "%",      lambda: physics.hvac_fan_speed),
    ("HvacZoneTemp",             "degC",   lambda: physics.hvac_zone_temp),
    ("ProductionOee",            "%",      lambda: 78.0 + 12.0 * math.sin(physics.t / 500.0)),
    ("ProductionCycleCount",     "",       lambda: float(int(physics.t / 30))),
    ("ProductionGoodParts",      "",       lambda: float(int(physics.t / 35))),
    ("ProductionRejectParts",    "",       lambda: float(int(physics.t / 900))),
    ("ProductionUptime",         "s",      lambda: float(physics.t)),
    ("BuildingTotalLoad",        "W",      lambda: 8000.0 + 2000.0 * math.sin(physics.t / 700.0)),
    ("BuildingLightingPower",    "W",      lambda: 1200.0 + 400.0 * math.sin(physics.t / 800.0)),
    ("BuildingHvacPower",        "W",      lambda: 2500.0 + 500.0 * math.sin(physics.t / 600.0)),
    ("BuildingEvChargingPower",  "W",      lambda: physics.ev_charging_power * 1000.0),
    ("BuildingOtherPower",       "W",      lambda: 1800.0 + 300.0 * random.uniform(-1, 1)),
    ("SafetyCo2Level",           "ppm",    lambda: 450.0 + 100.0 * math.sin(physics.t / 1200.0)),
    ("SafetySmokeDetected",      "",       lambda: 0.0),
    ("SafetyDoorsOpen",          "",       lambda: float(int((physics.t / 60) % 3))),
    ("SafetyWindowsOpen",        "",       lambda: float(int((physics.t / 180) % 5))),
    ("SafetyFireAlarm",          "",       lambda: 0.0),
]

HR_SETPOINTS = [
    "battery_charge_power",
    "battery_discharge_limit",
]

def float_to_regs(value: float):
    raw = struct.pack(">f", float(value))
    return struct.unpack(">HH", raw)

def regs_to_float(high: int, low: int) -> float:
    raw = struct.pack(">HH", high, low)
    return struct.unpack(">f", raw)[0]

def update_modbus_context(context):
    slave_id = 0x01

    ir: tuple = ()
    for _id_short, _unit, getter in DATA_POINTS:
        try:
            ir += float_to_regs(getter())
        except Exception:
            ir += float_to_regs(0.0)
    context[slave_id].setValues(4, 0, list(ir))

    sp = get_setpoints()
    hr_init = []
    for name in HR_SETPOINTS:
        hr_init += list(float_to_regs(sp[name]))

    current_hr = context[slave_id].getValues(3, 0, count=len(hr_init))

    if all(v == 0 for v in current_hr):
        context[slave_id].setValues(3, 0, hr_init)
    else:
        for i, name in enumerate(HR_SETPOINTS):
            h = current_hr[i * 2]
            l = current_hr[i * 2 + 1]
            try:
                val = regs_to_float(h, l)
                if math.isfinite(val):
                    set_setpoint(name, val)
            except Exception:
                pass

def run_modbus_server():
    log = logging.getLogger("Modbus")
    try:
        import asyncio
        from pymodbus.server import StartAsyncTcpServer
        from pymodbus.datastore import (
            ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
        )

        ir_size = len(DATA_POINTS) * 2
        hr_size = len(HR_SETPOINTS) * 2
        store = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * 50),
            co=ModbusSequentialDataBlock(0, [0] * 50),
            hr=ModbusSequentialDataBlock(0, [0] * hr_size),
            ir=ModbusSequentialDataBlock(0, [0] * ir_size),
        )
        context = ModbusServerContext(slaves={0x01: store}, single=False)

        def updater():
            while True:
                try:
                    update_modbus_context(context)
                    sp = get_setpoints()
                    log.info(
                        f"SOC={physics.battery_soc:.1f}%  "
                        f"U={physics.battery_voltage:.1f}V  "
                        f"BatP={sp['battery_charge_power']:.0f}W  "
                        f"Conv={sp['conveyor_speed']:.1f}m/min"
                    )
                except Exception as e:
                    log.error(f"Update error: {e}")
                time.sleep(1.0)

        threading.Thread(target=updater, daemon=True, name="modbus-updater").start()

        log.info(f"Modbus TCP Server gestartet auf Port {MODBUS_PORT}")
        log.info("  Input  Register 30001–30100  (50 Datenpunkte, float32)")
        log.info("  Holding Register 40001–40010 (5 Setpoints, float32, schreibbar)")
        for i, name in enumerate(HR_SETPOINTS):
            plcx = i * 2 + 1
            log.info(f"    HR {plcx}: {name}")

        asyncio.run(StartAsyncTcpServer(context=context,
                                        address=("0.0.0.0", MODBUS_PORT)))

    except ImportError:
        log.error("pymodbus nicht installiert — pip install pymodbus")
    except Exception as e:
        log.error(f"Modbus Server Fehler: {e}")

MQTT_BROKER   = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
MQTT_INTERVAL = float(os.getenv("MQTT_INTERVAL", "2.0"))

MQTT_TOPICS = {
    "simulation/solar/power":           lambda: physics.solar_power,
    "simulation/solar/voltage":         lambda: physics.solar_voltage,
    "simulation/solar/irradiance":      lambda: physics.solar_irradiance,
    "simulation/heatpump/power":        lambda: physics.heatpump_power,
    "simulation/heatpump/flow_temp":    lambda: physics.heatpump_flow_temp,
    "simulation/heatpump/return_temp":  lambda: physics.heatpump_return_temp,
    "simulation/heatpump/cop":          lambda: physics.heatpump_cop,
}

MQTT_CONTROL_PREFIX = "simulation/control/"

def run_mqtt_publisher():
    log = logging.getLogger("MQTT")
    try:
        import paho.mqtt.client as mqtt_lib

        client = mqtt_lib.Client(client_id="hardware-simulator-mqtt")

        def on_connect(c, ud, flags, rc, props=None):
            if rc == 0:
                log.info(f"Verbunden mit MQTT Broker {MQTT_BROKER}:{MQTT_PORT}")
                c.subscribe(MQTT_CONTROL_PREFIX + "#", qos=1)
                log.info(f"  Subscribed: {MQTT_CONTROL_PREFIX}#")
            else:
                log.error(f"MQTT Verbindungsfehler rc={rc}")

        def on_message(c, ud, msg):
            topic = msg.topic
            name = topic[len(MQTT_CONTROL_PREFIX):]
            try:
                payload = json.loads(msg.payload.decode())
                value = float(payload.get("value", payload))
                if name not in _MQTT_SETPOINTS:
                    log.warning(f"MQTT Control: '{name}' ist kein MQTT-Setpoint (erlaubt: {_MQTT_SETPOINTS})")
                    return
                if set_setpoint(name, value):
                    log.info(f"MQTT Control: {name} = {value}")
                else:
                    log.warning(f"MQTT Control: unbekannter Setpoint '{name}'")
            except Exception as e:
                log.error(f"MQTT Control parse error: {e}")

        client.on_connect = on_connect
        client.on_message = on_message

        connected = False
        for attempt in range(30):
            try:
                client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                client.loop_start()
                connected = True
                break
            except Exception as e:
                log.warning(f"MQTT Verbindungsversuch {attempt+1}/30: {e}")
                time.sleep(2.0)

        if not connected:
            log.error("MQTT Broker nicht erreichbar — Publisher beendet")
            return

        log.info("MQTT Publisher + Control Subscriber gestartet")

        while True:
            for topic, getter in MQTT_TOPICS.items():
                payload = json.dumps({
                    "value":     round(getter(), 2),
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "unit":      _mqtt_unit(topic)
                })
                client.publish(topic, payload, qos=0, retain=False)

            log.info(
                f"Solar={physics.solar_power:.0f}W  "
                f"HP={physics.heatpump_power:.0f}W  "
                f"COP={physics.heatpump_cop:.2f}"
            )
            time.sleep(MQTT_INTERVAL)

    except ImportError:
        log.error("paho-mqtt nicht installiert — pip install paho-mqtt")
    except Exception as e:
        log.error(f"MQTT Publisher Fehler: {e}")

def _mqtt_unit(topic: str) -> str:
    if "power" in topic:      return "W"
    if "voltage" in topic:    return "V"
    if "temp" in topic:       return "°C"
    if "irradiance" in topic: return "W/m²"
    if "cop" in topic:        return ""
    return ""

HTTP_PORT = int(os.getenv("HTTP_PORT", "8082"))

def run_http_server():
    log = logging.getLogger("HTTP")
    try:
        from flask import Flask, jsonify, request, abort
        app = Flask("hardware-simulator-http")

        import logging as _l
        _l.getLogger("werkzeug").setLevel(_l.ERROR)

        @app.route("/api/weather")
        def weather_all():
            return jsonify({
                "temperature": round(physics.weather_temperature, 2),
                "humidity":    round(physics.weather_humidity, 1),
                "wind_speed":  round(physics.weather_wind_speed, 1),
                "timestamp":   datetime.utcnow().isoformat() + "Z"
            })

        @app.route("/api/weather/temperature")
        def weather_temp():
            return jsonify({"value": round(physics.weather_temperature, 2), "unit": "°C"})

        @app.route("/api/weather/humidity")
        def weather_hum():
            return jsonify({"value": round(physics.weather_humidity, 1), "unit": "%"})

        @app.route("/api/weather/wind_speed")
        def weather_wind():
            return jsonify({"value": round(physics.weather_wind_speed, 1), "unit": "m/s"})

        @app.route("/api/grid")
        def grid_all():
            return jsonify({
                "power":     round(physics.grid_power, 1),
                "voltage":   round(physics.grid_voltage, 2),
                "frequency": round(physics.grid_frequency, 3),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })

        @app.route("/api/grid/power")
        def grid_power():
            return jsonify({"value": round(physics.grid_power, 1), "unit": "W"})

        @app.route("/api/grid/voltage")
        def grid_voltage():
            return jsonify({"value": round(physics.grid_voltage, 2), "unit": "V"})

        @app.route("/api/grid/frequency")
        def grid_freq():
            return jsonify({"value": round(physics.grid_frequency, 3), "unit": "Hz"})

        @app.route("/api/status")
        def status():
            return jsonify({
                "uptime_s":  round(physics.t, 1),
                "protocol":  "http",
                "setpoints": get_setpoints(),
                "simulator": "hardware_simulator.py"
            })

        @app.route("/api/setpoints")
        def all_setpoints():
            return jsonify(get_setpoints())

        @app.route("/api/control/<name>", methods=["GET"])
        def control_get(name):
            sp = get_setpoints()
            if name not in sp:
                abort(404, f"Unknown setpoint: {name}")
            return jsonify({"name": name, "value": sp[name]})

        @app.route("/api/control/<name>", methods=["PUT", "POST"])
        def control_set(name):
            if name not in _HTTP_SETPOINTS:
                abort(403, f"'{name}' ist kein HTTP-Setpoint. Erlaubt: {sorted(_HTTP_SETPOINTS)}")
            data = request.get_json(silent=True) or {}
            if "value" not in data:
                abort(400, "Body must contain {\"value\": <number>}")
            try:
                value = float(data["value"])
            except (TypeError, ValueError):
                abort(400, "value must be a number")
            if not set_setpoint(name, value):
                abort(404, f"Unknown setpoint: {name}")
            log.info(f"HTTP Control: {name} = {value}")
            return jsonify({"name": name, "value": value, "status": "ok"})

        log.info(f"HTTP Server gestartet auf Port {HTTP_PORT}")
        log.info("  GET  /api/weather    → Temperatur, Humidity, Wind")
        log.info("  GET  /api/grid       → Power, Voltage, Frequency")
        log.info("  GET  /api/setpoints  → alle Setpoints")
        log.info("  PUT  /api/control/<name>  → Setpoint schreiben")
        for name in _setpoints:
            log.info(f"    {name}")

        app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True)

    except ImportError:
        log.error("flask nicht installiert — pip install flask")
    except Exception as e:
        log.error(f"HTTP Server Fehler: {e}")

OPCUA_PORT = int(os.getenv("OPCUA_PORT", "4840"))

def run_opcua_server():
    log = logging.getLogger("OPC-UA")
    try:
        import asyncio
        from asyncua import Server, ua

        async def _run():
            server = Server()
            await server.init()
            server.set_endpoint(f"opc.tcp://0.0.0.0:{OPCUA_PORT}/simulation/")
            server.set_server_name("Hardware Simulator OPC-UA")
            server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

            uri = "urn:hardware-simulator"
            idx = await server.register_namespace(uri)

            objects = server.nodes.objects
            plant   = await objects.add_object(idx, "Plant")
            robot   = await plant.add_object(idx, "Robot")
            conv    = await plant.add_object(idx, "Conveyor")
            sp_obj  = await objects.add_object(idx, "Setpoints")

            n_j1  = await robot.add_variable(ua.NodeId(1001, idx), "Joint1_Position",  0.0)
            n_j2  = await robot.add_variable(ua.NodeId(1002, idx), "Joint2_Position",  0.0)
            n_spd = await robot.add_variable(ua.NodeId(1003, idx), "Speed",             0.0)
            n_cv  = await conv.add_variable(ua.NodeId(1004, idx),  "Speed",             0.0)
            n_run = await conv.add_variable(ua.NodeId(1005, idx),  "Running",           True)

            sp_nodes: dict = {}
            sp_defaults = get_setpoints()
            sp_node_ids = {
                "conveyor_speed":   2001,
                "robot_speed_limit":2002,
            }
            for name, node_id in sp_node_ids.items():
                node = await sp_obj.add_variable(
                    ua.NodeId(node_id, idx), name, sp_defaults[name]
                )
                await node.set_writable()
                sp_nodes[name] = node
                log.info(f"  ns=2;i={node_id}  Setpoints.{name}  (schreibbar)")

            async with server:
                log.info(f"OPC-UA Server gestartet auf Port {OPCUA_PORT}")
                log.info(f"  Namespace idx={idx}  URI={uri}")

                while True:
                    await n_j1.write_value(round(physics.robot_joint1_pos, 3))
                    await n_j2.write_value(round(physics.robot_joint2_pos, 3))
                    await n_spd.write_value(round(physics.robot_speed, 2))
                    await n_cv.write_value(round(physics.conveyor_speed, 2))
                    await n_run.write_value(physics.conveyor_speed > 0)

                    for name, node in sp_nodes.items():
                        try:
                            val = await node.read_value()
                            set_setpoint(name, float(val))
                        except Exception:
                            pass

                    log.info(
                        f"J1={physics.robot_joint1_pos:.1f}°  "
                        f"J2={physics.robot_joint2_pos:.1f}°  "
                        f"Conv={physics.conveyor_speed:.1f}m/min  "
                        f"HP={physics.heatpump_power:.0f}W"
                    )
                    await asyncio.sleep(1.0)

        asyncio.run(_run())

    except ImportError:
        log.error("asyncua nicht installiert — pip install asyncua")
    except Exception as e:
        log.error(f"OPC-UA Server Fehler: {e}")

KAFKA_BROKER   = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_INTERVAL = float(os.getenv("KAFKA_INTERVAL", "3.0"))

def run_kafka_producer():
    log = logging.getLogger("Kafka")
    try:
        from kafka import KafkaProducer
        from kafka.errors import NoBrokersAvailable

        producer = None
        for attempt in range(20):
            try:
                producer = KafkaProducer(
                    bootstrap_servers=[KAFKA_BROKER],
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    acks=1,
                    retries=3
                )
                log.info(f"Verbunden mit Kafka Broker {KAFKA_BROKER}")
                break
            except NoBrokersAvailable:
                log.warning(f"Kafka Verbindungsversuch {attempt+1}/20 ...")
                time.sleep(3.0)

        if not producer:
            log.error("Kafka Broker nicht erreichbar — Producer beendet")
            return

        log.info("Kafka Producer gestartet")

        while True:
            ts = datetime.utcnow().isoformat() + "Z"
            producer.send("simulation.ev", {
                "soc":              round(physics.ev_soc, 1),
                "charging_power":   round(physics.ev_charging_power, 2),
                "charging_current": round(physics.ev_charging_current, 2),
                "session_energy":   round(physics.ev_session_energy, 3),
                "timestamp":        ts
            })
            producer.send("simulation.ev.soc",   {"value": round(physics.ev_soc, 1),            "timestamp": ts})
            producer.send("simulation.ev.power",  {"value": round(physics.ev_charging_power, 2), "timestamp": ts})
            producer.flush()
            log.info(
                f"EV SOC={physics.ev_soc:.1f}%  "
                f"Power={physics.ev_charging_power:.1f}kW  "
                f"Session={physics.ev_session_energy:.2f}kWh"
            )
            time.sleep(KAFKA_INTERVAL)

    except ImportError:
        log.error("kafka-python nicht installiert — pip install kafka-python")
    except Exception as e:
        log.error(f"Kafka Producer Fehler: {e}")

BACNET_PORT = int(os.getenv("BACNET_PORT", "47808"))

def run_bacnet_device():
    log = logging.getLogger("BACnet")
    try:
        import asyncio
        from bacpypes3.ipv4.app import NormalApplication
        from bacpypes3.app import DeviceObject
        from bacpypes3.local.analog import AnalogInputObject, AnalogOutputObject

        async def _run():
            from bacpypes3.pdu import IPv4Address
            device = DeviceObject(
                objectIdentifier=("device", 100),
                objectName="SimulatedPlant",
                description="Hardware Simulator BACnet/IP Device",
                maxApduLengthAccepted=1024,
                segmentationSupported="noSegmentation",
            )
            AI = [
                ("HvacZoneTemp",       "degreesCelsius",  lambda: physics.hvac_zone_temp),
                ("HvacSupplyTemp",     "degreesCelsius",  lambda: physics.hvac_supply_temp),
                ("HvacReturnTemp",     "degreesCelsius",  lambda: physics.hvac_return_temp),
                ("HvacIndoorHumidity", "percent",         lambda: physics.hvac_indoor_humidity),
                ("HvacFanSpeed",       "percent",         lambda: physics.hvac_fan_speed),
                ("OutdoorTemperature", "degreesCelsius",  lambda: physics.weather_temperature),
            ]
            AO = [
                ("HvacTempSetpoint",    "degreesCelsius",  "hvac_temp_setpoint"),
                ("HvacFanSpeed_SP",     "percent",          "hvac_fan_speed_sp"),
            ]

            local_addr = IPv4Address(f"0.0.0.0:{BACNET_PORT}")
            app = NormalApplication(device, local_addr)
            try:
                ai_nodes = []
                for inst, (name, units, getter) in enumerate(AI):
                    obj = AnalogInputObject(
                        objectIdentifier=("analogInput", inst),
                        objectName=name,
                        presentValue=round(getter(), 4),
                        units=units,
                    )
                    app.add_object(obj)
                    ai_nodes.append((obj, getter))
                    log.info(f"  analogInput:{inst}  {name}  [{units}]")

                ao_nodes = []
                for inst, (name, units, sp) in enumerate(AO):
                    obj = AnalogOutputObject(
                        objectIdentifier=("analogOutput", inst),
                        objectName=name,
                        presentValue=get_setpoints()[sp],
                        units=units,
                    )
                    app.add_object(obj)
                    ao_nodes.append((obj, sp))
                    log.info(f"  analogOutput:{inst} {name}  [writable → {sp}]")

                log.info(f"BACnet/IP device on port {BACNET_PORT}  device-instance=100")
                await asyncio.sleep(0.5)

                while True:
                    for obj, getter in ai_nodes:
                        try:    obj.presentValue = round(getter(), 4)
                        except Exception: pass
                    for obj, sp_name in ao_nodes:
                        try:    set_setpoint(sp_name, float(obj.presentValue))
                        except Exception: pass
                    await asyncio.sleep(1.0)
            finally:
                app.close()

        asyncio.run(_run())
    except ImportError:
        log.error("bacpypes3 not installed — pip install bacpypes3")
    except Exception as e:
        log.error(f"BACnet Device error: {e}", exc_info=True)

OCPP_CS_URL = os.getenv("OCPP_CS_URL", "ws://databridge_GUI:9000")
OCPP_CP_ID  = os.getenv("OCPP_CP_ID",  "CP001")

def run_ocpp_chargepoint():
    log = logging.getLogger("OCPP")
    try:
        import asyncio
        import websockets
        from ocpp.v16 import ChargePoint, call, call_result
        from ocpp.routing import on
        from ocpp.v16.enums import (Action, RegistrationStatus, AuthorizationStatus,
                                     ConfigurationStatus, ChargingProfileStatus,
                                     RemoteStartStopStatus)
        from datetime import datetime as _dt

        _KEY_MAP = {
            "MaxChargingCurrent": "ocpp_max_current",
        }

        class SimCP(ChargePoint):
            @on(Action.ChangeConfiguration)
            def on_change_config(self, key, value, **kwargs):
                if key in _KEY_MAP:
                    try:    set_setpoint(_KEY_MAP[key], float(value))
                    except Exception: pass
                    log.info(f"ChangeConfiguration: {key} = {value}")
                return call_result.ChangeConfigurationPayload(status=ConfigurationStatus.accepted)

            @on(Action.SetChargingProfile)
            def on_set_profile(self, connector_id, cs_charging_profiles, **kwargs):
                try:
                    periods = cs_charging_profiles.get("chargingSchedule", {}).get("chargingSchedulePeriod", [])
                    if periods:
                        limit = float(periods[0].get("limit", 11.0))
                        set_setpoint("ev_charge_power", limit)
                        log.info(f"SetChargingProfile: ev_charge_power = {limit}")
                except Exception: pass
                return call_result.SetChargingProfilePayload(status=ChargingProfileStatus.accepted)

            @on(Action.GetConfiguration)
            def on_get_config(self, **kwargs):
                sp = get_setpoints()
                return call_result.GetConfigurationPayload(configuration_key=[
                    {"key": gui_key, "readonly": False, "value": str(sp.get(sp_key, ""))}
                    for gui_key, sp_key in _KEY_MAP.items()
                ])

            @on(Action.RemoteStartTransaction)
            def on_remote_start(self, **kwargs):
                return call_result.RemoteStartTransactionPayload(status=RemoteStartStopStatus.accepted)

            @on(Action.RemoteStopTransaction)
            def on_remote_stop(self, **kwargs):
                return call_result.RemoteStopTransactionPayload(status=RemoteStartStopStatus.accepted)

        async def _run():
            while True:
                try:
                    ws_url = f"{OCPP_CS_URL}/{OCPP_CP_ID}"
                    log.info(f"Connecting to OCPP CS: {ws_url}")
                    async with websockets.connect(ws_url, subprotocols=["ocpp1.6"]) as ws:
                        cp = SimCP(OCPP_CP_ID, ws)
                        await cp.call(call.BootNotificationPayload(
                            charge_point_vendor="SimVendor",
                            charge_point_model="HardwareSimulator",
                        ))
                        log.info(f"OCPP CP '{OCPP_CP_ID}' registered with CS")

                        async def _meter_loop():
                            while True:
                                await asyncio.sleep(10)
                                ts = _dt.utcnow().isoformat() + "Z"
                                await cp.call(call.MeterValuesPayload(
                                    connector_id=1,
                                    meter_value=[{"timestamp": ts, "sampledValue": [
                                        {"value": str(round(physics.ev_soc, 1)),              "measurand": "SoC",                            "unit": "Percent"},
                                        {"value": str(round(physics.ev_charging_power, 3)),   "measurand": "Power.Active.Import",            "unit": "kW"},
                                        {"value": str(round(physics.ev_charging_current, 2)), "measurand": "Current.Import",                 "unit": "A"},
                                        {"value": str(round(physics.ev_session_energy, 3)),   "measurand": "Energy.Active.Import.Register",  "unit": "kWh"},
                                        {"value": str(round(physics.battery_soc, 1)),         "measurand": "SoC",          "context": "Sample.Periodic", "unit": "Percent"},
                                        {"value": str(round(physics.battery_power, 1)),       "measurand": "Power.Active.Import", "phase": "L1", "unit": "W"},
                                    ]}],
                                ))
                        await asyncio.gather(cp.start(), _meter_loop())
                except Exception as exc:
                    log.warning(f"OCPP CP disconnected: {exc} — reconnecting in 5 s")
                    await asyncio.sleep(5)

        asyncio.run(_run())
    except ImportError:
        log.error("ocpp / websockets not installed — pip install ocpp websockets")
    except Exception as e:
        log.error(f"OCPP Charge Point error: {e}", exc_info=True)

DLMS_PORT = int(os.getenv("DLMS_PORT", "4059"))

_DLMS_OBIS_MAP = {
    "1.0.1.8.0.255":  lambda: physics.ev_session_energy,
    "1.0.2.8.0.255":  lambda: max(0.0, physics.solar_power * ((physics.t % 86400) / 3600.0) / 1000.0),
    "1.0.1.7.0.255":  lambda: physics.grid_power,
    "1.0.32.7.0.255": lambda: physics.grid_voltage,
    "1.0.52.7.0.255": lambda: physics.grid_voltage,
    "1.0.72.7.0.255": lambda: physics.grid_voltage,
    "1.0.31.7.0.255": lambda: abs(physics.grid_power) / max(physics.grid_voltage, 1.0),
    "1.0.14.7.0.255": lambda: physics.grid_frequency,
    "1.1.0.8.0.255":  lambda: physics.battery_soc,
    "0.0.96.1.0.255": lambda: 12345678.0,
}
_DLMS_SETPOINT_MAP = {
    "0.1.24.3.0.255": "grid_power_limit",
    "0.1.24.4.0.255": "peak_power_threshold",
}

def run_dlms_server():
    log = logging.getLogger("DLMS")
    try:
        import asyncio, struct

        def _wrap(data: bytes) -> bytes:
            return bytes([0x00, 0x01, 0x00, 0x01, 0x00, 0x03,
                          (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data

        def _obis_from_bytes(b: bytes) -> str:
            return ".".join(str(x) for x in b[:6])

        async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            peer = writer.get_extra_info("peername")
            log.info(f"DLMS client {peer} connected")
            try:
                while True:
                    hdr = await reader.readexactly(8)
                    length = (hdr[6] << 8) | hdr[7]
                    pdu = await reader.readexactly(length)

                    if pdu[0] == 0x60:
                        aare = bytes([0x61,0x1D,0xA1,0x09,0x06,0x07,
                                      0x60,0x85,0x74,0x05,0x08,0x01,0x01,
                                      0xA2,0x03,0x02,0x01,0x00,
                                      0xA3,0x05,0xA1,0x03,0x02,0x01,0x00,
                                      0xBE,0x09,0x04,0x07,0x08,0x80,0x00,
                                      0x06,0x1F,0xA0,0x00,0x00])
                        writer.write(_wrap(aare))

                    elif pdu[0] == 0xC0 and len(pdu) >= 13:
                        obis = _obis_from_bytes(pdu[7:13])
                        getter = _DLMS_OBIS_MAP.get(obis)
                        val = getter() if getter else 0.0
                        resp = bytes([0xC4,0x01,0x00,0x00,0x00,0x01,0x0D]) + struct.pack(">d", float(val))
                        writer.write(_wrap(resp))
                        log.debug(f"DLMS GET {obis} → {val:.4f}")

                    elif pdu[0] == 0xC1 and len(pdu) >= 21:
                        obis = _obis_from_bytes(pdu[7:13])
                        try:
                            val = struct.unpack(">d", pdu[-8:])[0]
                            sp = _DLMS_SETPOINT_MAP.get(obis)
                            if sp:
                                set_setpoint(sp, val)
                                log.info(f"DLMS SET {obis} → {sp} = {val:.3f}")
                        except Exception:
                            pass
                        writer.write(_wrap(bytes([0xC5,0x01,0x00,0x00,0x00,0x01,0x00])))

                    elif pdu[0] == 0x62:
                        writer.write(_wrap(bytes([0x63,0x03,0x80,0x01,0x00])))
                        break

                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionResetError):
                pass
            except Exception as exc:
                log.debug(f"DLMS client error {peer}: {exc}")
            finally:
                writer.close()
                log.info(f"DLMS client {peer} disconnected")

        async def _run():
            srv = await asyncio.start_server(_handle, "0.0.0.0", DLMS_PORT)
            log.info(f"DLMS/COSEM TCP server on port {DLMS_PORT}")
            for obis in _DLMS_OBIS_MAP:
                log.info(f"  {obis}")
            async with srv:
                await srv.serve_forever()

        asyncio.run(_run())
    except Exception as e:
        log.error(f"DLMS Server error: {e}", exc_info=True)

def print_config_summary():
    print("\n" + "="*70)
    print("  HARDWARE SIMULATOR — Alle Protokolle (Lesen + Steuern)")
    print("="*70)
    print(f"  Modbus TCP  → Port {MODBUS_PORT}")
    print(f"    Input  Register 30001-30100  (50 Datenpunkte, float32, READ)")
    print(f"    Holding Register 40001-40010 (5 Setpoints,    float32, READ+WRITE)")
    print()
    print(f"  MQTT        → Broker {MQTT_BROKER}:{MQTT_PORT}")
    print(f"    Publish: simulation/solar/*  simulation/heatpump/*")
    print(f"    Control: simulation/control/<name>  {{\"value\": 123.4}}")
    print()
    print(f"  HTTP/REST   → http://0.0.0.0:{HTTP_PORT}")
    print(f"    GET  /api/weather/*  /api/grid/*  /api/setpoints")
    print(f"    PUT  /api/control/<name>  {{\"value\": 123.4}}")
    print()
    print(f"  OPC-UA      → opc.tcp://0.0.0.0:{OPCUA_PORT}")
    print(f"    READ:  ns=2;i=1001-1005    WRITE: ns=2;i=2001-2005")
    print()
    print(f"  Kafka       → Broker {KAFKA_BROKER}")
    print(f"    simulation.ev  simulation.ev.soc  simulation.ev.power")
    print()
    print(f"  BACnet/IP   → UDP Port {BACNET_PORT}  (device-instance=100)")
    print(f"    READ:  analogInput:0-5   WRITE: analogOutput:0-2")
    print()
    print(f"  OCPP 1.6    → CP '{OCPP_CP_ID}' → CS {OCPP_CS_URL}")
    print(f"    MeterValues every 10 s  |  ChangeConfiguration / SetChargingProfile")
    print()
    print(f"  DLMS/COSEM  → TCP Port {DLMS_PORT}")
    print(f"    GET: 1.0.1.7/1.8/14/32.7.0.255 …   SET: 0.1.24.3-5.0.255")
    print("="*70 + "\n")

if __name__ == "__main__":
    print_config_summary()

    threading.Thread(target=physics_loop, daemon=True, name="physics").start()

    threads = [
        threading.Thread(target=run_modbus_server,    daemon=True, name="modbus"),
        threading.Thread(target=run_mqtt_publisher,   daemon=True, name="mqtt"),
        threading.Thread(target=run_opcua_server,     daemon=True, name="opcua"),
        threading.Thread(target=run_kafka_producer,   daemon=True, name="kafka"),
        threading.Thread(target=run_bacnet_device,    daemon=True, name="bacnet"),
        threading.Thread(target=run_ocpp_chargepoint, daemon=True, name="ocpp"),
        threading.Thread(target=run_dlms_server,      daemon=True, name="dlms"),
    ]

    for t in threads:
        t.start()
        time.sleep(0.3)

    try:
        run_http_server()
    except KeyboardInterrupt:
        print("\nSimulator beendet.")
