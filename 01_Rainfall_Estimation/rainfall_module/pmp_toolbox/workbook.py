"""Save and re-open a PMP job as a single Excel workbook.

One job is one ``.xlsx``: every case on every tab, its inputs and its results,
in one file that can be reopened and carried on with.  That is the Drain Design
Toolbox's project model, and it suits this plugin for the same reason -- a PMP
estimate is rarely one run, and the inputs behind a depth table are the only
thing that makes it auditable.

Layout of the workbook::

    Summary            one row per case, across all three tabs
    GSDM Inputs        one row per case, a column per input
    GSDM Results       each case's result table, stacked and labelled
    Areal GSDM Inputs
    Areal GSDM Results
    GTSMR Inputs
    GTSMR Results

Re-opening reads only the ``* Inputs`` sheets.  Results are output, and are
recomputed by pressing Calculate rather than trusted from a file somebody may
have edited.

``openpyxl`` is imported where it is used, not at module scope: QGIS bundles
numpy and matplotlib but not openpyxl, and a missing optional dependency should
cost the user an actionable message rather than a plugin that will not load.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Sheet names are capped at 31 characters by the format itself.
MAX_SHEET_NAME = 31

INSTALL_HINT = (
    "Saving and opening projects needs the openpyxl package, which this QGIS "
    "install does not have.\n\n"
    "Install it into the QGIS Python environment, for example from the OSGeo4W "
    "shell:\n\n    python -m pip install openpyxl\n\n"
    "Everything else in the plugin works without it, and each tab can still "
    "export CSV."
)


class WorkbookError(RuntimeError):
    """Anything that stops a project being written or read, with a reason."""


def _openpyxl():
    try:
        import openpyxl  # noqa: PLC0415 -- deliberately deferred
    except ImportError as exc:
        raise WorkbookError(INSTALL_HINT) from exc
    return openpyxl


# --------------------------------------------------------------- serialising


def serialise_inputs(inputs: dict) -> dict:
    """A case's inputs as values a spreadsheet cell can hold.

    Three kinds of value need care:

    * the catchment layer, which is a live QGIS object -- stored by name, and
      resolved back against the open project on the way in;
    * nested dicts and lists (the sampled grid factors, the zone reading, the
      ring weights) -- stored as JSON in one cell, because spreading them over
      columns would make the sheet unreadable and the round-trip fragile;
    * keys beginning with an underscore, which are cached render state and are
      deliberately dropped.
    """
    out: dict[str, object] = {}
    for key, value in inputs.items():
        if key.startswith("_"):
            continue
        if key == "layer":
            out[key] = value.name() if value is not None else ""
        elif isinstance(value, (dict, list, tuple)):
            out[key] = json.dumps(value)
        elif isinstance(value, bool):
            # Written as TRUE/FALSE by openpyxl and read back as bool.
            out[key] = value
        elif value is None:
            out[key] = ""
        else:
            out[key] = value
    return out


def deserialise_inputs(row: dict) -> dict:
    """The inverse of :func:`serialise_inputs`, against the open project."""
    from qgis.core import QgsProject

    out: dict[str, object] = {}
    for key, value in row.items():
        if key is None or str(key).startswith("_"):
            continue
        if key == "layer":
            out[key] = _find_layer(QgsProject.instance(), value)
        elif isinstance(value, str) and value[:1] in "{[":
            try:
                out[key] = _retuple(json.loads(value))
            except json.JSONDecodeError:
                out[key] = value
        else:
            out[key] = value
    return out


def _retuple(value):
    """JSON turns tuples into lists; the factor rows expect pairs back."""
    if isinstance(value, dict):
        return {
            k: tuple(v) if isinstance(v, list) and len(v) == 2 else v
            for k, v in value.items()
        }
    return value


def _find_layer(project, name):
    if not name:
        return None
    for layer in project.mapLayers().values():
        if layer.name() == name:
            return layer
    # A project saved against a layer that is not open now is not an error:
    # the case keeps every other input and the user repicks the layer.
    return None


def _sheet_name(prefix: str, suffix: str) -> str:
    name = f"{prefix} {suffix}"
    return name[:MAX_SHEET_NAME]


# ------------------------------------------------------------------- writing


def save_project(path, tabs, project_name: str = "") -> None:
    """Write every tab's cases to one workbook.

    ``tabs`` is a sequence of ``(key, tab)``; each tab must expose ``cases``
    and, for anything it has calculated, ``case.table``.
    """
    openpyxl = _openpyxl()
    book = openpyxl.Workbook()
    book.remove(book.active)

    summary = book.create_sheet("Summary")
    summary.append(["PMP Toolbox project"])
    summary.append(["Project", project_name])
    summary.append([])
    summary.append(
        ["Tab", "Case", "Layer", "Area (km2)", "Centroid", "Calculated", "Result"]
    )

    for key, tab in tabs:
        cases = tab.cases.cases()
        for case in cases:
            inputs = case.inputs
            layer = inputs.get("layer")
            summary.append([
                key,
                case.name,
                layer.name() if layer is not None else "",
                _area_of(tab),
                _centroid_of(tab),
                "yes" if case.result is not None else "no",
                _plain(case.summary),
            ])

        _write_inputs(book, key, cases)
        _write_results(book, key, cases)

    _autosize(summary)
    try:
        book.save(str(path))
    except PermissionError as exc:
        raise WorkbookError(
            f"Could not write {Path(path).name} -- it is probably open in Excel. "
            "Close it and try again."
        ) from exc
    except OSError as exc:
        raise WorkbookError(str(exc)) from exc


def _write_inputs(book, key: str, cases) -> None:
    sheet = book.create_sheet(_sheet_name(key, "Inputs"))
    rows = [serialise_inputs(c.inputs) for c in cases]

    # A union of keys in first-seen order, so a case that carries an extra
    # input does not shift everyone else's columns.
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)

    sheet.append(["Case"] + columns)
    for case, row in zip(cases, rows):
        sheet.append([case.name] + [row.get(c, "") for c in columns])
    _autosize(sheet)


def _write_results(book, key: str, cases) -> None:
    sheet = book.create_sheet(_sheet_name(key, "Results"))
    wrote = False
    for case in cases:
        if case.table is None:
            continue
        wrote = True
        sheet.append([case.name])
        sheet.append(list(case.table.headers))
        for row in case.table.rows:
            sheet.append(list(row))
        if case.table.warnings:
            sheet.append([])
            for warning in case.table.warnings:
                sheet.append(["WARNING", warning])
        sheet.append([])
        sheet.append(["Run inputs"])
        for name, value in case.table.run_inputs:
            sheet.append([name, value])
        sheet.append([])
        sheet.append([])
    if not wrote:
        sheet.append(["No case on this tab has been calculated."])
    _autosize(sheet)


def _autosize(sheet, limit: int = 60) -> None:
    """Widen columns to fit, up to a limit so one long note cannot dominate."""
    widths: dict[int, int] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            widths[cell.column] = max(
                widths.get(cell.column, 0), min(len(str(cell.value)), limit)
            )
    for column, width in widths.items():
        letter = sheet.cell(row=1, column=column).column_letter
        sheet.column_dimensions[letter].width = width + 2


def _plain(html: str) -> str:
    """The summary line without its markup, for a spreadsheet cell."""
    import re

    text = re.sub(r"<[^>]+>", " ", html or "")
    return " ".join(text.replace("&nbsp;", " ").split())


def _area_of(tab) -> str:
    catchment = tab.picker.catchment()
    return f"{catchment.area_km2:.4f}" if catchment else ""


def _centroid_of(tab) -> str:
    catchment = tab.picker.catchment()
    if catchment is None:
        return ""
    from .tabs.common import describe_latlon

    return describe_latlon(catchment.lat, catchment.lon)


# ------------------------------------------------------------------- reading


def load_project(path, tabs) -> dict:
    """Rebuild each tab's cases from a workbook's ``* Inputs`` sheets.

    Returns a report: ``{"project": name, "loaded": {key: n}, "missing": [...]}``
    so the caller can say what came back rather than silently doing nothing.
    Results are not read -- they are output, and are recomputed on demand.
    """
    openpyxl = _openpyxl()
    try:
        book = openpyxl.load_workbook(str(path), data_only=True)
    except OSError as exc:
        raise WorkbookError(str(exc)) from exc

    report = {"project": "", "loaded": {}, "missing": []}

    if "Summary" in book.sheetnames:
        for row in book["Summary"].iter_rows(min_row=1, max_row=4, values_only=True):
            if row and row[0] == "Project":
                report["project"] = str(row[1] or "")
                break

    for key, tab in tabs:
        name = _sheet_name(key, "Inputs")
        if name not in book.sheetnames:
            report["missing"].append(key)
            continue
        rows = list(book[name].iter_rows(values_only=True))
        if not rows:
            report["missing"].append(key)
            continue
        header = [str(h) if h is not None else "" for h in rows[0]]
        loaded = 0
        cases = []
        for row in rows[1:]:
            if row is None or row[0] in (None, ""):
                continue
            record = dict(zip(header[1:], row[1:]))
            cases.append((str(row[0]), deserialise_inputs(record)))
            loaded += 1
        if cases:
            tab.load_cases(cases)
        report["loaded"][key] = loaded

    return report
