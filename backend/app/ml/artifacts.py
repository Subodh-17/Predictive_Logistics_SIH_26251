"""Safe artefact handling. Models are stored as LightGBM *text* files plus JSON metadata - never pickles - and are
verified (SHA-256, schema version, feature list) before use. Any failure raises ArtifactError so callers can fall
back to the statistical baseline and say so."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import features as F

MODEL_FILE, META_FILE = "model.txt", "metadata.json"
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


class ArtifactError(RuntimeError):
    """The model artefact is missing, corrupt, tampered with, or incompatible with this code version."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current_version_dir(root: Path, kind: str) -> Path:
    pointer = Path(root) / kind / "CURRENT"
    try:
        version = pointer.read_text().strip()
    except OSError as e:
        raise ArtifactError(f"no {kind} model registered ({pointer} not readable)") from e
    if not _VERSION_RE.match(version):
        raise ArtifactError(f"invalid version string in {pointer}")
    d = Path(root) / kind / version
    if not d.is_dir():
        raise ArtifactError(f"model directory {d} does not exist")
    return d


def read_verified(dirpath: Path, *, expected_kind: str, pin: str | None = None) -> tuple[dict, Path]:
    """Return (metadata, model_path) after integrity and compatibility checks.

    The SHA-256 in metadata.json protects against corruption and accidental mismatches only: anyone able to replace model.txt can replace
    metadata.json too. ``pin`` (a digest supplied out-of-band through ML_FORECAST_SHA256 / ML_SHORTAGE_SHA256) closes that gap: when given,
    the model file must match it regardless of what the metadata says."""
    meta_p, model_p = dirpath / META_FILE, dirpath / MODEL_FILE
    if meta_p.is_symlink() or model_p.is_symlink():
        raise ArtifactError("model artefacts must be regular files, not symbolic links")
    if not meta_p.is_file() or not model_p.is_file():
        raise ArtifactError(f"{dirpath} is missing {META_FILE} or {MODEL_FILE}")
    try:
        meta = json.loads(meta_p.read_text())
    except (OSError, ValueError) as e:
        raise ArtifactError(f"unreadable metadata: {e}") from e
    if not isinstance(meta, dict):
        raise ArtifactError(f"metadata.json root must be a JSON object, got {type(meta).__name__}")
    if meta.get("kind") != expected_kind:
        raise ArtifactError(f"artefact kind is {meta.get('kind')!r}, expected {expected_kind!r}")
    if meta.get("schema_version") != F.SCHEMA_VERSION and expected_kind == "demand_forecast":
        raise ArtifactError(f"feature schema v{meta.get('schema_version')} is incompatible with code schema v{F.SCHEMA_VERSION}")
    if expected_kind == "demand_forecast" and meta.get("feature_names") != F.FEATURE_NAMES:
        raise ArtifactError("feature list in metadata does not match the code's feature list")
    actual = sha256_file(model_p)
    if actual != meta.get("model_sha256"):
        raise ArtifactError("model file checksum does not match metadata (file modified or corrupt)")
    if pin is not None and actual != pin.lower():
        raise ArtifactError("model file does not match the pinned SHA-256 supplied in the environment")
    return meta, model_p
