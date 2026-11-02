LANDSAT DOWNLOAD — QGIS plugin
© Grzegorz Górniak (gorniakgrzegorz@gmail.com)

WHAT IT IS
Bulk downloading of Landsat imagery — with NO account, sign-in or
API keys. Data: USGS Landsat Collection 2 Level-2 (surface
reflectance and surface temperature, 30 m, global archive since
1982: Landsat 4, 5, 7, 8 and 9) served openly by the Microsoft
Planetary Computer.
The plugin downloads only the bands needed for the products you
tick and builds ready-symbolised GeoTIFFs:
 - colour composites: RGB, CIR, SWIR (agriculture), GEO (geology)
 - indices on true surface reflectance, with colour ramps and
   legends: NDVI, NDWI, NDMI, NBR, NDSI
 - TEMP — land surface temperature in °C from the thermal band
   (urban heat islands, droughts)

INSTALLATION
1. QGIS -> Plugins -> Manage and Install Plugins...
2. "Install from ZIP" tab
3. Choose landsat_download.zip -> Install Plugin
4. The "Landsat Download" button appears on the toolbar

REQUIREMENTS
- QGIS 3.16 or newer — and nothing else (GDAL and numpy ship with
  QGIS; the data source needs no account)

HOW TO USE
1. Click the "Landsat Download" button
2. Pick the missions (Landsat 8+9 recommended; 4+5 for the 1980s
   and 1990s), the area (a project layer or a .gpkg file), dates,
   cloud limit and a target folder
3. Tick the products and click START DOWNLOAD
4. In the scene picker untick what you do not need (or use "best 3
   of every month"), confirm — and watch the progress bar
5. Finished products can be loaded into the project automatically

Interrupted? Run it again — the plugin skips finished scenes and
completes the rest. A CSV report lands in the target folder.
