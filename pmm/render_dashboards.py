#!/usr/bin/env python3
"""Write every Grafana dashboard under pmm/dashboards/ that is generated.

    python3 pmm/render_dashboards.py        (or: make dashboards)

Generated: the talk's two dashboards, osmc-basic and osmc-side-by-side, written by
health_dashboards.py (this file holds the shared panel helpers).

mongot-overview.json is hand-written and not touched here.
"""
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "dashboards"
DS = "Metrics"

# ----------------------------------------------------------------------------
# Panel helpers
# ----------------------------------------------------------------------------


def row(pid, title, y, collapsed=False, children=None):
    return {
        "collapsed": collapsed,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "id": pid,
        "panels": children or [],
        "title": title,
        "type": "row",
    }


def stat(pid, title, expr, x, y, w=6, h=5, unit="short", mappings=None, thresholds=None,
         description="", decimals=None, vmax=None, name_inside=False):
    """unit=None leaves the unit out (used for 0..1 ratios such as recall).

    name_inside=True drops the small panel header and prints the name big, under the value."""
    defaults = {
        "color": {"mode": "thresholds"},
        "mappings": mappings or [],
        "thresholds": thresholds or {"mode": "absolute", "steps": [{"color": "green"}]},
    }
    if unit is not None:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if vmax is not None:
        defaults["max"] = vmax
        defaults["min"] = 0
    options = {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "center",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "textMode": "value",
    }
    if name_inside:
        options["textMode"] = "value_and_name"
        options["text"] = {"titleSize": 20, "valueSize": 36}
    return {
        "datasource": DS,
        "description": description,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": pid,
        "options": options,
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": title, "refId": "A"}],
        "title": "" if name_inside else title,
        "type": "stat",
    }


def timeseries(pid, title, targets, x, y, w, h, unit, description="", vmax=None, thresholds=None,
               decimals=None, calcs=("lastNotNull", "max"), legend=None, color_by_thresholds=False):
    """legend: replaces the default legend (list at the bottom).
    color_by_thresholds: the line takes the colour of the threshold it is in."""
    defaults = {
        "color": {"mode": "thresholds" if color_by_thresholds else "palette-classic"},
        "custom": {"fillOpacity": 12, "lineWidth": 2, "showPoints": "never"},
        "min": 0,
        "unit": unit,
    }
    if vmax is not None:
        defaults["max"] = vmax
    if color_by_thresholds:
        # without this the whole line takes the colour of the last value
        defaults["custom"]["gradientMode"] = "scheme"
        defaults["custom"]["fillOpacity"] = 0  # the fill would paint the bands red under a green line
        defaults["custom"]["lineWidth"] = 3
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = thresholds
        defaults["custom"]["thresholdsStyle"] = {"mode": "line"}
    return {
        "datasource": DS,
        "description": description,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": pid,
        "options": {
            "legend": legend or {"calcs": list(calcs), "displayMode": "list",
                                 "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "targets": [
            {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}
            for ref, (expr, legend) in zip("ABCDEFGH", targets)
        ],
        "title": title,
        "type": "timeseries",
    }


def ts_min(*args, **kwargs):
    """Timeseries whose legend shows the minimum: the OpenSearch panels care about dips."""
    return timeseries(*args, calcs=("lastNotNull", "min"), **kwargs)


def value_map(**texts):
    return [{"type": "value", "options": {
        key: {"color": color, "text": text} for key, (color, text) in texts.items()
    }}]


def write(filename, uid, title, panels, tags, links=None, refresh="5s", time_from="now-15m"):
    dash = {
        "annotations": {"list": []},
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "links": links or [],
        "panels": panels,
        "refresh": refresh,
        "schemaVersion": 38,
        "style": "dark",
        "tags": tags,
        "templating": {"list": []},
        "time": {"from": time_from, "to": "now"},
        "timepicker": {},
        "timezone": "",
        "title": title,
        "uid": uid,
        "version": 1,
    }
    path = OUT_DIR / filename
    path.write_text(json.dumps(dash, indent=2) + "\n")
    print(path)


# ----------------------------------------------------------------------------
# Shared value maps and thresholds
# ----------------------------------------------------------------------------

up_map = value_map(**{"0": ("red", "DOWN"), "1": ("green", "UP")})
ready_map = value_map(**{"0": ("red", "NOT READY"), "1": ("green", "READY")})
not_green_map = value_map(**{"0": ("red", "NOT GREEN"), "1": ("green", "GREEN")})

green_red = {"mode": "absolute", "steps": [{"color": "red"}, {"color": "green", "value": 1}]}
recall_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "red"}, {"color": "yellow", "value": 0.8}, {"color": "green", "value": 0.9}],
}
queue_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "green"}, {"color": "yellow", "value": 2}, {"color": "red", "value": 8}],
}
lag_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "green"}, {"color": "yellow", "value": 5000}, {"color": "red", "value": 30000}],
}
latency_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "green"}, {"color": "yellow", "value": 0.05}, {"color": "red", "value": 0.25}],
}
hits_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "red"}, {"color": "yellow", "value": 8}, {"color": "green", "value": 9.5}],
}
cosine_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "red"}, {"color": "yellow", "value": 0.95}, {"color": "green", "value": 0.99}],
}
match_map = value_map(**{"0": ("red", "DIFFERENT MODEL"), "1": ("green", "SAME MODEL")})
ratio_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "green"}, {"color": "yellow", "value": 0.001}, {"color": "orange", "value": 0.005}],
}

MONGOT_LATENCY = [
    ('max(mongot_command_vectorSearchCommandTotalLatency_seconds{quantile="0.99"})', "p99"),
    ('max(mongot_command_vectorSearchCommandTotalLatency_seconds{quantile="0.5"})', "p50"),
]


if __name__ == "__main__":
    import health_dashboards

    health_dashboards.write_all()
