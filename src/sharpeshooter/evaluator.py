"""Synthetic deterministic metrics, never a strategy backtest or recommendation.

Ranges: annualized return [-.10, .30], volatility [.08, .40], drawdown
[-.65, -.05]. Sharpe uses a fixed .06 risk-free rate. Each evaluation uses
its own SHA-256-seeded generator and verifies the selected private split.
"""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import random
import re
from typing import Any, Literal, Protocol

from .data_prep import _SCHEMAS, _UNIVERSE_SCHEMA, _canonical, _file_payload, _inspect, _schema


@dataclass(frozen=True)
class EvaluationRequest:
    run_id: str
    idea_id: str
    family_id: str
    operator_id: str
    split: Literal["is", "oos"]
    strategy_spec: dict[str, Any]
    strategy_hash: str
    dataset_version: str
    dataset_split_hash: str


@dataclass(frozen=True)
class EvaluationResult:
    metrics: dict[str, int | float]
    checks: dict[str, str | int | bool]
    evaluator_name: str
    evaluator_version: str
    synthetic_metrics: bool


class Evaluator(Protocol):
    def evaluate(self, request: EvaluationRequest) -> EvaluationResult: ...


class EvaluatorFailure(Exception):
    """A deliberately fixed error: private paths/contents never reach callers."""
    def __init__(self):
        super().__init__("Synthetic evaluation could not validate the selected split")


_EXPECTED = _SCHEMAS | {"universe.parquet": _UNIVERSE_SCHEMA}
_HASH = r"sha256:[0-9a-f]{64}"
_PANDAS_METADATA_KEYS = {
    "attributes",
    "column_indexes",
    "columns",
    "creator",
    "index_columns",
    "pandas_version",
}


def _supported_schema_metadata(actual, expected) -> bool:
    if actual.metadata == expected.metadata:
        return all(a.metadata == e.metadata for a, e in zip(actual, expected))
    if any(a.metadata != e.metadata for a, e in zip(actual, expected)):
        return False
    metadata = actual.metadata
    if not isinstance(metadata, dict) or set(metadata) != {b"pandas"}:
        return False
    raw = metadata[b"pandas"]
    if not isinstance(raw, bytes) or len(raw) > 16_384:
        return False
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or set(payload) != _PANDAS_METADATA_KEYS:
        return False
    if payload["index_columns"] != [] or payload["column_indexes"] != [] or payload["attributes"] != {}:
        return False
    creator = payload["creator"]
    if (
        not isinstance(creator, dict)
        or set(creator) != {"library", "version"}
        or any(not isinstance(creator[key], str) or not creator[key] or len(creator[key]) > 128 for key in creator)
        or not isinstance(payload["pandas_version"], str)
        or not payload["pandas_version"]
        or len(payload["pandas_version"]) > 128
    ):
        return False
    columns = payload["columns"]
    if not isinstance(columns, list) or len(columns) != len(expected):
        return False
    for field, column in zip(expected, columns):
        if not isinstance(column, dict) or set(column) != {
            "field_name",
            "metadata",
            "name",
            "numpy_type",
            "pandas_type",
        }:
            return False
        if column["field_name"] != field.name or column["name"] != field.name or column["metadata"] is not None:
            return False
        for key in ("numpy_type", "pandas_type"):
            if not isinstance(column[key], str) or not column[key] or len(column[key]) > 128:
                return False
    return True


def _regular_under(root: Path, name: str) -> Path:
    path = root / name
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Invalid split file")
    return path


def selected_manifest(root: Path, split: str) -> dict:
    """Read only service-selected metadata. File contents are checked at evaluation."""
    try:
        if split not in ("is", "oos"):
            raise ValueError("Invalid split")
        payload = json.loads(_regular_under(root, "manifest.json").read_text(encoding="utf-8"))
        if set(payload) != {"dataset_version", "acceptance", "name", "start", "end", "files", "split_hash"}:
            raise ValueError("Invalid manifest")
        if not isinstance(payload["dataset_version"], str) or not payload["dataset_version"].strip():
            raise ValueError("Invalid version")
        if payload["acceptance"] != "pending" or payload["name"] != split:
            raise ValueError("Invalid manifest identity")
        if date.fromisoformat(payload["start"]) > date.fromisoformat(payload["end"]):
            raise ValueError("Invalid dates")
        if set(payload["files"]) != set(_EXPECTED):
            raise ValueError("Invalid files")
        for info in payload["files"].values():
            if set(info) != {"sha256", "row_count", "date_field", "date_min", "date_max"}:
                raise ValueError("Invalid file metadata")
            if not isinstance(info["sha256"], str) or not re.fullmatch(_HASH, info["sha256"]):
                raise ValueError("Invalid digest")
            if type(info["row_count"]) is not int or info["row_count"] < 0:
                raise ValueError("Invalid row count")
            for bound in ("date_min", "date_max"):
                if info[bound] is not None:
                    date.fromisoformat(info[bound])
        unhashed = {key: value for key, value in payload.items() if key != "split_hash"}
        if payload["split_hash"] != "sha256:" + hashlib.sha256(_canonical(unhashed)).hexdigest():
            raise ValueError("Invalid split digest")
        return payload
    except Exception:
        raise EvaluatorFailure() from None


class DeterministicStubEvaluator:
    def __init__(self, *, is_root, oos_root):
        self.is_root, self.oos_root = Path(is_root), Path(oos_root)

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        try:
            if request.split not in ("is", "oos"):
                raise ValueError("Invalid split")
            root = self.is_root if request.split == "is" else self.oos_root
            manifest = selected_manifest(root, request.split)
            if (request.dataset_version != manifest["dataset_version"] or
                    request.dataset_split_hash != manifest["split_hash"]):
                raise ValueError("Dataset identity mismatch")
            for name, schema in _EXPECTED.items():
                path = _regular_under(root, name)
                actual = _schema(path, schema)
                if not _supported_schema_metadata(actual, schema):
                    raise ValueError("Schema metadata mismatch")
                entry = _inspect(path, actual,
                                 date.fromisoformat(manifest["start"]), date.fromisoformat(manifest["end"]), request.split)
                if _file_payload(entry) != manifest["files"][name]:
                    raise ValueError("File metadata mismatch")
            calendar = manifest["files"]["calendar.parquet"]
            if not calendar["row_count"] or calendar["date_min"] is None or calendar["date_max"] is None:
                raise ValueError("Calendar has no observations")
            seed = hashlib.sha256((request.strategy_hash + "|" + request.dataset_split_hash + "|" + request.split).encode()).digest()
            generator = random.Random(seed)
            annual_return = round(generator.uniform(-.10, .30), 8)
            volatility = round(generator.uniform(.08, .40), 8)
            metrics = dict(annualized_return=annual_return, annualized_volatility=volatility,
                           sharpe_ratio=round((annual_return - .06) / volatility, 8),
                           max_drawdown=round(generator.uniform(-.65, -.05), 8), observations=calendar["row_count"])
            checks = dict(opened_split=request.split, dataset_version=manifest["dataset_version"],
                          acceptance=manifest["acceptance"], dataset_split_hash=manifest["split_hash"], date_min=calendar["date_min"],
                          date_max=calendar["date_max"], observations=calendar["row_count"], synthetic_metrics=True)
            return EvaluationResult(metrics, checks, "deterministic_synthetic_stub", "1", True)
        except Exception:
            raise EvaluatorFailure() from None
