# Global Mapper test pack

Twelve synthetic tests with known answers. Global Mapper's reports for them
pin down how it measures area, interpolates the DEM, measures 3D area and
handles the polygon boundary, so the QGIS Cut & Fill tool can copy it.

Each folder `T01` … `T12` holds `dem.tif` (DEM) and `area.shp` (one polygon).

## For each test

1. **Start clean.** Open a new, empty Global Mapper workspace. Load `dem.tif`
   **first** (so Global Mapper takes its projection), then `area.shp`.
   Do not change Config > Projection.
2. **Select the polygon** and open the cut-and-fill volume calculation, the
   same way you produced `example_cut.txt` and `Example2.txt`.
3. In **Volume Calculation Parameters Setup**:
   - Volume Calculation Type: **Calculate Cut-and-Fill Volumes Within Area Feature**
   - Sample Spacing: **leave what Global Mapper fills in**. Write the X-axis and
     Y-axis values into `results.csv`.
   - Volume Units: **cubic meters**
   - **Perform Multiple Calculations Over a Range of Base Heights**, Meters,
     above sea level, with the From / To / Step in the table below
   - Leave **Interpolate to Fill Small Gaps in Data** unticked, and the
     "Find Area Cut Height…" options off
4. **Save the report** in the test's folder as `<ID>_GM.txt`
   (e.g. `T01\T01_GM.txt`), in the same format as `example_cut.txt`.

| ID | Surface and polygon | CRS | Base from | to | step |
|---|---|---|---|---|---|
| T01 | Flat 0 m, 1 km square, central meridian, 25° S | MGA55 (EPSG:7855) | 1 | 3 | 1 |
| T02 | Flat 0 m, 1 km square, 300 km east of central meridian, 25° S | MGA55 | 1 | 3 | 1 |
| T03 | Flat 0 m, 1 km square, central meridian, 40° S | MGA55 | 1 | 3 | 1 |
| T04 | Flat 0 m, 1 km square, central meridian, 10° S | MGA55 | 1 | 3 | 1 |
| T05 | Flat 0 m, 0.01° square, 25° S | GDA2020 geographic (EPSG:7844) | 1 | 3 | 1 |
| T06 | Flat 0 m, 1 km square (map units), 40° S | Web Mercator (EPSG:3857) | 1 | 3 | 1 |
| T07 | One 10 m spike in one cell, 200 m square | MGA55 | 0 | 10 | 1 |
| T08 | Egg-crate, wavelength 40 m, 10 m DEM, 400 m square | MGA55 | 5 | 15 | 1 |
| T09 | Tilted plane, 10 % slope, 1 km square | MGA55 | 150 | 250 | 10 |
| T10 | Egg-crate, wavelength 80 m, 20 m DEM, 1 km square | MGA55 | 5 | 15 | 1 |
| T11 | Flat 0 m, circle radius 200 m | MGA55 | 1 | 3 | 1 |
| T12 | Flat 0 m, strip 2,000 m × 50 m | MGA55 | 1 | 3 | 1 |

If Global Mapper reprojects anything, refuses a test, or a value looks odd,
note it in the `notes` column of `results.csv`.

## When done

Tell Claude. It runs:

```
python -I analyse_gm_tests.py
```

which compares every report with each hypothesis (area model, surface
interpolation, 3D method, boundary handling, spacing rule).
`python -I analyse_gm_tests.py --predict` shows the predictions without
reports. `make_gm_test_pack.py` rebuilds the pack.
