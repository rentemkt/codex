"""Replace only Codex in a pinned official package and record its provenance."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

VERSION = "0.166.0"
TARGET = "aarch64-apple-darwin"
BASE_COMMIT = "6ff1e1ca3b30fc8b914720681fcf5fe62e95f856"
OFFICIAL_ARCHIVE_SHA256 = (
    "55a440cb579f970abe7c79ab181e54b0ea4c419be99f333bbd868eebac9c21f0"
)
OFFICIAL_URL = (
    "https://github.com/openai/codex/releases/download/"
    f"rust-v{VERSION}/codex-package-{TARGET}.tar.gz"
)


def sha256(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def inventory(root):
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def aggregate_hash(files):
    hasher = hashlib.sha256()
    for name, digest in sorted(files.items()):
        hasher.update(f"{name}\0{digest}\0".encode())
    return hasher.hexdigest()


def stage_official_archive(archive_path, destination, expected_sha256):
    if sha256(archive_path) != expected_sha256:
        raise ValueError("official package SHA256 mismatch")
    destination.mkdir()
    with tarfile.open(archive_path, "r:gz") as archive:
        # The pinned package has only regular files/directories, with no links.
        for member in archive.getmembers():
            path = (destination / member.name).resolve()
            if destination.resolve() not in path.parents or not (
                member.isfile() or member.isdir()
            ):
                raise ValueError(f"unsupported official package entry: {member.name}")
        archive.extractall(destination)
    manifest = json.loads((destination / "codex-package.json").read_text())
    if any(
        manifest.get(key) != value
        for key, value in {
            "layoutVersion": 1,
            "version": VERSION,
            "target": TARGET,
            "variant": "codex",
            "entrypoint": "bin/codex",
        }.items()
    ):
        raise ValueError("unexpected official Codex package layout or version")
    for required in (
        "bin/codex",
        "bin/codex-code-mode-host",
        "bin/codex-exec-server",
        "codex-path/rg",
        "codex-resources/voice/manifest.json",
        "codex-resources/voice/bin/codex-voice-host",
    ):
        if not (destination / required).is_file():
            raise ValueError(f"official package resource is missing: {required}")
    return inventory(destination)


def package_localized_cli(source_root, binary, archive_path, output_dir):
    cargo = (source_root / "codex-rs/Cargo.toml").read_text()
    if not re.search(r'^version = "0\.166\.0"$', cargo, re.MULTILINE):
        raise ValueError("Cargo version must remain 0.166.0")
    i18n = source_root / "codex-rs/tui/src/i18n.rs"
    language_pack = i18n.with_suffix("") / "language_pack.rs"
    if not i18n.is_file() or not language_pack.is_file():
        raise ValueError(
            "the localized i18n interface and language-pack loader are required"
        )
    api_files = {
        path.relative_to(source_root).as_posix(): sha256(path)
        for path in [i18n, *sorted(i18n.with_suffix("").rglob("*"))]
        if path.is_file()
    }
    commit = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
    ).strip()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"codex-pt-BR-{VERSION}-{TARGET}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="localized-codex-") as temporary:
        package = Path(temporary) / "package"
        original = stage_official_archive(
            archive_path, package, OFFICIAL_ARCHIVE_SHA256
        )
        shutil.copy2(binary, package / "bin/codex")
        (package / "bin/codex").chmod(0o755)
        preserved = {
            name: digest for name, digest in original.items() if name != "bin/codex"
        }
        after = inventory(package)
        if any(after.get(name) != digest for name, digest in preserved.items()):
            raise ValueError("an official helper or resource changed unexpectedly")
        locale_pack = source_root / ".github/locale-packs/pt-BR"
        pack_manifest = None
        if locale_pack.is_dir():
            shutil.copytree(locale_pack, package / "locale-packs/pt-BR")
            pack_manifest = {
                "path": "locale-packs/pt-BR",
                "sha256": aggregate_hash(inventory(locale_pack)),
            }
        manifest = {
            "schemaVersion": 1,
            "distribution": "unofficial-localized",
            "locale": "pt-BR",
            "version": VERSION,
            "target": TARGET,
            "sourceCommit": commit,
            "upstreamBase": {"tag": f"rust-v{VERSION}", "commit": BASE_COMMIT},
            "binary": {
                "path": "bin/codex",
                "sha256": after["bin/codex"],
                "signature": "ad-hoc",
            },
            "i18nApi": {"sha256": aggregate_hash(api_files), "files": api_files},
            "localePack": pack_manifest,
            "officialPackage": {
                "url": OFFICIAL_URL,
                "sha256": OFFICIAL_ARCHIVE_SHA256,
                "preservedFileCount": len(preserved),
                "preservedFilesSha256": aggregate_hash(preserved),
            },
        }
        serialized = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        (package / "localized-build.json").write_text(serialized, encoding="utf-8")
        (output_dir / "localized-build.json").write_text(serialized, encoding="utf-8")
        with tarfile.open(output_dir / archive_name, "w:gz") as archive:
            for path in sorted(package.rglob("*")):
                archive.add(path, arcname=path.relative_to(package), recursive=False)
    files = [archive_name, "localized-build.json"]
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{sha256(output_dir / name)}  {name}\n" for name in files),
        encoding="ascii",
    )
    print(
        json.dumps({"archive": str(output_dir / archive_name), "sourceCommit": commit})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-archive", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    package_localized_cli(
        Path(__file__).resolve().parents[2],
        args.binary,
        args.official_archive,
        args.output_dir,
    )
