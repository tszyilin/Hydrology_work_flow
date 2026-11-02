"""Client for the RFFE 2021 web app (https://rffe-2021.wmawater.com.au/).

The site is a Plotly Dash app, so it exposes a JSON callback API rather than a
documented REST API. This drives those callbacks the same way the browser does.

Deliberately free of any QGIS or Qt import so it can be tested standalone.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "https://rffe-2021.wmawater.com.au"

# Cloudflare answers Python's default user-agent with a 403, so present as a browser.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HEADERS = {"Content-Type": "application/json", "Accept": "application/json",
           "User-Agent": UA, "Referer": BASE + "/", "Origin": BASE}

#: The six AEPs the model returns, in the order it returns them.
AEPS = ["50%", "20%", "10%", "5%", "2%", "1%"]


class RffeError(RuntimeError):
    """Raised when the RFFE service rejects a request or cannot be reached."""


def _post(payload: dict, label: str, retries: int = 3) -> dict:
    """POST one Dash callback, retrying transient failures."""
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(BASE + "/_dash-update-component",
                                     data=body, headers=HEADERS)
        try:
            f = urllib.request.urlopen(req, timeout=300)
            if f.status == 204:                      # Dash "no update"
                raise RffeError(f"{label}: server returned no update")
            return json.loads(f.read().decode())["response"]
        except urllib.error.HTTPError as e:
            # A 500 here usually means the site rejected the inputs, e.g. an
            # outlet that is not on a mapped stream.
            if attempt == retries - 1:
                if e.code == 500:
                    raise RffeError(
                        f"{label}: the RFFE service rejected this site (HTTP 500). "
                        "Check the outlet sits on a mapped watercourse and within "
                        "Australia.") from None
                raise RffeError(f"{label}: HTTP {e.code}") from None
            time.sleep(2 * (attempt + 1))
        except urllib.error.URLError as e:
            if attempt == retries - 1:
                raise RffeError(f"{label}: cannot reach RFFE ({e.reason})") from None
            time.sleep(2 * (attempt + 1))
    raise RffeError(f"{label}: exhausted retries")     # pragma: no cover


def _iv(cid: str, prop: str, value) -> dict:
    return {"id": cid, "property": prop, "value": value}


def _sync_catchment(lon: float, lat: float, clon: float, clat: float, area: float):
    """Have the app build the catchment polygon for this location.

    The 'Run RFFE' callback takes catchPolygon.positions as State -- whatever the
    map is currently showing. Sending the page's default polygon (a Sydney
    catchment) makes the server 500 for every other site, so drive the map-sync
    callback first and pass its polygon through.
    """
    r = _post({
        "output": ("..outletLonValue.value...outletLatValue.value...centroidLonValue.value..."
                   "centroidLatValue.value...markerOutlet.position...markerCentroid.position..."
                   "catchLayer.children.."),
        "outputs": [{"id": x, "property": y} for x, y in
                    [("outletLonValue", "value"), ("outletLatValue", "value"),
                     ("centroidLonValue", "value"), ("centroidLatValue", "value"),
                     ("markerOutlet", "position"), ("markerCentroid", "position"),
                     ("catchLayer", "children")]],
        "inputs": [_iv("outletLonValue", "value", lon), _iv("outletLatValue", "value", lat),
                   _iv("centroidLonValue", "value", clon), _iv("centroidLatValue", "value", clat),
                   _iv("areaValue", "value", area),
                   _iv("markerOutlet", "position", [lat, lon]),
                   _iv("markerCentroid", "position", [clat, clon])],
        "changedPropIds": ["outletLonValue.value"]}, "catchment sync")
    return r["catchLayer"]["children"]["props"]["positions"]


def query_site(lon: float, lat: float, area: float,
               clon: float | None = None, clat: float | None = None):
    """Run one site through RFFE.

    :returns: ``(site, models, region, polygon)`` -- the site properties and
        predictors, the fitted models, the gauged stations behind them, and the
        catchment polygon as ``[[lat, lon], ...]``.
    """
    # Centroid defaults slightly upstream of the outlet; only shape-sensitive.
    clon = lon if clon is None else clon
    clat = lat - 0.07 if clat is None else clat

    positions = _sync_catchment(lon, lat, clon, clat, area)

    # 1. Delineate the catchment and collect the model predictors.
    r1 = _post({
        "output": "..tablePropsDiv.children...runRFFE.children...siteData.data..",
        "outputs": [{"id": "tablePropsDiv", "property": "children"},
                    {"id": "runRFFE", "property": "children"},
                    {"id": "siteData", "property": "data"}],
        "inputs": [_iv("basicButton", "n_clicks", 1), _iv("polygonButton", "n_clicks", 0)],
        "state": [_iv("outletLonValue", "value", lon), _iv("outletLatValue", "value", lat),
                  _iv("catchPolygon", "positions", positions),
                  _iv("outletLonValue2", "value", lon), _iv("outletLatValue2", "value", lat),
                  _iv("catchPolygon2", "positions", [[0.0, 0.0], [0.1, 0.1], [0.2, 0.0]])],
        "changedPropIds": ["basicButton.n_clicks"]}, "delineation")
    site, trigger = r1["siteData"]["data"], r1["runRFFE"]["children"]

    # 2. Fit the regional models.
    r2 = _post({
        "output": ("..Results1.children...regionData.data...modelsData.data..."
                   "plotMaps.children...warning.children...warning.hidden.."),
        "outputs": [{"id": x, "property": y} for x, y in
                    [("Results1", "children"), ("regionData", "data"),
                     ("modelsData", "data"), ("plotMaps", "children"),
                     ("warning", "children"), ("warning", "hidden")]],
        "inputs": [_iv("runRFFE", "children", trigger), _iv("siteData", "data", site)],
        "changedPropIds": ["runRFFE.children"]}, "model fit")

    return site, r2["modelsData"]["data"], r2["regionData"]["data"], positions


def station_table(region: dict):
    """Flatten regionData into ``(header, rows)``.

    regionData arrives as pandas 'split' orient ({index, columns, data}) keyed by
    region number: the gauged catchments the regional models were fitted from.
    """
    header, rows = None, []
    for region_id, tbl in (region or {}).items():
        if not (isinstance(tbl, dict) and "columns" in tbl and "data" in tbl):
            continue
        if header is None:
            header = ["Region_ID", "Station_ID"] + list(tbl["columns"])
        for station_id, row in zip(tbl["index"], tbl["data"]):
            rows.append([region_id, station_id] + list(row))
    return header or [], rows
