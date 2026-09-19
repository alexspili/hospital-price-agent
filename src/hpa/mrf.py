"""Streaming readers for CMS machine-readable standard-charges files (data dictionary v3.0).

Three shapes: CSV wide, CSV tall and JSON. All three yield the same `Charge` records, one
per (item, standard-charge context), carrying only the four summary columns plus the
context needed to judge comparability. Payer-specific columns are skipped. Nothing here
ever holds more than one row or one item in memory.
"""

import csv
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field

import ijson

PARSER_VERSION = "3"  # 2: JSON "modifiers" string; 3: sub-cent values kept (DECIMAL(18,6))
SUMMARY_COLUMNS = ("gross", "discounted_cash", "min", "max")


class OffTemplate(ValueError):
    """The file is not in the CMS template; the message says how it differs."""


@dataclass(frozen=True)
class FileHeader:
    hospital_name: str | None
    last_updated_on: str | None
    version: str | None
    location_names: tuple[str, ...]
    shape: str  # csv-wide | csv-tall | json


@dataclass
class Charge:
    item_id: str  # stable hash of the item identity, same across tall rows
    description: str
    codes: tuple[tuple[str, str], ...]  # (code type, code)
    setting: str | None
    billing_class: str | None
    modifiers: str | None
    drug_unit: str | None
    drug_type: str | None
    gross: float | None
    discounted_cash: float | None
    minimum: float | None
    maximum: float | None
    notes: str | None
    source_ref: str  # "row 1234" or "item 567/charge 2"
    off_template_note: str | None = None  # non-numeric text found in a dollar column


# --- helpers ---------------------------------------------------------------------------

def _item_id(description: str, codes, drug_unit, drug_type) -> str:
    key = json.dumps([description.strip().lower(), sorted(codes), drug_unit or "", drug_type or ""])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _num(value, notes: list[str], column: str) -> float | None:
    """A dollar column holds a positive number or nothing. Anything else is kept as text
    in the off-template note, never coerced."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s == "":
        return None
    try:
        return float(s.replace(",", "")) if not s.startswith("$") else float(s[1:].replace(",", ""))
    except ValueError:
        notes.append(f"{column}={s[:80]!r}")
        return None


def _blank(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _enum(v) -> str | None:
    """setting / billing_class: valid values are case-insensitive per the dictionary."""
    s = _blank(v)
    return s.lower() if s else None


class _SkipBOM(io.RawIOBase):
    """A binary stream minus a leading UTF-8 BOM, which ijson rejects. A real io object,
    because ijson's C backend reads through the io protocol, not a bare `read`."""

    def __init__(self, raw):
        super().__init__()
        self.raw = raw
        self.pending = b""
        first = raw.read(3)
        if first != b"\xef\xbb\xbf":
            self.pending = first

    def readable(self):
        return True

    def readinto(self, b):
        if self.pending:
            n = min(len(b), len(self.pending))
            b[:n] = self.pending[:n]
            self.pending = self.pending[n:]
            return n
        chunk = self.raw.read(len(b))
        b[: len(chunk)] = chunk
        return len(chunk)


# --- CSV ----------------------------------------------------------------------------------

def _norm_header(h: str) -> str:
    return "|".join(p.strip().lower() for p in h.strip().lstrip("﻿").split("|"))


def read_csv_header(lines: Iterator[str]) -> tuple[FileHeader, list[str], list[str]]:
    """Rows 1-3 of a CMS CSV: general-data keys, their values, and the column headers."""
    reader = csv.reader(lines)
    try:
        keys = [_norm_header(k) for k in next(reader)]
        values = next(reader)
        columns = [_norm_header(c) for c in next(reader)]
    except StopIteration:
        raise OffTemplate("fewer than 3 rows")
    general = dict(zip(keys, values))
    if "description" not in columns or "standard_charge|gross" not in columns:
        raise OffTemplate(
            "row 3 is not the CMS header (no 'description' / 'standard_charge|gross'); "
            f"first cells: {columns[:4]}"
        )
    shape = "csv-tall" if "payer_name" in columns else "csv-wide"
    header = FileHeader(
        _blank(general.get("hospital_name")), _blank(general.get("last_updated_on")),
        _blank(general.get("version")), tuple(v for v in [_blank(general.get("location_name"))] if v), shape,
    )
    return header, columns, [k for k in keys]


def iter_csv(lines: Iterator[str]) -> tuple[FileHeader, Iterator[Charge]]:
    lines = iter(lines)
    header, columns, _ = read_csv_header(lines)
    return header, _csv_charges(lines, columns, header.shape)


def _csv_charges(lines: Iterator[str], columns: list[str], shape: str) -> Iterator[Charge]:
    idx = {c: i for i, c in enumerate(columns)}
    code_cols = sorted(
        ((int(m.group(1)), idx[c], idx.get(f"code|{m.group(1)}|type")) for c in columns if (m := re.fullmatch(r"code\|(\d+)", c))),
    )

    def cell(row, name):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else None

    reader = csv.reader(lines)
    seen: dict[str, set[tuple]] = {}  # tall only: item_id -> contexts already emitted
    for n, row in enumerate(reader, start=4):
        if not any(c.strip() for c in row):
            continue
        description = (cell(row, "description") or "").strip()
        codes = tuple(
            ((row[t] if t is not None and t < len(row) else "").strip().upper(), row[c].strip())
            for _, c, t in code_cols if c < len(row) and row[c].strip()
        )
        drug_unit, drug_type = _blank(cell(row, "drug_unit_of_measurement")), _blank(cell(row, "drug_type_of_measurement"))
        item_id = _item_id(description, codes, drug_unit, drug_type)
        problems: list[str] = []
        charge = Charge(
            item_id=item_id, description=description, codes=codes,
            setting=_enum(cell(row, "setting")), billing_class=_enum(cell(row, "billing_class")),
            modifiers=_blank(cell(row, "modifiers")), drug_unit=drug_unit, drug_type=drug_type,
            gross=_num(cell(row, "standard_charge|gross"), problems, "gross"),
            discounted_cash=_num(cell(row, "standard_charge|discounted_cash"), problems, "discounted_cash"),
            minimum=_num(cell(row, "standard_charge|min"), problems, "min"),
            maximum=_num(cell(row, "standard_charge|max"), problems, "max"),
            notes=_blank(cell(row, "additional_generic_notes")), source_ref=f"row {n}",
            off_template_note="; ".join(problems) or None,
        )
        if shape == "csv-wide":
            yield charge
            continue
        # Tall: one row per payer/plan, summary columns repeated. Emit one charge per
        # distinct (item, setting, billing class, modifiers, summary values); a second
        # row for the same context with *different* summary values is a conflict and is
        # emitted too, so nothing is silently chosen.
        ctx = (charge.setting, charge.billing_class, charge.modifiers, charge.gross, charge.discounted_cash, charge.minimum, charge.maximum)
        contexts = seen.setdefault(item_id, set())
        if ctx in contexts:
            continue
        contexts.add(ctx)
        yield charge


# --- JSON ---------------------------------------------------------------------------------

def read_json_header(prefix: bytes) -> FileHeader:
    """Top-level scalars come before the big array in every file seen so far, so they can
    be read from the first bytes without parsing the whole document."""
    text = prefix.decode("utf-8-sig", errors="replace")

    def scalar(key):
        m = re.search(r'"%s"\s*:\s*"([^"]*)"' % key, text)
        return m.group(1) if m else None

    m = re.search(r'"location_name"\s*:\s*\[([^\]]*)\]', text)
    locations = tuple(re.findall(r'"([^"]*)"', m.group(1))) if m else ()
    if '"standard_charge_information"' not in text and "standard_charge_information" not in text[:200_000]:
        pass  # may simply be further in; the array reader will say if it's missing
    return FileHeader(scalar("hospital_name"), scalar("last_updated_on"), scalar("version"), locations, "json")


def iter_json(stream) -> Iterator[Charge]:
    found = False
    for n, item in enumerate(ijson.items(io.BufferedReader(_SkipBOM(stream), 1 << 20), "standard_charge_information.item", use_float=True), start=1):
        found = True
        description = str(item.get("description") or "").strip()
        codes = tuple(
            (str(c.get("type") or "").strip().upper(), str(c.get("code") or "").strip())
            for c in item.get("code_information") or [] if c.get("code")
        )
        drug = item.get("drug_information") or {}
        drug_unit, drug_type = _blank(drug.get("unit")), _blank(drug.get("type"))
        item_id = _item_id(description, codes, drug_unit, drug_type)
        for k, sc in enumerate(item.get("standard_charges") or [], start=1):
            problems: list[str] = []
            # The dictionary says `modifier_code` (an array); HCA writes `modifiers` (a string).
            mods = sc.get("modifier_code")
            mods = ", ".join(str(m) for m in mods) if isinstance(mods, list) and mods else _blank(mods) or _blank(sc.get("modifiers"))
            yield Charge(
                item_id=item_id, description=description, codes=codes,
                setting=_enum(sc.get("setting")), billing_class=_enum(sc.get("billing_class")),
                modifiers=mods,
                drug_unit=drug_unit, drug_type=drug_type,
                gross=_num(sc.get("gross_charge"), problems, "gross"),
                discounted_cash=_num(sc.get("discounted_cash"), problems, "discounted_cash"),
                minimum=_num(sc.get("minimum"), problems, "min"),
                maximum=_num(sc.get("maximum"), problems, "max"),
                notes=_blank(sc.get("additional_generic_notes")), source_ref=f"item {n}/charge {k}",
                off_template_note="; ".join(problems) or None,
            )
    if not found:
        raise OffTemplate("no standard_charge_information array")


# --- entry point --------------------------------------------------------------------------

def open_mrf(path: str, shape_hint: str | None = None) -> tuple[FileHeader, Iterator[Charge]]:
    """Open a downloaded file (csv, json or a zip holding one of those) as a stream of
    charges. The caller iterates; nothing is read ahead."""
    f = open(path, "rb")
    head = f.read(4)
    f.seek(0)
    if head.startswith(b"PK"):
        f.close()
        return _open_zip(path)
    if head.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"{"):
        prefix = f.read(256_000)
        f.seek(0)
        return read_json_header(prefix), iter_json(f)
    text = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline="")
    return iter_csv(text)


def _open_zip(path: str) -> tuple[FileHeader, Iterator[Charge]]:
    z = zipfile.ZipFile(path)
    members = [m for m in z.infolist() if not m.is_dir() and re.search(r"\.(csv|json)$", m.filename, re.I)]
    if not members:
        raise OffTemplate(f"zip holds no csv/json: {[m.filename for m in z.infolist()][:5]}")
    member = max(members, key=lambda m: m.file_size)
    raw = z.open(member)
    if member.filename.lower().endswith(".json"):
        prefix = raw.read(256_000)
        raw.close()
        raw = z.open(member)
        return read_json_header(prefix), iter_json(raw)
    text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
    return iter_csv(text)
