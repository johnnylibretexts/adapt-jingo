"""Model manifest verification and private-bundle install helpers.

The CT2 acoustic model is intentionally kept outside the Python wheel. This
module gives embedding apps a small auditable boundary: verify the external
model directory against a manifest, or install it from an explicitly supplied
local/archive URL and then verify it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DEFAULT_MODEL_MANIFEST_PATH = ASSETS_DIR / "model-manifest.json"
DEFAULT_HF_MODEL_REPO_ID = "johnnyrobotai/johnnylingo-jingo-wav2vec2-xlsr-53-espeak-ct2"
DEFAULT_HF_MODEL_FILENAME = "wav2vec2-xlsr-53-espeak-ct2-v0.2.1.zip"
DEFAULT_HF_MODEL_REVISION = "main"


class ModelAssetError(RuntimeError):
    """Raised when a model asset cannot be verified or installed."""


def load_model_manifest(path: str | Path | None = None) -> dict[str, Any]:
    """Load the default or caller-supplied model manifest."""
    manifest_path = Path(path) if path else DEFAULT_MODEL_MANIFEST_PATH
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def required_files(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return list(manifest.get("model", {}).get("required_files", []))


def verify_model_dir(
    model_dir: str | Path,
    *,
    manifest: dict[str, Any] | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a structured verification report for ``model_dir``.

    This never loads CTranslate2, so callers can use it in CI and packaging
    smoke tests without paying model startup cost.
    """
    loaded = manifest or load_model_manifest(manifest_path)
    root = Path(model_dir)
    file_reports: list[dict[str, Any]] = []
    errors: list[str] = []
    for spec in required_files(loaded):
        rel = str(spec["path"])
        path = root / rel
        report: dict[str, Any] = {
            "path": rel,
            "exists": path.is_file(),
            "expected_size_bytes": spec.get("size_bytes"),
            "expected_sha256": spec.get("sha256"),
        }
        if not path.is_file():
            report["ok"] = False
            errors.append(f"missing {rel}")
            file_reports.append(report)
            continue
        size = path.stat().st_size
        report["size_bytes"] = size
        if spec.get("size_bytes") is not None and size != int(spec["size_bytes"]):
            report["ok"] = False
            errors.append(f"{rel} size mismatch: {size} != {spec['size_bytes']}")
            file_reports.append(report)
            continue
        digest = file_sha256(path)
        report["sha256"] = digest
        if spec.get("sha256") and digest != spec["sha256"]:
            report["ok"] = False
            errors.append(f"{rel} sha256 mismatch")
        else:
            report["ok"] = True
        file_reports.append(report)

    return {
        "ok": not errors,
        "model_dir": str(root),
        "manifest_version": loaded.get("manifest_version"),
        "model_name": loaded.get("model", {}).get("name"),
        "files": file_reports,
        "errors": errors,
    }


def verify_or_raise(
    model_dir: str | Path,
    *,
    manifest: dict[str, Any] | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    report = verify_model_dir(model_dir, manifest=manifest, manifest_path=manifest_path)
    if not report["ok"]:
        raise ModelAssetError("; ".join(report["errors"]) or "model verification failed")
    return report


def ensure_model(
    model_dir: str | Path,
    archive: str,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Install a model from a caller-provided archive/path, then verify it.

    ``archive`` may be a local directory, a local zip/tar/tar.gz/tgz archive, or
    an http(s) URL to one of those archive formats. There is deliberately no
    default public URL in v0.2.1.
    """
    dest = Path(model_dir)
    manifest = load_model_manifest(manifest_path)
    existing = verify_model_dir(dest, manifest=manifest)
    if existing["ok"]:
        existing["status"] = "already_present"
        return existing

    with tempfile.TemporaryDirectory(prefix="jingo-engine-model-") as tmp:
        tmp_path = Path(tmp)
        source = _acquire_archive(archive, tmp_path)
        extracted = _extract_or_copy_source(source, tmp_path / "extracted")
        model_root = _find_model_root(extracted, manifest)
        dest.mkdir(parents=True, exist_ok=True)
        for spec in required_files(manifest):
            rel = str(spec["path"])
            shutil.copy2(model_root / rel, dest / rel)

    report = verify_or_raise(dest, manifest=manifest)
    report["status"] = "installed"
    return report


def huggingface_archive_url(
    repo_id: str,
    filename: str,
    *,
    revision: str = DEFAULT_HF_MODEL_REVISION,
) -> str:
    """Return the explicit Hugging Face archive URL for a model artifact.

    This is intentionally a URL builder, not a hidden default. Callers still
    choose the repo, revision, and filename at the CLI/API boundary.
    """
    repo = "/".join(urllib.parse.quote(part, safe="") for part in repo_id.split("/"))
    rev = urllib.parse.quote(revision, safe="")
    name = urllib.parse.quote(filename, safe="/")
    return f"https://huggingface.co/{repo}/resolve/{rev}/{name}"


def ensure_model_from_huggingface(
    model_dir: str | Path,
    *,
    repo_id: str,
    filename: str,
    revision: str = DEFAULT_HF_MODEL_REVISION,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Install a model from an explicitly supplied Hugging Face artifact."""
    url = huggingface_archive_url(repo_id, filename, revision=revision)
    report = ensure_model(model_dir, url, manifest_path=manifest_path)
    report["source"] = {
        "type": "huggingface",
        "repo_id": repo_id,
        "revision": revision,
        "filename": filename,
        "url": url,
    }
    return report


def _acquire_archive(archive: str, tmp_path: Path) -> Path:
    parsed = urllib.parse.urlparse(archive)
    if parsed.scheme in {"http", "https"}:
        name = Path(parsed.path).name or "model-archive"
        target = tmp_path / name
        urllib.request.urlretrieve(archive, target)  # noqa: S310 - caller supplies trusted URL
        return target
    path = Path(archive).expanduser()
    if not path.exists():
        raise ModelAssetError(f"archive not found: {path}")
    return path


def _extract_or_copy_source(source: Path, target: Path) -> Path:
    if source.is_dir():
        return source
    target.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            zf.extractall(target)
        return target
    if tarfile.is_tarfile(source):
        with tarfile.open(source) as tf:
            tf.extractall(target)
        return target
    raise ModelAssetError(f"unsupported archive format: {source}")


def _find_model_root(extracted: Path, manifest: dict[str, Any]) -> Path:
    candidates = [extracted]
    if extracted.is_dir():
        candidates.extend(p for p in extracted.rglob("*") if p.is_dir())
    required = [str(spec["path"]) for spec in required_files(manifest)]
    for candidate in candidates:
        if all((candidate / rel).is_file() for rel in required):
            return candidate
    raise ModelAssetError("archive does not contain required model files")


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify or install jingo_engine CT2 model assets.")
    parser.add_argument("--manifest", help="Path to a model manifest JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="Verify a model directory against the manifest.")
    verify.add_argument("--model-dir", required=True)

    ensure = sub.add_parser("ensure", help="Install from an explicit archive/path or Hugging Face artifact, then verify.")
    ensure.add_argument("--model-dir", required=True)
    ensure.add_argument("--archive", help="Local directory/archive or http(s) archive URL.")
    ensure.add_argument("--hf-repo", help="Explicit Hugging Face repo id, for example owner/model-repo.")
    ensure.add_argument("--hf-revision", default=DEFAULT_HF_MODEL_REVISION)
    ensure.add_argument("--hf-filename", help="Archive filename inside the Hugging Face repo.")

    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            report = verify_model_dir(args.model_dir, manifest_path=args.manifest)
            _print_json(report)
            return 0 if report["ok"] else 1
        if args.command == "ensure":
            if args.archive:
                _print_json(ensure_model(args.model_dir, args.archive, manifest_path=args.manifest))
                return 0
            if args.hf_repo and args.hf_filename:
                _print_json(
                    ensure_model_from_huggingface(
                        args.model_dir,
                        repo_id=args.hf_repo,
                        revision=args.hf_revision,
                        filename=args.hf_filename,
                        manifest_path=args.manifest,
                    )
                )
                return 0
            raise ModelAssetError("ensure requires --archive or both --hf-repo and --hf-filename")
            return 0
    except Exception as exc:  # pragma: no cover - exercised through CLI subprocess tests
        _print_json({"ok": False, "error": str(exc)})
        return 1
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
