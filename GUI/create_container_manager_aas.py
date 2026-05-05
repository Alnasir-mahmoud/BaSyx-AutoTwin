# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

import base64
import json
import os

import requests
import basyx.aas.model as model
import basyx.aas.adapter.json as aas_json
from basyx.aas.adapter.aasx import AASXWriter

import connection as conn

SEMANTIC_CONTAINER  = "https://example.com/plugins/container-control"
SEMANTIC_WEB_IFRAME = "https://example.com/plugins/web-iframe-viewer"

MANAGED_CONTAINERS = [
    "aas-env",
    "aas-registry",
    "sm-registry",
    "aas-discovery",
    "mongo",
    "mosquitto",
    "aas-ui",
    "container-api-basyx",
    "influxdb",
    "thies-proxy",
    "databridge-official",
    "databridge-simulator",
    "databridge-simulator-multitag",
    "databridge_GUI",
    "aas-workflow-gui",
    "ext-kafka",
    "dashboard-api",
    "grafana",
    "testorchestrator",
    "ext-simulator",
]

def _desc(en: str, de: str | None = None) -> model.MultiLanguageTextType:
    d = {"en": en}
    if de:
        d["de"] = de
    return model.MultiLanguageTextType(d)

def _ext_ref(iri: str) -> model.ExternalReference:
    return model.ExternalReference((
        model.Key(type_=model.KeyTypes.GLOBAL_REFERENCE, value=iri),
    ))

def build_aas() -> tuple[model.AssetAdministrationShell, model.Submodel]:
    host_ip       = os.getenv("HOST_IP", conn.load().get("host", "localhost"))
    container_api = os.getenv(
        "CONTAINER_API_EXTERNAL_URL",
        f"http://{host_ip}:{os.getenv('CONTAINER_API_PORT', '8090')}",
    )
    grafana_port  = os.getenv("GRAFANA_PORT", "3001")
    influx_port   = os.getenv("INFLUXDB_PORT", "8086")

    sm = model.Submodel(
        id_="https://hems.example.com/submodels/container_control",
        id_short="ContainerControl",
        description=_desc("Docker Container Control", "Docker Container Steuerung"),
        semantic_id=_ext_ref(SEMANTIC_CONTAINER),
    )

    sm.submodel_element.add(model.Property(
        id_short="ApiEndpoint",
        value_type=model.datatypes.String,
        value=container_api,
        description=_desc("Container-API base URL (port 8090)",
                           "Container-API Basis-URL (Port 8090)"),
    ))

    managed = model.SubmodelElementCollection(
        id_short="ManagedContainers",
        description=_desc("Managed Docker containers",
                           "Verwaltete Docker-Container"),
    )
    for container in MANAGED_CONTAINERS:
        id_short = container.replace("-", "_")
        managed.value.add(model.Property(
            id_short=id_short,
            value_type=model.datatypes.String,
            value=container,
            description=_desc(f"Container: {container}"),
            semantic_id=_ext_ref(SEMANTIC_CONTAINER),
        ))
    sm.submodel_element.add(managed)

    web = model.SubmodelElementCollection(
        id_short="WebInterfaces",
        description=_desc("Embedded web UIs", "Eingebettete Web-Oberflächen"),
    )
    _web_ifaces = [
        ("InfluxDB_UI",  f"http://{host_ip}:{influx_port}",
         "InfluxDB Admin UI"),
        ("Grafana_UI",   f"http://{host_ip}:{grafana_port}",
         "Grafana Dashboards"),
        ("AAS_UI",       conn.get_url("aas_ui", external=True),
         "BaSyx AAS Web UI"),
    ]
    for id_short, url, label in _web_ifaces:
        web.value.add(model.Property(
            id_short=id_short,
            value_type=model.datatypes.String,
            value=url,
            description=_desc(label),
            semantic_id=_ext_ref(SEMANTIC_WEB_IFRAME),
        ))
    sm.submodel_element.add(web)

    aas = model.AssetAdministrationShell(
        id_="https://hems.example.com/ids/aas/container-manager",
        id_short="ContainerManager",
        asset_information=model.AssetInformation(
            asset_kind=model.AssetKind.INSTANCE,
            global_asset_id="container-manager-001",
        ),
    )
    aas.submodel.add(model.ModelReference.from_referable(sm))

    return aas, sm

def deploy(aas: model.AssetAdministrationShell, sm: model.Submodel) -> None:
    server = conn.get_url("aas")

    def _upsert(endpoint: str, obj: model.Identifiable) -> None:
        encoded = base64.urlsafe_b64encode(obj.id.encode()).decode().rstrip("=")
        body    = json.loads(json.dumps(obj, cls=aas_json.AASToJsonEncoder))
        try:
            r = requests.post(f"{server}/{endpoint}", json=body, timeout=10)
            if r.status_code == 409:
                requests.put(f"{server}/{endpoint}/{encoded}", json=body, timeout=10)
                print(f"  ↻ updated  {obj.id_short}")
            elif r.status_code in (200, 201):
                print(f"  ✓ created  {obj.id_short}")
            else:
                print(f"  ✗ {r.status_code}  {obj.id_short}: {r.text[:120]}")
        except Exception as exc:
            print(f"  ✗ error    {obj.id_short}: {exc}")

    print(f"\nDeploying to {server} ...")
    _upsert("submodels", sm)
    _upsert("shells",    aas)

def save_aasx(aas: model.AssetAdministrationShell,
              sm: model.Submodel) -> None:
    out = os.path.join(os.path.dirname(__file__), "ContainerManager.aasx")
    store = model.DictObjectStore([aas, sm])
    with AASXWriter(out) as w:
        w.write_all_aas_objects(
            part_name="/aasx/aasx",
            objects=store,
            file_store=model.DictObjectStore(),
            write_json=False,
        )
    print(f"  ✓ saved    {out}")

if __name__ == "__main__":
    aas, sm = build_aas()
    deploy(aas, sm)
    save_aasx(aas, sm)
    print("\nDone.")
