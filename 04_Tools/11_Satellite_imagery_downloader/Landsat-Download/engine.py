# -*- coding: utf-8 -*-
"""
ENGINE of the "Landsat Download" plugin — all the real work, no GUI:
searching the Landsat archive, bulk downloading bands and building
ready-symbolised products.

DATA SOURCE: USGS Landsat Collection 2 Level-2 (surface reflectance
and surface temperature) served openly through the Microsoft
Planetary Computer STAC API. Landsat 4, 5, 7, 8 and 9, global
coverage since 1982, 30 m resolution — and NO account or sign-in
is needed at all.

No qgis imports here on purpose — this module can be tested outside
QGIS. Instead of rasterio we use GDAL and numpy, which ship with
every QGIS installation, so the user installs nothing.

© Grzegorz Górniak
"""

import os
import csv
import time

import requests                      # bundled with QGIS
from osgeo import gdal               # the heart of QGIS, always there
import numpy as np                   # always there as well

gdal.UseExceptions()

# Planetary Computer endpoints — leave as they are
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
COLLECTION = "landsat-c2-l2"

RETRIES = 3          # how many times to retry a band before giving up
GB_PER_BAND = 0.07   # rough size of one 30 m band file (for estimates)

# =============================================================================
#  LANDSAT BAND CHEAT SHEET (Collection 2 Level-2 asset names):
#    blue, green, red  = visible light            (30 m)
#    nir08             = near-infrared            (30 m)
#    swir16, swir22    = shortwave infrared 1 & 2 (30 m)
#    lwir11 / lwir     = thermal infrared -> surface temperature
#                        (lwir11 on Landsat 8/9, lwir on Landsat 4-7)
#  Landsat has no red-edge band, so there is no NDRE here — but it
#  DOES have a thermal band, so we add a TEMP product instead.
# =============================================================================

# Product definitions. "bands" = asset names needed (first defines
# the pixel grid). Indices use (A-B)/(A+B) on the first two bands,
# computed on real reflectance (scale 0.0000275, offset -0.2).
PRODUCTS = {
    "RGB":  {"kind": "composite",
             "bands": ["red", "green", "blue"],
             "label": "RGB — natural colours (like from a plane)"},
    "CIR":  {"kind": "composite",
             "bands": ["nir08", "red", "green"],
             "label": "CIR — infrared (vegetation in red)"},
    "SWIR": {"kind": "composite",
             "bands": ["swir16", "nir08", "blue"],
             "label": "SWIR — agriculture (crops, soil moisture)"},
    "GEO":  {"kind": "composite",
             "bands": ["swir22", "swir16", "blue"],
             "label": "GEO — geology (rocks, quarries)"},
    "NDVI": {"kind": "index",
             "bands": ["nir08", "red"],
             "label": "NDVI — vegetation condition (the classic)"},
    "NDWI": {"kind": "index",
             "bands": ["green", "nir08"],
             "label": "NDWI — surface water (lakes, floods)"},
    "NDMI": {"kind": "index",
             "bands": ["nir08", "swir16"],
             "label": "NDMI — vegetation moisture (droughts)"},
    "NBR":  {"kind": "index",
             "bands": ["nir08", "swir22"],
             "label": "NBR — burn severity (wildfires)"},
    "NDSI": {"kind": "index",
             "bands": ["green", "swir16"],
             "label": "NDSI — snow and ice"},
    "TEMP": {"kind": "temperature",
             "bands": ["lwir11"],   # falls back to "lwir" on L4-7
             "label": "TEMP — land surface temperature in °C"},
}

# mission choices for the GUI: (label, list of STAC platform names)
MISSIONS = [
    ("Landsat 8 + 9 (2013 — today, recommended)",
     ["landsat-8", "landsat-9"]),
    ("Landsat 7 (1999 — 2022)", ["landsat-7"]),
    ("Landsat 4 + 5 (1982 — 2013)", ["landsat-4", "landsat-5"]),
    ("All Landsat missions (1982 — today)",
     ["landsat-4", "landsat-5", "landsat-7", "landsat-8",
      "landsat-9"]),
]

# scene selection strategies (shared by both dialogs)
STRATEGIES = [
    ("Take all found scenes", "ALL"),
    ("Let me pick from the list (checkboxes)", "MANUAL"),
    ("Best 3 of every month (least clouds)", "TOP3"),
]

MONTH_NAMES = {"01": "January", "02": "February", "03": "March",
               "04": "April", "05": "May", "06": "June",
               "07": "July", "08": "August", "09": "September",
               "10": "October", "11": "November", "12": "December"}

# =============================================================================
#  READY-MADE SYMBOLOGY — palettes written as .qml next to each .tif;
#  QGIS applies them automatically, so the user gets a coloured,
#  labelled map instead of a grey sheet.
# =============================================================================

PALETTES = {
    "NDVI": [(-1.0, "#d7191c", "water / no vegetation"),
             (0.0, "#fdae61", "soil, built-up"),
             (0.2, "#ffffbf", "sparse vegetation"),
             (0.5, "#a6d96a", "good vegetation"),
             (1.0, "#1a9641", "lush vegetation")],
    "NDWI": [(-1.0, "#8c510a", "dry land"),
             (0.0, "#f6e8c3", "land"),
             (0.2, "#80cdc1", "wet / shallows"),
             (1.0, "#01665e", "water")],
    "NDMI": [(-1.0, "#d73027", "severe drought"),
             (0.0, "#fee090", "dry"),
             (0.4, "#91bfdb", "moist"),
             (1.0, "#4575b4", "very moist")],
    "NBR":  [(-1.0, "#67001f", "fresh burn scar"),
             (0.0, "#f7f7f7", "neutral terrain"),
             (0.4, "#a6dba0", "vegetation"),
             (1.0, "#1b7837", "lush vegetation")],
    "NDSI": [(-1.0, "#a6611a", "no snow"),
             (0.0, "#f5f5f5", "transitional"),
             (0.4, "#9ecae1", "snow"),
             (1.0, "#2171b5", "snow / ice")],
    "TEMP": [(-20.0, "#313695", "-20 °C"),
             (0.0, "#74add1", "0 °C"),
             (15.0, "#ffffbf", "15 °C"),
             (30.0, "#f46d43", "30 °C"),
             (50.0, "#a50026", "50 °C")],
}

# value range of each palette (min, max) for the QML header
PALETTE_RANGE = {"TEMP": (-20, 50)}


def write_qml(tif_path, product):
    """Writes a .qml style file next to the .tif with a ready colour
    ramp and legend — QGIS applies it automatically on load."""
    if product not in PALETTES:
        return  # composites carry their colours in the file itself
    low, high = PALETTE_RANGE.get(product, (-1, 1))
    items = "\n".join(
        f'            <item alpha="255" value="{value}" '
        f'label="{label}" color="{colour}"/>'
        for value, colour, label in PALETTES[product])
    xml = (
        '<!DOCTYPE qgis>\n<qgis version="3.28.0">\n  <pipe>\n'
        '    <rasterrenderer type="singlebandpseudocolor" band="1" '
        f'opacity="1" classificationMin="{low}" '
        f'classificationMax="{high}">\n'
        '      <rastershader>\n'
        '        <colorrampshader colorRampType="INTERPOLATED" '
        'classificationMode="1" clip="0">\n'
        f'{items}\n'
        '        </colorrampshader>\n      </rastershader>\n'
        '    </rasterrenderer>\n  </pipe>\n</qgis>\n')
    with open(tif_path.replace(".tif", ".qml"), "w",
              encoding="utf-8") as handle:
        handle.write(xml)


# =============================================================================
#  SEARCH (STAC, no account needed)
# =============================================================================

def search_scenes(aoi_geojson, date_from, date_to, clouds, platforms,
                  log=print):
    """
    Asks the Planetary Computer STAC catalogue for Landsat Collection 2
    Level-2 scenes matching the criteria. Results come in pages of
    100 — we loop until we have them all.
    """
    url = STAC_URL
    body = {"collections": [COLLECTION],
            "intersects": aoi_geojson,
            "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lte": clouds},
                      "platform": {"in": platforms}},
            "limit": 100}

    scenes, page = [], 0
    while True:
        page += 1
        log(f"Asking the catalogue for page {page} (a moment)...")
        response = requests.post(url, json=body, timeout=90)
        if response.status_code != 200:
            raise RuntimeError(f"Search failed: {response.text[:200]}")
        payload = response.json()
        found = payload.get("features", [])
        scenes.extend(found)
        log(f"Page {page}: {len(found)} scenes "
            f"(total {len(scenes)}).")
        next_link = next((link for link in payload.get("links", [])
                          if link.get("rel") == "next"), None)
        if not next_link:
            break
        url = next_link.get("href", url)
        body = next_link.get("body", body)
    return scenes


def scene_date(item):
    """The acquisition date of a STAC item (YYYY-MM-DD)."""
    return item.get("properties", {}).get("datetime", "")[:10]


def scene_clouds(item):
    """Cloud cover percentage of a STAC item (or None)."""
    return item.get("properties", {}).get("eo:cloud_cover")


def scene_platform(item):
    """Satellite name, e.g. 'landsat-8'."""
    return item.get("properties", {}).get("platform", "?")


def thermal_asset(item):
    """Thermal band name: 'lwir11' on Landsat 8/9, 'lwir' on 4-7."""
    assets = item.get("assets", {})
    return "lwir11" if "lwir11" in assets else "lwir"


def needed_assets(item, products):
    """The set of band assets required for the chosen products."""
    needed = []
    for product, on in products.items():
        if not on:
            continue
        for band in PRODUCTS[product]["bands"]:
            if band == "lwir11":            # thermal: per-mission name
                band = thermal_asset(item)
            if band not in needed:
                needed.append(band)
    return needed


# =============================================================================
#  DOWNLOADING (band files with retries and resuming)
# =============================================================================

def sign(url):
    """
    Planetary Computer serves files from Azure storage and expects a
    short-lived signed link — this endpoint hands one out to anyone,
    no account needed.
    """
    response = requests.get(SIGN_URL, params={"href": url}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"link signing failed "
                           f"(code {response.status_code})")
    return response.json()["href"]


def download_band(item, asset, folder, log=print, who=""):
    """
    Downloads one band file of one scene. Skips files already on
    disk, retries after errors and keeps a .part name while
    downloading so an interrupted transfer never masquerades as a
    finished file. Returns the local path.
    """
    target = os.path.join(folder, f"{item['id']}_{asset}.tif")
    temp_path = target + ".part"
    if os.path.exists(target):
        return target

    href = item["assets"][asset]["href"]
    for attempt in range(1, RETRIES + 1):
        try:
            signed = sign(href)
            response = requests.get(signed, stream=True, timeout=300)
            if response.status_code != 200:
                raise RuntimeError(f"code {response.status_code}")
            with open(temp_path, "wb") as handle:
                for chunk in response.iter_content(
                        chunk_size=8 * 1024 * 1024):
                    handle.write(chunk)
            os.rename(temp_path, target)
            return target
        except Exception as error:
            log(f"{who}   OOPS: band {asset}, attempt {attempt} "
                f"failed ({error}).")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if attempt < RETRIES:
                time.sleep(10)
    raise RuntimeError(f"band {asset}: failed after {RETRIES} "
                       f"attempts")


def download_scene(item, number, total, folder, products,
                   keep_bands, log=print):
    """
    Downloads all bands needed for the chosen products of one scene
    and builds the products. Runs in parallel workers — hence the
    [number/total] prefix. Returns (created products, status, seconds).
    """
    who = f"[{number}/{total}]"
    start = time.time()
    base = item["id"]

    # resumability: if every chosen product already exists — skip
    todo = [product for product, on in products.items() if on
            and not os.path.exists(
                os.path.join(folder, f"{base}_{product}.tif"))]
    if not todo:
        log(f"{who} SKIPPING — products for {base[:35]} already "
            f"exist.")
        return [], "skipped (already done)", 0

    assets = needed_assets(item, {p: True for p in todo})
    log(f"{who} Scene {base[:40]}: downloading {len(assets)} "
        f"band(s)...")
    band_paths = {}
    for asset in assets:
        band_paths[asset] = download_band(item, asset, folder, log,
                                          who)
        log(f"{who}   got band: {asset}")

    created = make_products(item, band_paths, folder, todo, log, who)

    if not keep_bands:
        for path in band_paths.values():
            try:
                os.remove(path)
            except OSError:
                pass
        log(f"{who}   raw band files removed (products kept).")

    elapsed = time.time() - start
    log(f"{who} Done! {base[:40]} — {elapsed/60:.1f} min")
    return created, "OK", elapsed


# =============================================================================
#  PRODUCTS (GDAL + numpy)
# =============================================================================

def _stretch_to_8bit(band):
    """
    Raw values -> a 1-255 image range (2-98 percentile stretch).
    Landsat scenes are rotated rectangles with big black corners
    (value 0 = fill), so data is stretched to 1-255 while zeros stay
    0 and are flagged as nodata — QGIS shows the corners as
    TRANSPARENT instead of a huge black frame.
    """
    positive = band[band > 0]
    if positive.size == 0:
        return np.zeros(band.shape, dtype="uint8")
    low, high = np.percentile(positive, (2, 98))
    if high <= low:
        high = low + 1
    normalised = np.clip((band.astype("float32") - low) / (high - low),
                         0, 1)
    result = (normalised * 254 + 1).astype("uint8")
    result[band == 0] = 0
    return result


def _reflectance(dn):
    """
    Collection 2 Level-2 stores surface reflectance as scaled
    integers. Real reflectance = DN * 0.0000275 - 0.2 (USGS formula).
    We convert before computing indices — otherwise the -0.2 offset
    would skew NDVI & friends.
    """
    return np.clip(dn.astype("float32") * 0.0000275 - 0.2, 0, 1)


def _read(path, shape=None):
    """Reads a band via GDAL (optionally resampled to "shape")."""
    dataset = gdal.Open(path)
    band = dataset.GetRasterBand(1)
    if shape and (dataset.RasterYSize, dataset.RasterXSize) != shape:
        array = band.ReadAsArray(buf_xsize=shape[1],
                                 buf_ysize=shape[0])
    else:
        array = band.ReadAsArray()
    return array, dataset


def _write(target, layers, template, gdal_type, nodata=None):
    """Writes a finished product as GeoTIFF (georeference copied
    from the template band)."""
    driver = gdal.GetDriverByName("GTiff")
    output = driver.Create(
        target, template.RasterXSize, template.RasterYSize,
        len(layers), gdal_type,
        options=["COMPRESS=DEFLATE", "TILED=YES"])
    output.SetGeoTransform(template.GetGeoTransform())
    output.SetProjection(template.GetProjection())
    for number, layer in enumerate(layers, start=1):
        band = output.GetRasterBand(number)
        band.WriteArray(layer)
        if nodata is not None:
            band.SetNoDataValue(nodata)
    output.FlushCache()
    output = None  # closes the file (the GDAL way)


def make_products(item, band_paths, folder, todo, log=print, who=""):
    """Builds the requested products from downloaded band files.
    Returns a list of created .tif paths."""
    created = []
    base = item["id"]

    for product in todo:
        recipe = PRODUCTS[product]
        bands = [thermal_asset(item) if band == "lwir11" else band
                 for band in recipe["bands"]]
        if any(band not in band_paths for band in bands):
            log(f"{who}   Bands missing for {product} — skipping.")
            continue
        target = os.path.join(folder, f"{base}_{product}.tif")
        try:
            if recipe["kind"] == "composite":
                first, template = _read(band_paths[bands[0]])
                shape = first.shape
                layers = [_stretch_to_8bit(first)]
                for band in bands[1:]:
                    array, _ = _read(band_paths[band], shape)
                    layers.append(_stretch_to_8bit(array))
                # nodata=0 -> transparent scene corners in QGIS
                _write(target, layers, template, gdal.GDT_Byte,
                       nodata=0)

            elif recipe["kind"] == "index":
                dn_a, template = _read(band_paths[bands[0]])
                dn_b, _ = _read(band_paths[bands[1]], dn_a.shape)
                valid = (dn_a > 0) & (dn_b > 0)
                a = _reflectance(dn_a)
                b = _reflectance(dn_b)
                total = a + b
                index = np.where(
                    valid & (total > 0),
                    (a - b) / np.where(total > 0, total, 1),
                    -9999).astype("float32")
                _write(target, [index], template, gdal.GDT_Float32,
                       nodata=-9999)
                write_qml(target, product)  # ready colour ramp

            elif recipe["kind"] == "temperature":
                dn, template = _read(band_paths[bands[0]])
                # USGS formula: Kelvin = DN * 0.00341802 + 149
                celsius = np.where(
                    dn > 0,
                    dn.astype("float32") * 0.00341802 + 149 - 273.15,
                    -9999).astype("float32")
                _write(target, [celsius], template, gdal.GDT_Float32,
                       nodata=-9999)
                write_qml(target, "TEMP")   # blue-to-red ramp in °C

            created.append(target)
            log(f"{who}   done: {os.path.basename(target)}")
        except Exception as error:
            log(f"{who}   OOPS: {product} failed ({error}).")
    return created


# =============================================================================
#  REPORT
# =============================================================================

def save_report(folder, report):
    """Writes a CSV report (semicolons and a BOM — Excel-friendly)."""
    path = os.path.join(folder,
                        f"report_{time.strftime('%Y%m%d_%H%M')}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=report[0].keys(),
                                delimiter=";")
        writer.writeheader()
        writer.writerows(report)
    return path
