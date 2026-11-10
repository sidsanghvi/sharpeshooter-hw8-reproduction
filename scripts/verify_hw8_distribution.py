#!/usr/bin/env python3
"""Fail-closed inventory verification for projected HW8 release artifacts."""
from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import zipfile


ENTRY_POINTS = {
    "builder": "agents.builder:main", "scout": "agents.scout:main",
    "skeptic": "agents.skeptic:main", "sharpeshooter-admin": "sharpeshooter.operator_cli:main",
    "sharpeshooter-task": "sharpeshooter.task_cli:main",
}
POLICY_VERSION = 1
SDIST_ROOT = "sharpeshooter-0.1.0"
DIST_INFO = "sharpeshooter-0.1.0.dist-info"
TOP_LEVEL_FIELDS = {
    "schema_version", "projection_policy_version", "ingress_commit",
    "pyproject_sha256", "files",
}
FILE_FIELDS = {"path", "source", "size", "sha256"}
DECLARED_FILES = {
    "pyproject.toml", "uv.lock", "README.md", "docs/architecture.md",
    "scripts/demo.py", "scripts/verify_receipt.py",
    "scripts/verify_hw8_distribution.py", "scripts/smoke_hw8_wheel.py",
    "tasks/hw8/HW8_CONTRACT.md", "tasks/hw8/fixtures/research-task-v1.json",
}
DECLARED_TREES = ("src/sharpeshooter/", "agents/")
EXPECTED_PROJECTED_PATHS = DECLARED_FILES | {
    "agents/__init__.py",
    "agents/builder.py",
    "agents/common.py",
    "agents/memory_templates/builder.md",
    "agents/memory_templates/scout.md",
    "agents/memory_templates/skeptic.md",
    "agents/prompts/builder.txt",
    "agents/prompts/scout.txt",
    "agents/prompts/skeptic.txt",
    "agents/schemas/builder.json",
    "agents/schemas/scout.json",
    "agents/schemas/skeptic.json",
    "agents/scout.py",
    "agents/skeptic.py",
    "agents/workflow_policy.py",
    "src/sharpeshooter/__init__.py",
    "src/sharpeshooter/auth.py",
    "src/sharpeshooter/config.py",
    "src/sharpeshooter/data_prep.py",
    "src/sharpeshooter/db.py",
    "src/sharpeshooter/domain.py",
    "src/sharpeshooter/errors.py",
    "src/sharpeshooter/evaluator.py",
    "src/sharpeshooter/http_app.py",
    "src/sharpeshooter/ledger.py",
    "src/sharpeshooter/mcp_server.py",
    "src/sharpeshooter/operator_cli.py",
    "src/sharpeshooter/receipts.py",
    "src/sharpeshooter/research_task.py",
    "src/sharpeshooter/schema.sql",
    "src/sharpeshooter/task_cli.py",
    "src/sharpeshooter/task_runner.py",
}
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_METADATA = (
    b"Metadata-Version: 2.5\nName: sharpeshooter\nVersion: 0.1.0\n"
    b"Summary: Deterministic shared research ledger\nRequires-Python: >=3.11\n"
    b"Requires-Dist: fastapi<1,>=0.115\nRequires-Dist: jsonschema<5,>=4\n"
    b"Requires-Dist: mcp<3,>=2\nRequires-Dist: pyarrow==22.0.0\n"
    b"Requires-Dist: uvicorn<1,>=0.30\nProvides-Extra: test\n"
    b"Requires-Dist: pytest<9,>=8; extra == 'test'\n"
)
EXPECTED_WHEEL = (
    b"Wheel-Version: 1.0\nGenerator: hatchling 1.33.0\n"
    b"Root-Is-Purelib: true\nTag: py3-none-any\n"
)
EXPECTED_ENTRY_POINTS = (
    b"[console_scripts]\n"
    b"builder = agents.builder:main\n"
    b"scout = agents.scout:main\n"
    b"sharpeshooter-admin = sharpeshooter.operator_cli:main\n"
    b"sharpeshooter-task = sharpeshooter.task_cli:main\n"
    b"skeptic = agents.skeptic:main\n"
)
FORBIDDEN_WHEEL = ("benchmarks/", "tasks/", "runtime/", "evidence/", "hw6", "hw7", ".git/")
FORBIDDEN_SOURCE = ("benchmarks/", "runtime/", "evidence/", "tasks/hw6/", "tasks/hw7/", ".git/")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("unsafe archive member")
    return path


def load_manifest(path: Path) -> dict:
    raw = path.read_bytes()
    value = json.loads(raw)
    if raw != json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"):
        raise ValueError("projection manifest is not canonical")
    if not isinstance(value, dict) or set(value) != TOP_LEVEL_FIELDS:
        raise ValueError("projection manifest fields are invalid")
    if value.get("schema_version") != "sharpeshooter.hw8-projection.v1":
        raise ValueError("projection manifest version mismatch")
    if type(value["projection_policy_version"]) is not int or value["projection_policy_version"] != POLICY_VERSION:
        raise ValueError("projection policy version mismatch")
    if not isinstance(value["ingress_commit"], str) or COMMIT_PATTERN.fullmatch(value["ingress_commit"]) is None:
        raise ValueError("projection ingress commit is invalid")
    if not isinstance(value["pyproject_sha256"], str) or SHA256_PATTERN.fullmatch(value["pyproject_sha256"]) is None:
        raise ValueError("projection pyproject digest is invalid")
    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("projection manifest has no files")
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != FILE_FIELDS:
            raise ValueError("projection manifest entry is invalid")
        relative = entry["path"]
        if not isinstance(relative, str) or not isinstance(entry["source"], str):
            raise ValueError("projection manifest path is invalid")
        safe_member(relative)
        if (
            entry["source"] != relative
            or not (relative in DECLARED_FILES or relative.startswith(DECLARED_TREES))
            or "__pycache__" in PurePosixPath(relative).parts
            or PurePosixPath(relative).suffix in (".pyc", ".pyo")
            or type(entry["size"]) is not int
            or entry["size"] < 0
            or not isinstance(entry["sha256"], str)
            or SHA256_PATTERN.fullmatch(entry["sha256"]) is None
        ):
            raise ValueError("projection manifest entry is invalid")
    paths = [entry["path"] for entry in files]
    if paths != sorted(paths, key=lambda item: item.encode()) or len(paths) != len(set(paths)):
        raise ValueError("projection manifest paths are not unique and sorted")
    if set(paths) != EXPECTED_PROJECTED_PATHS:
        raise ValueError("projection manifest declared inventory is not exact")
    pyproject = next(entry for entry in files if entry["path"] == "pyproject.toml")
    if pyproject["sha256"] != value["pyproject_sha256"]:
        raise ValueError("projection pyproject digest mismatch")
    return value


def _content_details(data: bytes) -> dict:
    return {"size": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}


def verify_source(path: Path, manifest: dict, manifest_path: Path) -> dict[str, bytes]:
    required = {entry["path"]: entry for entry in manifest["files"]}
    generated = {
        "hw8-projection-manifest.json": manifest_path.read_bytes(),
        "PKG-INFO": EXPECTED_METADATA,
    }
    expected = {*required, *generated}
    with tarfile.open(path, "r:*") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError("source archive contains duplicate members")
        observed = {}
        for member in members:
            parsed = safe_member(member.name)
            if len(parsed.parts) < 2 or parsed.parts[0] != SDIST_ROOT:
                raise ValueError("source archive root is missing")
            member_relative = PurePosixPath(*parsed.parts[1:]).as_posix()
            if any(value in member_relative.lower() for value in FORBIDDEN_SOURCE):
                raise ValueError("forbidden source archive member")
            if not member.isfile():
                raise ValueError("unsafe source archive member type")
            if member_relative not in expected:
                raise ValueError("source archive has an unexpected member")
            expected_size = required.get(member_relative, {}).get(
                "size", len(generated.get(member_relative, b""))
            )
            if member.size != expected_size:
                raise ValueError("source archive member size mismatch")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError("source archive member is unreadable")
            observed[member_relative] = extracted.read()
        if set(observed) != expected:
            raise ValueError("source archive inventory differs from projection")
        for relative, entry in required.items():
            if _content_details(observed[relative]) != {
                "size": entry["size"], "sha256": entry["sha256"]
            }:
                raise ValueError("source archive differs from projection manifest")
        for relative, data in generated.items():
            if observed[relative] != data:
                raise ValueError("source archive generated metadata is invalid")
    return observed


def _wheel_project_files(manifest: dict) -> dict[str, dict]:
    result = {}
    for entry in manifest["files"]:
        relative = entry["path"]
        if relative.startswith("src/sharpeshooter/"):
            wheel_name = relative.removeprefix("src/")
        elif relative.startswith("agents/"):
            wheel_name = relative
        else:
            continue
        if wheel_name in result:
            raise ValueError("wheel projection contains a collision")
        result[wheel_name] = entry
    return result


def _expected_record(names: list[str], contents: dict[str, bytes]) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    record_name = f"{DIST_INFO}/RECORD"
    for name in names:
        if name == record_name:
            continue
        data = contents[name]
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + encoded, len(data)))
    writer.writerow((record_name, "", ""))
    return output.getvalue().encode("utf-8")


def verify_wheel(path: Path, manifest: dict, source_contents: dict[str, bytes]) -> None:
    projected = _wheel_project_files(manifest)
    generated = {
        f"{DIST_INFO}/METADATA": EXPECTED_METADATA,
        f"{DIST_INFO}/WHEEL": EXPECTED_WHEEL,
        f"{DIST_INFO}/entry_points.txt": EXPECTED_ENTRY_POINTS,
    }
    record_name = f"{DIST_INFO}/RECORD"
    expected = {*projected, *generated, record_name}
    with zipfile.ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if len(infos) != len(archive.infolist()) or len(names) != len(set(names)):
            raise ValueError("wheel contains duplicate or directory members")
        for info in infos:
            member_type = (info.external_attr >> 16) & 0o170000
            if member_type not in (0, stat.S_IFREG):
                raise ValueError("wheel member type is invalid")
            safe_member(info.filename)
        if any(value in name.lower() for name in names for value in FORBIDDEN_WHEEL):
            raise ValueError("forbidden wheel member")
        if set(names) != expected:
            raise ValueError("wheel inventory differs from projection")
        contents = {}
        for info in infos:
            if info.filename in projected and info.file_size != projected[info.filename]["size"]:
                raise ValueError("wheel projected member size mismatch")
            contents[info.filename] = archive.read(info)
        for name, entry in projected.items():
            if _content_details(contents[name]) != {
                "size": entry["size"], "sha256": entry["sha256"]
            }:
                raise ValueError("wheel member differs from projection manifest")
            source_name = "src/" + name if name.startswith("sharpeshooter/") else name
            if contents[name] != source_contents[source_name]:
                raise ValueError("wheel member differs from source archive")
        for name, data in generated.items():
            if contents[name] != data:
                raise ValueError("wheel generated metadata is invalid")
        if contents[f"{DIST_INFO}/METADATA"] != source_contents["PKG-INFO"]:
            raise ValueError("wheel and source metadata differ")
        if contents[record_name] != _expected_record(names, contents):
            raise ValueError("wheel RECORD is invalid")
        parser = configparser.ConfigParser()
        parser.read_file(StringIO(contents[f"{DIST_INFO}/entry_points.txt"].decode("utf-8")))
        if dict(parser["console_scripts"]) != ENTRY_POINTS:
            raise ValueError("wheel entry points are invalid")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-manifest", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.projection_manifest)
        source_contents = verify_source(args.source_archive, manifest, args.projection_manifest)
        verify_wheel(args.wheel, manifest, source_contents)
        print(json.dumps({
            "projection_manifest_sha256": digest(args.projection_manifest),
            "source_archive_sha256": digest(args.source_archive),
            "wheel_sha256": digest(args.wheel),
        }, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tarfile.TarError, zipfile.BadZipFile):
        print("HW8 distribution verification failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
