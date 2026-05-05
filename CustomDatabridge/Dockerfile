FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pymodbus paho-mqtt requests influxdb-client asyncua kafka-python \
    bacpypes3 ocpp websockets gurux-dlms gurux-net

# Code is bind-mounted from the host; only entrypoint matters here.
CMD ["sh", "-c", "python -u generate_databridge_config_GUI.py && python -u databridge_service_GUI.py"]
