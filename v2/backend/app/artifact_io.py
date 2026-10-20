"""Publish complete artifact directories and verify their content manifests.

Directory renames never expose mixed generations. On an ordinary rename failure,
the old directory is restored. A process interruption between renames can leave
the destination absent; the complete previous directory remains beside it.
"""

import hashlib
import json
import os
import uuid
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifacts(directory, manifest_name):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / manifest_name).read_text(encoding="utf-8"))
    outputs = manifest.get("outputs")
    if not outputs:
        raise ValueError("Missing artifact hashes; rebuild this dataset/experiment")
    for name, expected in outputs.items():
        if Path(name).name != name or name in (".", "..", manifest_name):
            raise ValueError("Unsafe artifact filename")
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size != expected["bytes"] or file_sha256(path) != expected["sha256"]:
            raise ValueError(f"Artifact integrity failure: {name}")
    return manifest


def publish_directory(stage, output, manifest, manifest_name):
    stage, output = Path(stage).resolve(), Path(output).resolve()
    if stage == output or stage.parent != output.parent or not stage.is_dir():
        raise ValueError("Staging and output must be distinct sibling directories")
    files = sorted(stage.iterdir())
    if not files or any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError("Only regular artifact files may be published")
    manifest["outputs"] = {path.name: {"sha256": file_sha256(path), "bytes": path.stat().st_size}
                           for path in files if path.name != manifest_name}
    (stage / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    verify_artifacts(stage, manifest_name)
    backup = output.parent / f".{output.name}.previous-{uuid.uuid4().hex}"
    if backup.resolve().parent != output.parent:
        raise ValueError("Backup path escaped the artifact parent")
    had_previous = output.exists()
    if had_previous:
        os.replace(output, backup)
    try:
        os.replace(stage, output)
    except BaseException:
        if had_previous:
            os.replace(backup, output)
        raise
    # Preserve the old complete generation rather than recursively deleting it.
    return backup if had_previous else None
