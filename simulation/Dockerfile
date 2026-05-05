FROM python:3.11-slim

WORKDIR /app

COPY requirements*.txt ./

# Split into 3 groups — jeder Layer hat eigenen Cache-Eintrag.
# Wenn Docker bei Layer 2 abstürzt, fängt der nächste Versuch dort an.
RUN pip install --no-cache-dir --prefer-binary -r requirements-base.txt
RUN pip install --no-cache-dir --prefer-binary -r requirements-opcua.txt
RUN pip install --no-cache-dir --prefer-binary -r requirements-protocols.txt

COPY hardware_simulator.py .

# Ports: Modbus=5020, HTTP=8082, OPC-UA=4840, BACnet=47808/UDP, DLMS=4059
EXPOSE 5020 8082 4840 4059
EXPOSE 47808/udp

ENV MODBUS_PORT=5020
ENV HTTP_PORT=8082
ENV OPCUA_PORT=4840
ENV MQTT_BROKER=mosquitto
ENV MQTT_PORT=1883
ENV KAFKA_BROKER=kafka:9092
ENV BACNET_PORT=47808
ENV DLMS_PORT=4059
ENV OCPP_CS_URL=ws://databridge_GUI:9000
ENV OCPP_CP_ID=CP001

CMD ["python", "-u", "hardware_simulator.py"]
