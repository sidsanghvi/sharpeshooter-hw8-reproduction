"""Deterministic, fixture-testable point-in-time Parquet split preparation.

This module does not choose storage mounts or grant access to data. The caller
must supply an OOS destination inside the service-only volume for real staging.
"""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


class DataPrepError(Exception):
    """A safe rule/file-level preparation failure, without source row contents."""


@dataclass(frozen=True)
class FileManifest:
    filename: str
    sha256: str
    row_count: int
    date_field: str
    date_min: date | None
    date_max: date | None


@dataclass(frozen=True)
class SplitDetails:
    name: str
    start: date
    end: date
    files: tuple[FileManifest, ...]
    split_hash: str


@dataclass(frozen=True)
class SplitManifest:
    dataset_version: str
    acceptance: str
    is_split: SplitDetails
    oos_split: SplitDetails
    public_manifest_path: Path


_SCHEMAS = {
    "ohlcv.parquet": pa.schema([
        ("internal_id", pa.string()), ("date", pa.date32()),
        *[(name, pa.float64()) for name in ("open", "high", "low", "close")],
        ("volume", pa.int64()), ("adj_factor", pa.float64()),
        *[(name, pa.float64()) for name in ("open_adj", "high_adj", "low_adj", "close_adj")],
    ]),
    "symbols.parquet": pa.schema([
        ("internal_id", pa.string()), ("ticker", pa.string()), ("name", pa.null()),
        ("valid_from", pa.date32()), ("valid_to", pa.date32()),
        ("isin", pa.string()), ("kind", pa.string()),
    ]),
    "market_cap.parquet": pa.schema([
        ("internal_id", pa.string()), ("date", pa.date32()),
        ("market_cap", pa.float64()), ("basis", pa.string()),
    ]),
    "corporate_actions.parquet": pa.schema([
        ("internal_id", pa.string()), ("ex_date", pa.date32()),
        ("action_type", pa.string()), ("ratio_or_terms", pa.string()),
        ("factor", pa.float64()), ("source", pa.string()), ("notes", pa.string()),
    ]),
    "delistings.parquet": pa.schema([
        ("internal_id", pa.string()), ("event_date", pa.date32()),
        ("event_type", pa.string()), ("terms_text", pa.string()),
        ("last_traded_price", pa.float64()),
    ]),
    "calendar.parquet": pa.schema([
        ("date", pa.date32()), ("session_type", pa.string()), ("note", pa.string()),
    ]),
    "benchmarks.parquet": pa.schema([
        ("benchmark_id", pa.string()), ("date", pa.date32()),
        ("close_level", pa.float64()), ("variant", pa.string()),
    ]),
}
_UNIVERSE_SCHEMA = pa.schema([
    pa.field("internal_id", pa.string(), nullable=False),
    pa.field("valid_from", pa.date32(), nullable=False),
    pa.field("valid_to", pa.date32(), nullable=False),
    pa.field("rank", pa.int64()),
    pa.field("selection_rule", pa.string(), nullable=False),
    pa.field("rebalance_date", pa.date32()),
])
_DATE_FIELDS = {name: "date" for name in _SCHEMAS} | {
    "symbols.parquet": "valid_from", "corporate_actions.parquet": "ex_date",
    "delistings.parquet": "event_date", "universe.parquet": "valid_from",
}
_ALL_ELIGIBLE_START = date(2009, 1, 1)


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return "sha256:" + hasher.hexdigest()


def _source_manifest(source: Path) -> dict:
    try:
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError
        canonical_keys = {"version", "created", "acceptance"}
        real_keys = {"version_id", "created_date", "serving_notes"}
        is_canonical = bool(canonical_keys & manifest.keys())
        is_real = bool(real_keys & manifest.keys())
        if is_canonical == is_real:
            raise ValueError

        if is_canonical:
            version = manifest.get("version")
            created = manifest.get("created")
            acceptance = manifest.get("acceptance")
            files = manifest.get("files")
            if acceptance != "pending" or not isinstance(files, dict):
                raise ValueError
        else:
            version = manifest.get("version_id")
            created = manifest.get("created_date")
            serving_notes = manifest.get("serving_notes")
            acceptance = serving_notes.get("acceptance") if isinstance(serving_notes, dict) else None
            entries = manifest.get("files")
            if not isinstance(acceptance, str) or not acceptance.startswith("pending") or not isinstance(entries, list):
                raise ValueError
            files = {}
            for entry in entries:
                name = entry.get("filename") if isinstance(entry, dict) else None
                if not isinstance(name, str) or name in files:
                    raise ValueError
                files[name] = entry
            manifest = {"version": version, "created": created, "acceptance": "pending", "files": files}

        if not isinstance(version, str) or not version.strip():
            raise ValueError
        if not isinstance(created, str):
            raise ValueError
        date.fromisoformat(created)
        if set(files) != set(_SCHEMAS):
            raise ValueError
        expected = {}
        for name in sorted(_SCHEMAS):
            entry = files[name]
            value = entry.get("sha256") if isinstance(entry, dict) else None
            if not isinstance(value, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value):
                raise DataPrepError(f"{name}: invalid source digest")
            expected[name] = value.removeprefix("sha256:")
    except (OSError, ValueError, TypeError, KeyError):
        raise DataPrepError("manifest.json: invalid source metadata") from None
    # No Parquet open, output directory, or staging allocation precedes this loop.
    for name in sorted(_SCHEMAS):
        try:
            actual = _digest(source / name)
        except OSError:
            raise DataPrepError(f"{name}: source digest unreadable") from None
        if actual != "sha256:" + expected[name]:
            raise DataPrepError(f"{name}: source digest mismatch")
    return manifest


def _schema(path: Path, expected: pa.Schema) -> pa.Schema:
    actual = pq.read_schema(path)
    # Stronger source nullability is compatible except where derivation must
    # introduce nulls. IS symbol censoring requires a nullable valid_to field.
    if actual.names != expected.names or any(a.type != e.type for a, e in zip(actual, expected)):
        raise DataPrepError(f"{path.name}: physical schema mismatch")
    if any(not e.nullable and a.nullable for a, e in zip(actual, expected)):
        raise DataPrepError(f"{path.name}: nullability mismatch")
    if path.name == "symbols.parquet" and not actual.field("valid_to").nullable:
        raise DataPrepError("symbols.parquet: valid_to must be nullable for IS censoring")
    return actual


def _range(field: str, start: date, end: date):
    return (ds.field(field) >= pa.scalar(start)) & (ds.field(field) <= pa.scalar(end))


def _batches(path: Path, expression=None, columns=None):
    return ds.dataset(path, format="parquet").scanner(
        filter=expression, columns=columns, batch_size=65_536, use_threads=False,
    ).to_batches()


def _rows(path: Path, expression=None, columns=None):
    for batch in _batches(path, expression, columns):
        yield from batch.to_pylist()


def _overlap(start: date, end: date):
    return (ds.field("valid_from") <= pa.scalar(end)) & (
        ds.field("valid_to").is_null() | (ds.field("valid_to") >= pa.scalar(start))
    )


def _write_filtered(source: Path, stage: Path, schemas: dict, name: str, start: date, end: date, split: str):
    schema = schemas[name]
    expression = _overlap(start, end) if name == "symbols.parquet" else _range(_DATE_FIELDS[name], start, end)
    with pq.ParquetWriter(stage / name, schema, compression="zstd") as writer:
        for batch in _batches(source / name, expression):
            if name == "symbols.parquet" and split == "is":
                index = schema.get_field_index("valid_to")
                values = batch.column(index)
                censored = pc.if_else(pc.greater(values, pa.scalar(end)), pa.scalar(None, pa.date32()), values)
                batch = batch.set_column(index, schema.field(index), censored)
            writer.write_batch(batch)


def _next_quarter(start: date) -> date:
    return date(start.year + 1, 1, 1) if start.month == 10 else date(start.year, start.month + 3, 1)


def _first_regular(source: Path, quarter: date) -> date:
    sessions = [row["date"] for row in _rows(
        source / "calendar.parquet",
        _range("date", quarter, _next_quarter(quarter) - timedelta(days=1)) & (ds.field("session_type") == "regular"),
        ["date"],
    )]
    if not sessions:
        raise DataPrepError("calendar.parquet: quarter has no regular rebalance session")
    return min(sessions)


def _certified_top250(source: Path, rebalance: date) -> list[str]:
    adjusted = ("open_adj", "high_adj", "low_adj", "close_adj")
    price_ids = set()
    expression = ds.field("date") == pa.scalar(rebalance)
    for row in _rows(source / "ohlcv.parquet", expression, ["internal_id", *adjusted]):
        if row["internal_id"] is not None and all(row[key] is not None and math.isfinite(row[key]) for key in adjusted):
            price_ids.add(row["internal_id"])
    caps = {}
    for row in _rows(source / "market_cap.parquet", expression, ["internal_id", "basis", "market_cap"]):
        ident, value = row["internal_id"], row["market_cap"]
        if ident in price_ids and row["basis"] == "full" and value is not None and math.isfinite(value) and value > 0:
            if ident in caps:
                raise DataPrepError("market_cap.parquet: duplicate certified identity at rebalance")
            caps[ident] = value
    if len(caps) < 300:
        raise DataPrepError("universe.parquet: rebalance requires 300 distinct certified candidates")
    return sorted(caps, key=lambda ident: (-caps[ident], ident))[:250]


def _universe(source: Path, start: date, end: date) -> pa.Table:
    result = []
    early_start, early_end = max(start, date(2006, 1, 1)), min(end, date(2008, 12, 31))
    if early_start <= early_end:
        quarter = date(early_start.year, 3 * ((early_start.month - 1) // 3) + 1, 1)
        first_quarter = quarter
        rebalances = []
        while quarter <= early_end:
            rebalances.append(_first_regular(source, quarter))
            quarter = _next_quarter(quarter)
        if rebalances[0] > early_start and first_quarter > date(2006, 1, 1):
            previous_day = first_quarter - timedelta(days=1)
            previous_quarter = date(previous_day.year, 3 * ((previous_day.month - 1) // 3) + 1, 1)
            rebalances.insert(0, _first_regular(source, previous_quarter))
        for index, rebalance in enumerate(rebalances):
            until = min(early_end, rebalances[index + 1] - timedelta(days=1)) if index + 1 < len(rebalances) else early_end
            beginning = max(early_start, rebalance)
            if beginning <= until:
                members = _certified_top250(source, rebalance)
                for rank, ident in enumerate(members, 1):
                    result.append(dict(internal_id=ident, valid_from=beginning, valid_to=until,
                                       rank=rank, selection_rule="quarterly_top_250_full_market_cap", rebalance_date=rebalance))
    later_start = max(start, _ALL_ELIGIBLE_START)
    if later_start <= end:
        intervals = {}
        for row in _rows(source / "symbols.parquet", _overlap(later_start, end), ["internal_id", "valid_from", "valid_to"]):
            if row["internal_id"] is None or row["valid_from"] is None:
                raise DataPrepError("symbols.parquet: invalid identity interval")
            beginning, until = max(later_start, row["valid_from"]), min(end, row["valid_to"] or end)
            intervals.setdefault(row["internal_id"], []).append((beginning, until))
        for ident, spans in intervals.items():
            merged = []
            for beginning, until in sorted(spans):
                # Difference arithmetic avoids overflowing date.max on open spans.
                if merged and (beginning - merged[-1][1]).days <= 1:
                    merged[-1] = (merged[-1][0], max(until, merged[-1][1]))
                else:
                    merged.append((beginning, until))
            for beginning, until in merged:
                result.append(dict(internal_id=ident, valid_from=beginning, valid_to=until,
                                   rank=None, selection_rule="all_eligible", rebalance_date=None))
    result.sort(key=lambda row: (row["valid_from"], row["rank"] is None, row["rank"] or 0, row["internal_id"]))
    return pa.Table.from_pylist(result, schema=_UNIVERSE_SCHEMA)


def _inspect(path: Path, expected: pa.Schema, start: date, end: date, split: str) -> FileManifest:
    actual = _schema(path, expected)
    if not actual.equals(expected, check_metadata=True):
        raise DataPrepError(f"{path.name}: staged schema changed")
    field = _DATE_FIELDS[path.name]
    count, lower, upper = 0, None, None
    for batch in _batches(path):
        count += batch.num_rows
        for index, column in enumerate(batch.columns):
            if not actual.field(index).nullable and column.null_count:
                raise DataPrepError(f"{path.name}: non-nullable field contains null")
        dates = batch.column(actual.get_field_index(field))
        bounds = pc.min_max(dates).as_py()
        if bounds["min"] is not None:
            lower = min(lower, bounds["min"]) if lower else bounds["min"]
            upper = max(upper, bounds["max"]) if upper else bounds["max"]
        if path.name == "symbols.parquet":
            for row in batch.to_pylist():
                if row["valid_from"] is None or row["valid_from"] > end or (row["valid_to"] is not None and row["valid_to"] < start):
                    raise DataPrepError("symbols.parquet: staged interval outside split")
                if split == "is" and row["valid_to"] is not None and row["valid_to"] > end:
                    raise DataPrepError("symbols.parquet: IS cutoff uncensored")
        elif dates.null_count or (bounds["min"] is not None and (bounds["min"] < start or bounds["max"] > end)):
            raise DataPrepError(f"{path.name}: staged date outside split")
        if path.name == "universe.parquet":
            for row in batch.to_pylist():
                if not row["valid_from"] <= row["valid_to"] <= end:
                    raise DataPrepError("universe.parquet: invalid staged interval")
    return FileManifest(path.name, _digest(path), count, field, lower, upper)


def _file_payload(entry: FileManifest) -> dict:
    payload = asdict(entry)
    payload.pop("filename")
    for field in ("date_min", "date_max"):
        payload[field] = payload[field].isoformat() if payload[field] is not None else None
    return payload


def _split_payload(version: str, details: SplitDetails) -> dict:
    return dict(dataset_version=version, acceptance="pending", name=details.name,
                start=details.start.isoformat(), end=details.end.isoformat(),
                files={entry.filename: _file_payload(entry) for entry in details.files})


def _stage(source: Path, stage: Path, schemas: dict, version: str, split: str, start: date, end: date) -> SplitDetails:
    for name in sorted(schemas):
        _write_filtered(source, stage, schemas, name, start, end, split)
    pq.write_table(_universe(source, start, end), stage / "universe.parquet", compression="zstd")
    expected = schemas | {"universe.parquet": _UNIVERSE_SCHEMA}
    files = tuple(_inspect(stage / name, expected[name], start, end, split) for name in sorted(expected))
    details = SplitDetails(split, start, end, files, "")
    payload = _split_payload(version, details)
    split_hash = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    details = SplitDetails(split, start, end, files, split_hash)
    (stage / "manifest.json").write_bytes(_canonical(payload | {"split_hash": split_hash}))
    return details


def _validate(stage: Path, schemas: dict, version: str, details: SplitDetails):
    expected = schemas | {"universe.parquet": _UNIVERSE_SCHEMA}
    files = tuple(_inspect(stage / name, expected[name], details.start, details.end, details.name) for name in sorted(expected))
    if files != details.files:
        raise DataPrepError("manifest.json: staged file metadata changed")
    payload = _split_payload(version, details)
    split_hash = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    if split_hash != details.split_hash or json.loads((stage / "manifest.json").read_text()) != payload | {"split_hash": split_hash}:
        raise DataPrepError("manifest.json: staged split manifest mismatch")


def _public(details: SplitDetails) -> dict:
    return dict(split_hash=details.split_hash, start=details.start.isoformat(), end=details.end.isoformat(),
                row_counts={entry.filename: entry.row_count for entry in details.files})


def prepare_data(
    source_dir: Path, is_output_dir: Path, oos_output_dir: Path,
    is_start: date, is_end: date, oos_start: date, oos_end: date,
) -> SplitManifest:
    """Verify, stage, validate, and publish two inclusive point-in-time splits."""
    stages, published = [], []
    public_temp = None
    try:
        try:
            source, is_output, oos_output = (Path(path).resolve() for path in (source_dir, is_output_dir, oos_output_dir))
            public_path = is_output.parent / "split_manifest.json"
            is_stage = is_output.parent / ".staging-is"
            if is_stage.exists() or is_stage.is_symlink():
                raise DataPrepError("IS staging path: entry already exists")
            oos_stage = oos_output.parent / ".staging-oos"
            if oos_stage.exists() or oos_stage.is_symlink():
                oos_stage = oos_output.parent / f".staging-oos-{uuid4().hex}"
            planned_stages = (is_stage.resolve(), oos_stage.resolve())
            paths = (source, is_output, oos_output, public_path.resolve(), *planned_stages)
        except (OSError, RuntimeError, TypeError, ValueError):
            raise DataPrepError("source/output path: cannot resolve safely") from None
        # Destinations and stages must all be disjoint, including their resolved
        # aliases. Otherwise a directory rename can move hidden OOS into IS.
        for index, path in enumerate(paths):
            for other in paths[index + 1:]:
                if path == other or path.is_relative_to(other) or other.is_relative_to(path):
                    raise DataPrepError("source/output/public/staging paths: overlap forbidden")
        if any(type(value) is not date for value in (is_start, is_end, oos_start, oos_end)) or not is_start < is_end < oos_start < oos_end:
            raise DataPrepError("split windows: require increasing non-overlapping dates")
        if is_start < date(2006, 1, 1):
            raise DataPrepError("split windows: universe begins 2006-01-01")
        if is_output.exists() or oos_output.exists():
            raise DataPrepError("output path: final split already exists")
        manifest = _source_manifest(source)
        schemas = {name: _schema(source / name, expected) for name, expected in _SCHEMAS.items()}
        version = manifest["version"]
        for stage in planned_stages:
            stage.parent.mkdir(parents=True, exist_ok=True)
            stage.mkdir()  # Exclusive creation; existing paths are never removed.
            stages.append(stage)
        is_details = _stage(source, stages[0], schemas, version, "is", is_start, is_end)
        oos_details = _stage(source, stages[1], schemas, version, "oos", oos_start, oos_end)
        _validate(stages[0], schemas, version, is_details)
        _validate(stages[1], schemas, version, oos_details)
        for stage, output in zip(stages, (is_output, oos_output)):
            if output.exists():
                raise DataPrepError("output path: final split appeared during staging")
            stage.rename(output)
            published.append(output)
        public_payload = dict(dataset_version=version, acceptance="pending",
                              **{"is": _public(is_details), "oos": _public(oos_details)})
        with tempfile.NamedTemporaryFile(prefix=".split-manifest-", dir=public_path.parent, delete=False) as stream:
            public_temp = Path(stream.name)
            stream.write(_canonical(public_payload))
        public_temp.replace(public_path)
        return SplitManifest(version, "pending", is_details, oos_details, public_path)
    except DataPrepError:
        for output in published:
            shutil.rmtree(output)
        raise
    except (OSError, pa.ArrowException, ValueError, TypeError, OverflowError):
        for output in published:
            shutil.rmtree(output)
        raise DataPrepError("data preparation: source, staging, or publication failed") from None
    finally:
        for stage in stages:
            if stage.exists():
                shutil.rmtree(stage)
        if public_temp is not None:
            public_temp.unlink(missing_ok=True)


def main(argv=None):
    """One-time operator staging entrypoint; never invoked by agent tools."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Verify and stage point-in-time splits")
    parser.add_argument("--source", type=Path, default=Path("/source"))
    parser.add_argument("--is-output", type=Path, default=Path("/is-data/is"))
    parser.add_argument("--oos-output", type=Path, default=Path("/data/oos"))
    for flag in ("is-start", "is-end", "oos-start", "oos-end"):
        parser.add_argument("--" + flag, type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_data(args.source, args.is_output, args.oos_output,
                              args.is_start, args.is_end, args.oos_start, args.oos_end)
    except DataPrepError as exc:
        print(json.dumps({"error": "DATA_PREP_FAILED", "message": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"dataset_version": result.dataset_version, "acceptance": result.acceptance,
                      "is_split_hash": result.is_split.split_hash, "oos_split_hash": result.oos_split.split_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
