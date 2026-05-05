# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class PropertySpec:
    name: str
    bucket: str
    measurement: str
    unit: str = ""
    description: str = ""
    viz_type: str = "timeseries"

_PANEL_W = 12
_PANEL_H = 8

def _flux_query(spec: PropertySpec) -> str:
    return (
        f'from(bucket: "{spec.bucket}")\n'
        f'  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
        f'  |> filter(fn: (r) => r._measurement == "{spec.name}")\n'
        f'  |> filter(fn: (r) => r._field == "value")\n'
        f'  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)'
    )

def _panel_base(spec: PropertySpec, idx: int, datasource_uid: str) -> dict:
    col = (idx % 2) * _PANEL_W
    row = (idx // 2) * _PANEL_H
    title = (spec.description or spec.name) + (f" ({spec.unit})" if spec.unit else "")
    return {
        "id":         idx + 1,
        "title":      title,
        "datasource": {"type": "influxdb", "uid": datasource_uid},
        "gridPos":    {"x": col, "y": row, "w": _PANEL_W, "h": _PANEL_H},
        "targets": [{
            "refId":      "A",
            "datasource": {"type": "influxdb", "uid": datasource_uid},
            "query":      _flux_query(spec),
            "queryType":  "flux",
        }],
    }

def _timeseries_panel(spec: PropertySpec, idx: int, datasource_uid: str) -> dict:
    p = _panel_base(spec, idx, datasource_uid)
    p["type"] = "timeseries"
    p["fieldConfig"] = {
        "defaults": {
            "unit":   spec.unit or "none",
            "custom": {"drawStyle": "line", "lineWidth": 1, "showPoints": "never"},
        },
        "overrides": [],
    }
    p["options"] = {
        "legend":  {"showLegend": True, "displayMode": "list", "placement": "bottom"},
        "tooltip": {"mode": "single", "sort": "none"},
    }
    return p

def _gauge_panel(spec: PropertySpec, idx: int, datasource_uid: str) -> dict:
    p = _panel_base(spec, idx, datasource_uid)
    p["type"] = "gauge"
    p["fieldConfig"] = {
        "defaults": {
            "unit": spec.unit or "none",
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "green",  "value": None},
                    {"color": "yellow", "value": 80},
                    {"color": "red",    "value": 100},
                ],
            },
        },
        "overrides": [],
    }
    p["options"] = {
        "reduceOptions":       {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "orientation":         "auto",
        "showThresholdLabels": False,
        "showThresholdMarkers": True,
    }
    return p

def _stat_panel(spec: PropertySpec, idx: int, datasource_uid: str) -> dict:
    p = _panel_base(spec, idx, datasource_uid)
    p["type"] = "stat"
    p["fieldConfig"] = {
        "defaults": {
            "unit": spec.unit or "none",
            "thresholds": {
                "mode": "absolute",
                "steps": [{"color": "blue", "value": None}],
            },
        },
        "overrides": [],
    }
    p["options"] = {
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "orientation":   "auto",
        "colorMode":     "value",
        "graphMode":     "none",
        "justifyMode":   "auto",
    }
    return p

def _bargauge_panel(spec: PropertySpec, idx: int, datasource_uid: str) -> dict:
    p = _panel_base(spec, idx, datasource_uid)
    p["type"] = "bargauge"
    p["fieldConfig"] = {
        "defaults": {
            "unit": spec.unit or "none",
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "green",  "value": None},
                    {"color": "yellow", "value": 70},
                    {"color": "red",    "value": 90},
                ],
            },
        },
        "overrides": [],
    }
    p["options"] = {
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "orientation":   "horizontal",
        "displayMode":   "gradient",
        "valueMode":     "color",
        "showUnfilled":  True,
    }
    return p

_PANEL_BUILDERS = {
    "timeseries": _timeseries_panel,
    "gauge":      _gauge_panel,
    "stat":       _stat_panel,
    "bargauge":   _bargauge_panel,
}

def _build_panel(spec: PropertySpec, idx: int, datasource_uid: str) -> dict:
    builder = _PANEL_BUILDERS.get(spec.viz_type, _timeseries_panel)
    return builder(spec, idx, datasource_uid)

def _make_dashboard_payload(uid: str, title: str, panels: list[dict],
                             refresh: str = "5s") -> dict:
    return {
        "dashboard": {
            "uid":   uid,
            "title": title,
            "tags":  ["aas", "basyx", "auto-generated"],
            "timezone": "browser",
            "schemaVersion": 38,
            "version": 0,
            "refresh": refresh,
            "time":    {"from": "now-1h", "to": "now"},
            "panels":  panels,
        },
        "overwrite":   True,
        "folderUid":   "",
    }

def build_dashboard(
    asset_name: str,
    properties: list[PropertySpec],
    *,
    datasource_uid: str,
    refresh: str = "5s",
) -> dict:
    panels = [_build_panel(p, i, datasource_uid) for i, p in enumerate(properties)]
    return _make_dashboard_payload(
        uid=f"aas-{asset_name.lower()}",
        title=f"AAS · {asset_name}",
        panels=panels,
        refresh=refresh,
    )

def build_protocol_dashboard(
    asset_name: str,
    protocol: str,
    properties: list[PropertySpec],
    *,
    datasource_uid: str,
    refresh: str = "5s",
) -> dict:
    panels = [_build_panel(p, i, datasource_uid) for i, p in enumerate(properties)]
    uid = f"aas-{asset_name.lower()}-{protocol}"
    return _make_dashboard_payload(
        uid=uid,
        title=f"AAS · {asset_name} · {protocol.upper()}",
        panels=panels,
        refresh=refresh,
    )
