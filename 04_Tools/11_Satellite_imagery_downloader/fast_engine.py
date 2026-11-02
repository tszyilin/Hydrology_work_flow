# -*- coding: utf-8 -*-
"""
FAST ENGINE — standalone (no QGIS) bulk downloader built on top of
the "Landsat Download" plugin's engine.py. Sources: Landsat
(Planetary Computer), Sentinel-2 raw bands (Earth Search, or
Copernicus Data Space with a login) — see SOURCES.

What it adds over the plugin:
  - band-level parallelism (many band files at once, not 1-4 scenes)
  - one SAS token per storage container (cached ~1 h) instead of one
    signing request per band -> no 429 rate-limit errors when many
    downloads run in parallel
  - pooled HTTP connections, retries with back-off, clean Stop
  - product building (memory heavy) limited by its own semaphore so
    many downloads never mean many 1 GB numpy arrays at once
  - searching split into yearly chunks (2001 / 2002 / 2003 ...),
    each year written to its own sub-folder, resumable
  - events go to a queue the GUI polls -> no signal flood
"""

import os
import sys
import time
import queue
import calendar
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urljoin

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "Landsat-Download"))

# Anaconda's GDAL does not always know where its data folder is
if "GDAL_DATA" not in os.environ:
    _gdal_data = os.path.join(sys.prefix, "Library", "share", "gdal")
    if os.path.isdir(_gdal_data):
        os.environ["GDAL_DATA"] = _gdal_data

import requests                                   # noqa: E402
from requests.adapters import HTTPAdapter         # noqa: E402

import engine                                     # noqa: E402

TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token"
CDSE_TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/"
                  "CDSE/protocol/openid-connect/token")
RETRIES = 5
CHUNK = 1024 * 1024

PLATFORMS = [("Landsat 4", "landsat-4"), ("Landsat 5", "landsat-5"),
             ("Landsat 7", "landsat-7"), ("Landsat 8", "landsat-8"),
             ("Landsat 9", "landsat-9")]
S2_PLATFORMS = [("Sentinel-2A", "sentinel-2a"),
                ("Sentinel-2B", "sentinel-2b"),
                ("Sentinel-2C", "sentinel-2c")]

# extra raw bands that can be downloaded on top of the products
# (Landsat names; each source maps them to its own asset)
EXTRA_BANDS = {"qa_pixel": "QA_PIXEL (cloud / shadow mask)"}

# =============================================================================
#  SOURCES — where scenes come from. Band names everywhere else are the
#  Landsat asset names of engine.PRODUCTS; "asset_map" translates them
#  to the source's own asset (None = the source has no such band).
# =============================================================================

SOURCES = {
    "landsat": {
        "label": "Landsat C2 L2 (Planetary Computer)",
        "stac_url": engine.STAC_URL, "collection": engine.COLLECTION,
        "platforms": PLATFORMS, "default_platforms": ["landsat-5",
                                                      "landsat-7"],
        "platform_filter": True, "signed": True, "auth": None,
        "https_alternate": False, "ext": ".tif", "asset_map": {},
        # folder "" = straight into the output folder, as before, so
        # downloads already started there still resume
        "products": True, "max_connections": None, "folder": "",
        "gb_per_band": engine.GB_PER_BAND,
        "extra_label": "QA_PIXEL (cloud / shadow mask)",
        "hint": "2001-2003: Landsat 5 + 7. Landsat 7 has scan-line gaps "
                "(SLC-off) after 31 May 2003."},
    "s2_earthsearch": {
        "label": "Sentinel-2 L2A (Earth Search, AWS — fast, no login)",
        "stac_url": "https://earth-search.aws.element84.com/v1/search",
        "collection": "sentinel-2-c1-l2a",
        "platforms": S2_PLATFORMS,
        "default_platforms": [p for _, p in S2_PLATFORMS],
        "platform_filter": True, "signed": False, "auth": None,
        "https_alternate": False, "ext": ".tif",
        "asset_map": {"nir08": "nir", "qa_pixel": "scl",
                      "lwir11": None, "lwir": None},
        "products": False, "max_connections": None, "folder": "Sentinel2",
        "gb_per_band": 0.18,
        "extra_label": "SCL (scene classification / cloud mask)",
        "hint": "Sentinel-2 starts mid-2015. Raw bands at native "
                "resolution (10 m: blue, green, red, nir; 20 m: swir)."},
    "s2_cdse": {
        "label": "Sentinel-2 L2A (Copernicus Data Space — login)",
        "stac_url": "https://stac.dataspace.copernicus.eu/v1/search",
        "collection": "sentinel-2-l2a",
        "platforms": S2_PLATFORMS,
        "default_platforms": [p for _, p in S2_PLATFORMS],
        "platform_filter": False,          # CDSE rejects "in" queries
        "signed": False, "auth": "cdse",
        "https_alternate": True, "ext": ".jp2",
        "asset_map": {"blue": "B02_10m", "green": "B03_10m",
                      "red": "B04_10m", "nir08": "B08_10m",
                      "swir16": "B11_20m", "swir22": "B12_20m",
                      "qa_pixel": "SCL_20m", "lwir11": None, "lwir": None},
        "products": False, "max_connections": 4,   # CDSE per-user limit
        "folder": "Sentinel2_CDSE", "gb_per_band": 0.12,
        "extra_label": "SCL (scene classification / cloud mask)",
        "hint": "Free Copernicus account needed. Max 4 downloads at once "
                "and servers in Europe — slower than Earth Search."},
}


def source_assets(source, item, product_keys, extra_bands=()):
    """The source's asset names needed for the products + extras."""
    names = engine.needed_assets(item, {p: True for p in product_keys})
    names += [b for b in extra_bands if b not in names]
    assets = []
    for name in names:
        asset = source["asset_map"].get(name, name)
        if asset and asset in item["assets"] and asset not in assets:
            assets.append(asset)
    return assets


def asset_href(source, item, asset):
    entry = item["assets"][asset]
    if source["https_alternate"]:
        return entry["alternate"]["https"]["href"]
    return entry["href"]


class Cancelled(Exception):
    pass


def make_session(pool_size):
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_size,
                          pool_maxsize=pool_size)
    session.mount("https://", adapter)
    return session


# =============================================================================
#  SEARCH — split into yearly chunks
# =============================================================================

def year_chunks(date_from, date_to, split):
    """[('2001', '2001-01-01', '2001-12-31'), ...] or one chunk."""
    if not split:
        return [(f"{date_from}_{date_to}", date_from, date_to)]
    chunks = []
    for year in range(int(date_from[:4]), int(date_to[:4]) + 1):
        start = max(date_from, f"{year}-01-01")
        end = min(date_to, f"{year}-12-31")
        chunks.append((str(year), start, end))
    return chunks


def search_stac(source, aoi, date_from, date_to, clouds, platforms):
    """STAC search with paging (same idea as engine.search_scenes, but
    for any source; follows POST-body and GET 'next' links)."""
    query = {"eo:cloud_cover": {"lte": clouds}}
    if source["platform_filter"]:
        query["platform"] = {"in": platforms}
    body = {"collections": [source["collection"]], "intersects": aoi,
            "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
            "query": query, "limit": 100}
    url, method, items = source["stac_url"], "POST", []
    while True:
        if method == "POST":
            response = requests.post(url, json=body, timeout=90)
        else:
            response = requests.get(url, timeout=90)
        if response.status_code != 200:
            raise RuntimeError(f"search failed: {response.text[:200]}")
        payload = response.json()
        items.extend(payload.get("features", []))
        link = next((l for l in payload.get("links", [])
                     if l.get("rel") == "next"), None)
        if not link:
            break
        url = link.get("href", url)
        method = link.get("method", "GET").upper()
        if method == "POST":
            body = dict(body, **link["body"]) if link.get("merge") \
                else link.get("body", body)
    # platform filter on our side too (needed where the server can't)
    return [item for item in items
            if engine.scene_platform(item).lower() in platforms]


def search_chunks(source, aoi, date_from, date_to, clouds, platforms,
                  split, log=print, stop=None):
    """Searches every chunk (with retries). Returns
    [(label, [items])] — scenes de-duplicated across chunks."""
    results, seen = [], set()
    for label, start, end in year_chunks(date_from, date_to, split):
        if stop is not None and stop.is_set():
            raise Cancelled()
        log(f"Searching {label} ({start} .. {end})...")
        for attempt in range(1, RETRIES + 1):
            try:
                items = search_stac(source, aoi, start, end, clouds,
                                    platforms)
                break
            except Exception as error:
                log(f"  search {label} attempt {attempt} failed: {error}")
                if attempt == RETRIES:
                    raise
                time.sleep(5 * attempt)
        items = [item for item in items if item["id"] not in seen]
        seen.update(item["id"] for item in items)
        items.sort(key=engine.scene_date)
        log(f"  {label}: {len(items)} scenes")
        results.append((label, items))
    return results


# =============================================================================
#  SIGNING — one cached SAS token per storage container
# =============================================================================

class Signer:
    def __init__(self, session):
        self.session = session
        self.lock = threading.Lock()
        self.tokens = {}            # (account, container) -> (token, expiry)

    @staticmethod
    def _key(href):
        # https://<account>.blob.core.windows.net/<container>/...
        host, path = href.split("://", 1)[1].split("/", 1)
        return host.split(".")[0], path.split("/", 1)[0]

    def _fetch(self, key):
        for attempt in range(1, RETRIES + 1):
            response = self.session.get(f"{TOKEN_URL}/{key[0]}/{key[1]}",
                                        timeout=30)
            if response.status_code == 200:
                data = response.json()
                expiry = calendar.timegm(time.strptime(
                    data["msft:expiry"][:19], "%Y-%m-%dT%H:%M:%S"))
                return data["token"], expiry
            time.sleep(3 * attempt)
        raise RuntimeError(f"token request failed "
                           f"(code {response.status_code})")

    def sign(self, href, refresh=False):
        key = self._key(href)
        with self.lock:
            token, expiry = self.tokens.get(key, (None, 0))
            if refresh or token is None or time.time() > expiry - 300:
                token, expiry = self._fetch(key)
                self.tokens[key] = (token, expiry)
        return f"{href}{'&' if '?' in href else '?'}{token}"


# =============================================================================
#  LOGIN — Copernicus Data Space bearer token (cached, auto-refreshed)
# =============================================================================

class LoginFailed(RuntimeError):
    pass


class TokenAuth:
    """CDSE password login. The token lives ~10 min; it is renewed a
    minute before it expires (or after a 401). The password stays in
    memory only."""

    def __init__(self, session, username, password):
        self.session = session
        self.username = username
        self.password = password
        self.lock = threading.Lock()
        self.token, self.expiry = None, 0

    def _login(self):
        response = self.session.post(CDSE_TOKEN_URL, timeout=30, data={
            "client_id": "cdse-public", "grant_type": "password",
            "username": self.username, "password": self.password})
        if response.status_code in (400, 401):
            raise LoginFailed("Copernicus login failed — check the "
                              "e-mail and password.")
        if response.status_code != 200:
            raise RuntimeError(f"login request failed "
                               f"(code {response.status_code})")
        data = response.json()
        self.token = data["access_token"]
        self.expiry = time.time() + int(data.get("expires_in", 600))

    def headers(self, refresh=False):
        with self.lock:
            if refresh or self.token is None or \
                    time.time() > self.expiry - 60:
                self._login()
            return {"Authorization": f"Bearer {self.token}"}


# =============================================================================
#  DOWNLOADER
# =============================================================================

class BulkDownloader:
    """
    jobs: list of (item, folder, source). Runs in a background thread
    (call run()). Talks to the GUI only through self.events:
      ("log", text) / ("scene", record_dict) / ("done", summary)
    self.bytes_done is read by the GUI to compute the speed.
    """

    def __init__(self, jobs, products, extra_bands=(), raw_only=False,
                 keep_bands=True, workers=8, builders=2):
        self.jobs = jobs
        self.products = {p: True for p, on in products.items() if on}
        self.extra_bands = list(extra_bands)
        self.raw_only = raw_only
        self.keep_bands = keep_bands or raw_only
        self.workers = workers
        self.builders = builders
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.bytes_done = 0
        self._bytes_lock = threading.Lock()
        self.active = {}          # (scene id, band) -> live state dict
        self.session = make_session(workers + 4)
        self.signer = Signer(self.session)
        self.auths = {}           # source "auth" key -> TokenAuth
        self.build_gate = threading.Semaphore(builders)
        # one band pool per source, so a source with a connection cap
        # (CDSE: 4) never blocks the others' slots
        self.band_pools = {}
        # enough scenes in flight (~3+ bands each) to keep every band
        # slot busy while others build products — but not so many that
        # every scene is half-done at once
        self.scene_pool = ThreadPoolExecutor(
            max(2, workers // 3) + builders, thread_name_prefix="scene")
        self._lock = threading.Lock()
        self._pending = {}        # future -> (item, folder)
        self._queued = set()      # (scene id, folder) ever queued
        self.total = 0
        self.closed = False

    def set_login(self, auth_key, username, password):
        self.auths[auth_key] = TokenAuth(self.session, username, password)

    def band_pool(self, source):
        with self._lock:
            pool = self.band_pools.get(source["label"])
            if pool is None:
                size = min(self.workers,
                           source["max_connections"] or self.workers)
                pool = ThreadPoolExecutor(size, thread_name_prefix="band")
                self.band_pools[source["label"]] = pool
            return pool

    def add_jobs(self, jobs):
        """Adds scenes to the running queue. Returns how many were new,
        or None if this run has already finished (start a new one)."""
        added = 0
        with self._lock:
            if self.closed:
                return None
            for item, folder, source in jobs:
                if (item["id"], folder) in self._queued:
                    continue
                self._queued.add((item["id"], folder))
                self.total += 1
                future = self.scene_pool.submit(self.do_scene, item,
                                                folder, source, self.total)
                self._pending[future] = (item, folder)
                added += 1
        return added

    def log(self, text):
        self.events.put(("log", text))

    # ---- one band ----------------------------------------------------------
    def download_band(self, item, asset, folder, source, who):
        """Downloads one band; while it runs, self.active[(scene,
        band)] holds its live state for the GUI's progress table."""
        key = (item["id"], asset)
        try:
            return self._download_band(item, asset, folder, source, who,
                                       key)
        finally:
            self.active.pop(key, None)

    def _request(self, source, href, headers, refresh):
        """GET with signing / login. Redirects are followed by hand so
        the login header survives a hop to another host."""
        url = self.signer.sign(href, refresh=refresh) if source["signed"] \
            else href
        if source["auth"]:
            auth = self.auths.get(source["auth"])
            if auth is None:
                raise LoginFailed("no login given for this source")
            headers = dict(headers, **auth.headers(refresh=refresh))
        for _ in range(5):
            response = self.session.get(url, stream=True, headers=headers,
                                        timeout=(30, 120),
                                        allow_redirects=False)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            url = urljoin(url, response.headers["Location"])
            response.close()
        raise RuntimeError("too many redirects")

    def _download_band(self, item, asset, folder, source, who, key):
        """
        A broken connection keeps the .part file and the next attempt
        asks only for the missing bytes (HTTP Range) — also across
        runs, so Stop / crash never wastes data. Attempts that made
        progress do not count towards the limit.
        """
        target = os.path.join(folder, f"{item['id']}_{asset}"
                                      f"{source['ext']}")
        if os.path.exists(target):
            return target
        temp_path = target + ".part"
        href = asset_href(source, item, asset)
        refresh = False
        failures = 0
        entry = {"scene": item["id"], "asset": asset, "done": 0,
                 "total": 0, "state": "connecting"}
        self.active[key] = entry
        while True:
            if self.stop.is_set():
                raise Cancelled()
            have = os.path.getsize(temp_path) \
                if os.path.exists(temp_path) else 0
            got = 0
            entry["done"] = have
            try:
                headers = {"Range": f"bytes={have}-"} if have else {}
                with self._request(source, href, headers,
                                   refresh) as response:
                    code = response.status_code
                    if code in (401, 403):
                        refresh = True
                        raise RuntimeError(f"code {code} (token)")
                    if code == 416:            # .part is already whole
                        os.replace(temp_path, target)
                        return target
                    if code == 206:
                        mode = "ab"
                        total = int(response.headers.get(
                            "Content-Range", "/0").rsplit("/", 1)[1])
                    elif code == 200:          # server ignored Range
                        mode, have = "wb", 0
                        total = int(response.headers.get(
                            "Content-Length", 0))
                    else:
                        raise RuntimeError(f"code {code}")
                    entry.update(total=total, done=have,
                                 state="downloading")
                    with open(temp_path, mode) as handle:
                        for chunk in response.iter_content(CHUNK):
                            if self.stop.is_set():
                                raise Cancelled()
                            handle.write(chunk)
                            got += len(chunk)
                            entry["done"] = have + got
                            with self._bytes_lock:
                                self.bytes_done += len(chunk)
                if total and have + got < total:
                    raise RuntimeError(f"incomplete ({have + got} of "
                                       f"{total} bytes)")
                os.replace(temp_path, target)
                return target
            except (Cancelled, LoginFailed):
                raise                       # keep .part for resuming
            except Exception as error:
                if got == 0:
                    failures += 1
                if failures >= RETRIES:
                    raise RuntimeError(f"band {asset} failed after "
                                       f"{RETRIES} attempts ({error})")
                entry["state"] = f"reconnecting ({failures}/{RETRIES})"
                self.log(f"{who} resume {asset} at "
                         f"{(have + got)/1e6:.0f} MB "
                         f"(fail {failures}/{RETRIES}): "
                         f"{str(error)[:80]}")
                self.stop.wait(min(60, 5 * max(1, failures)))

    @staticmethod
    def _remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

    # ---- one scene ---------------------------------------------------------
    def do_scene(self, item, folder, source, number):
        who = f"[{number}]"
        base = item["id"]
        start = time.time()
        if self.stop.is_set():
            raise Cancelled()
        os.makedirs(folder, exist_ok=True)

        if self.raw_only or not source["products"]:
            todo = []
            assets = source_assets(source, item, self.products,
                                   self.extra_bands)
            missing = [a for a in assets if not os.path.exists(
                os.path.join(folder, f"{base}_{a}{source['ext']}"))]
            if not missing:
                return [], "skipped (already done)", 0
        else:
            todo = [p for p in self.products if not os.path.exists(
                os.path.join(folder, f"{base}_{p}.tif"))]
            if not todo:
                return [], "skipped (already done)", 0
            assets = source_assets(source, item, todo, self.extra_bands)
        if not assets:
            raise RuntimeError("none of the chosen bands exist for this "
                               "scene")

        # all bands of this scene download in parallel in the band pool
        self.events.put(("status", (base, f"downloading {len(assets)} "
                                          f"bands")))
        pool = self.band_pool(source)
        futures = {pool.submit(self.download_band, item, asset, folder,
                               source, who): asset
                   for asset in assets}
        wait(futures)
        band_paths = {}
        for future, asset in futures.items():
            band_paths[asset] = future.result()   # re-raises errors
        if self.stop.is_set():
            raise Cancelled()

        created = []
        if todo:
            with self.build_gate:                 # limit RAM use
                if self.stop.is_set():
                    raise Cancelled()
                self.events.put(("status", (base, "building products")))
                created = engine.make_products(
                    item, band_paths, folder, todo, self.log, who)
            if not self.keep_bands:
                extras = set(source_assets(source, item, [],
                                           self.extra_bands))
                for asset, path in band_paths.items():
                    if asset not in extras:       # QA/SCL is kept
                        self._remove(path)

        elapsed = time.time() - start
        self.log(f"{who} done {base} ({elapsed/60:.1f} min)")
        return created, "OK", elapsed

    # ---- everything --------------------------------------------------------
    def run(self):
        """Works through the queue until it is empty — scenes added
        with add_jobs() meanwhile are picked up as well."""
        counts = {"ok": 0, "failed": 0, "skipped": 0, "cancelled": 0}
        reports = {}              # folder -> rows
        self.add_jobs(self.jobs)
        try:
            while True:
                with self._lock:
                    pending = set(self._pending)
                    if not pending:
                        self.closed = True     # no more add_jobs()
                        break
                finished, _ = wait(pending, timeout=0.5,
                                   return_when="FIRST_COMPLETED")
                for future in finished:
                    with self._lock:
                        item, folder = self._pending.pop(future)
                    created, seconds = [], 0
                    try:
                        created, status, seconds = future.result()
                        key = "skipped" if status.startswith("skipped") \
                            else "ok"
                    except Cancelled:
                        status, key = "cancelled", "cancelled"
                    except Exception as error:
                        status, key = f"failed ({error})", "failed"
                        self.log(f"FAILED {item['id']}: {error}")
                    counts[key] += 1
                    row = {"scene": item["id"],
                           "date": engine.scene_date(item),
                           "platform": engine.scene_platform(item),
                           "clouds_%": engine.scene_clouds(item),
                           "products": len(created),
                           "status": status,
                           "minutes": round(seconds / 60, 1)}
                    reports.setdefault(folder, []).append(row)
                    self.events.put(("scene", dict(row, key=key)))
        finally:
            with self._lock:
                self.closed = True
            self.scene_pool.shutdown(wait=True, cancel_futures=True)
            for pool in list(self.band_pools.values()):
                pool.shutdown(wait=True, cancel_futures=True)
            report_paths = []
            for folder, rows in reports.items():
                rows.sort(key=lambda r: r["date"])
                try:
                    report_paths.append(engine.save_report(folder, rows))
                except Exception as error:
                    self.log(f"Could not write report in {folder}: "
                             f"{error}")
            self.events.put(("done", dict(counts, reports=report_paths)))
