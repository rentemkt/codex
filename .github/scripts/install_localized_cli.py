"""Install the verified personal pt-BR Codex build, with reversible local changes."""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath

VERSION = "0.166.0"
TARGET = "aarch64-apple-darwin"
BASE_COMMIT = "6ff1e1ca3b30fc8b914720681fcf5fe62e95f856"
OFFICIAL_SHA256 = "55a440cb579f970abe7c79ab181e54b0ea4c419be99f333bbd868eebac9c21f0"
OFFICIAL_URL = (
    "https://github.com/openai/codex/releases/download/"
    f"rust-v{VERSION}/codex-package-{TARGET}.tar.gz"
)
OFFICIAL_PATH = "/opt/homebrew/bin/codex"
ARCHIVE_NAME = f"codex-pt-BR-{VERSION}-{TARGET}.tar.gz"
MANAGED_START = "# >>> codex-pt-br >>>"
MANAGED_END = "# <<< codex-pt-br <<<"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aggregate_hash(files):
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(f"{name}\0{value}\0".encode())
    return digest.hexdigest()


def inventory(root):
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def expect(value, expected, description):
    if value != expected:
        raise ValueError(description)


def safe_relative(name):
    path = PurePosixPath(name)
    if (
        not name or "\\" in name or path.is_absolute()
        or any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))
    ):
        raise ValueError("unsafe relative path: " + name)
    return Path(*path.parts)


def safe_destination(home, destination):
    """Reject links in managed paths, including an existing destination."""
    destination = Path(destination)
    if not destination.is_absolute():
        destination = home / destination
    try:
        relative = destination.relative_to(home)
    except ValueError:
        raise ValueError("installation destination is outside the selected home")
    safe_relative(relative.as_posix())
    current = home
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("managed paths must not contain symbolic links: " + str(current))
        if current != destination and current.exists() and not current.is_dir():
            raise ValueError("managed parent path is not a directory: " + str(current))
    return destination


def extract_package(archive_path, destination):
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 10000 or sum(item.size for item in members) > 4 * 1024**3:
            raise ValueError("package exceeds supported extraction limits")
        names = set()
        for member in members:
            relative = safe_relative(member.name)
            if relative in names or not (member.isfile() or member.isdir()):
                raise ValueError("duplicate or unsupported archive entry: " + member.name)
            if member.mode & 0o7000:
                raise ValueError("privileged archive permissions are unsupported")
            names.add(relative)
        # Validate every name before creating anything; never follow archive links.
        for member in members:
            output = destination / safe_relative(member.name)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, output.open("xb") as target:
                shutil.copyfileobj(source, target)
            output.chmod(member.mode & 0o777)


def validate_artifact(artifact_dir, destination):
    expected_names = {ARCHIVE_NAME, "localized-build.json"}
    checksums = {}
    for line in (artifact_dir / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("invalid SHA256SUMS entry")
        digest, name = match.groups()
        safe_relative(name)
        if name not in expected_names or name in checksums:
            raise ValueError("unexpected SHA256SUMS entry")
        path = artifact_dir / name
        if path.is_symlink() or not path.is_file() or sha256(path) != digest:
            raise ValueError("artifact SHA256 mismatch: " + name)
        checksums[name] = digest
    expect(set(checksums), expected_names, "artifact checksums are incomplete")
    manifest_bytes = (artifact_dir / "localized-build.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    for key, value in {
        "schemaVersion": 1, "distribution": "unofficial-localized", "locale": "pt-BR",
        "version": VERSION, "target": TARGET,
        "upstreamBase": {"tag": "rust-v" + VERSION, "commit": BASE_COMMIT},
    }.items():
        expect(manifest.get(key), value, "unexpected localized build " + key)
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("sourceCommit", "")):
        raise ValueError("invalid localized source commit")
    official = manifest["officialPackage"]
    expect(official.get("url"), OFFICIAL_URL, "unexpected official package URL")
    expect(official.get("sha256"), OFFICIAL_SHA256, "unexpected official package hash")
    api = manifest["i18nApi"]
    required_api = {"codex-rs/tui/src/i18n.rs", "codex-rs/tui/src/i18n/language_pack.rs"}
    if not required_api.issubset(api.get("files", {})) or any(
        not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in api["files"].values()
    ):
        raise ValueError("invalid i18n API inventory")
    expect(api["sha256"], aggregate_hash(api["files"]), "i18n API inventory hash mismatch")
    for name in api["files"]:
        safe_relative(name)
    extract_package(artifact_dir / ARCHIVE_NAME, destination)
    expect((destination / "localized-build.json").read_bytes(), manifest_bytes,
           "embedded build manifest differs from the artifact manifest")
    package = json.loads((destination / "codex-package.json").read_text())
    for key, value in {
        "layoutVersion": 1, "version": VERSION, "target": TARGET,
        "variant": "codex", "entrypoint": "bin/codex",
    }.items():
        expect(package.get(key), value, "unexpected official package " + key)
    for name in (
        "bin/codex", "bin/codex-code-mode-host", "bin/codex-exec-server", "codex-path/rg",
        "codex-resources/voice/manifest.json", "codex-resources/voice/bin/codex-voice-host",
    ):
        if not (destination / name).is_file():
            raise ValueError("required official resource is missing: " + name)
        if name != "codex-resources/voice/manifest.json" and not os.access(
            destination / name, os.X_OK
        ):
            raise ValueError("required executable resource is not executable: " + name)
    binary = manifest["binary"]
    expect(binary.get("path"), "bin/codex", "unexpected localized binary path")
    expect(binary.get("signature"), "ad-hoc", "unexpected localized binary signature")
    expect(sha256(destination / "bin/codex"), binary["sha256"], "localized binary hash mismatch")
    if not os.access(destination / "bin/codex", os.X_OK):
        raise ValueError("localized binary is not executable")
    pack = manifest.get("localePack")
    if not pack or pack.get("path") != "locale-packs/pt-BR":
        raise ValueError("the pt-BR locale pack is required")
    pack_root = destination / pack["path"]
    expect(aggregate_hash(inventory(pack_root)), pack["sha256"], "locale pack hash mismatch")
    locale = json.loads((pack_root / "manifest.json").read_text())
    for key, value in {"schemaVersion": 1, "type": "language", "locale": "pt-BR"}.items():
        expect(locale.get(key), value, "unexpected language manifest " + key)
    if not locale.get("id") or not locale["i18nApi"]["min"] <= 1 <= locale["i18nApi"]["max"]:
        raise ValueError("incompatible language pack")
    resources = locale["resources"]
    for resource in resources:
        relative = safe_relative(resource["path"])
        expect(sha256(pack_root / relative), resource["sha256"], "language resource hash mismatch")
    if not any(resource["path"] == "messages.ftl" for resource in resources):
        raise ValueError("language messages.ftl is required")
    preserved = {
        name: digest for name, digest in inventory(destination).items()
        if name not in ("bin/codex", "localized-build.json")
        and not name.startswith("locale-packs/")
    }
    expect(len(preserved), official["preservedFileCount"], "official resource count mismatch")
    expect(aggregate_hash(preserved), official["preservedFilesSha256"],
           "an official helper or resource changed")
    return manifest, checksums["localized-build.json"]


def profile_content(original, launcher_dir):
    text = original.decode("utf-8")
    blocks = re.findall(
        r"(?ms)^" + re.escape(MANAGED_START) + r"\n.*?^" + re.escape(MANAGED_END) + r"\n?", text
    )
    if text.count(MANAGED_START) != len(blocks) or text.count(MANAGED_END) != len(blocks):
        raise ValueError("shell profile has an incomplete managed block")
    for block in blocks:
        text = text.replace(block, "")
    if text and not text.endswith("\n"):
        text += "\n"
    block = (
        MANAGED_START + "\n"
        + "_codex_pt_br_bin=" + shlex.quote(str(launcher_dir)) + "\n"
        + 'path=("$_codex_pt_br_bin" "${(@)path:#"$_codex_pt_br_bin"}")\n'
        + "export PATH\n"
        + "unset _codex_pt_br_bin\n"
        + MANAGED_END + "\n"
    )
    return (text + block).encode("utf-8")


def launcher_content(official_path, release, manifest_hash):
    # Keep arguments untouched. Only recognize the FIRST command after known
    # global options: an exec prompt containing "update" must never be rerouted.
    source = '''#!/usr/bin/python3
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

OFFICIAL = __OFFICIAL__
RELEASE = Path(__RELEASE__)
MANIFEST_SHA256 = __MANIFEST_HASH__
VERSION = __VERSION__
TARGET = __TARGET__
BASE = __BASE__
VALUE_OPTIONS = {
    "-c", "--config", "-m", "--model", "-p", "--profile", "-s", "--sandbox",
    "-a", "--ask-for-approval", "-C", "--cd", "--add-dir", "--enable", "--disable",
    "-i", "--image", "--remote", "--remote-auth-token-env", "--local-provider",
}
FLAG_OPTIONS = {
    "--search", "--oss", "--full-auto", "--dangerously-bypass-approvals-and-sandbox",
    "--no-alt-screen", "--no-mouse", "--help", "-h", "--version", "-V",
    "--strict-config", "--no-daemon", "--worktree", "--approve-for-me", "--not-so-yolo",
    "--yolo", "--dangerously-bypass-hook-trust",
}

def first_command(arguments):
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            return None
        if argument in VALUE_OPTIONS:
            index += 2
        elif argument in FLAG_OPTIONS or argument.startswith("--") and "=" in argument:
            index += 1
        elif any(argument.startswith(short) and len(argument) > len(short)
                 for short in ("-c", "-m", "-p", "-s", "-a", "-C", "-i")):
            index += 1
        elif argument.startswith("-"):
            return None
        else:
            return argument
    return None

def compatible():
    try:
        result = subprocess.run([OFFICIAL, "--version"], capture_output=True,
                                text=True, timeout=5, check=True)
        match = re.fullmatch(r"codex-cli ([0-9]+\\.[0-9]+\\.[0-9]+)\\s*", result.stdout)
        if not match or match.group(1) != VERSION:
            return False
        source = (RELEASE / "localized-build.json").read_bytes()
        if hashlib.sha256(source).hexdigest() != MANIFEST_SHA256:
            return False
        manifest = json.loads(source)
        return (manifest.get("version") == VERSION and manifest.get("target") == TARGET
                and manifest.get("upstreamBase", {}).get("commit") == BASE
                and manifest.get("binary", {}).get("path") == "bin/codex"
                and (RELEASE / "bin/codex").is_file())
    except (OSError, ValueError, subprocess.SubprocessError):
        return False

command = OFFICIAL
if first_command(sys.argv[1:]) != "update" and compatible():
    command = str(RELEASE / "bin/codex")
    os.execve(command, [command, *sys.argv[1:]], {**os.environ, "CODEX_MANAGED_BY_BREW": "1"})
os.execv(command, [command, *sys.argv[1:]])
'''
    for marker, value in {
        "__OFFICIAL__": str(official_path), "__RELEASE__": str(release),
        "__MANIFEST_HASH__": manifest_hash, "__VERSION__": VERSION,
        "__TARGET__": TARGET, "__BASE__": BASE_COMMIT,
    }.items():
        source = source.replace(marker, repr(value))
    return source.encode("utf-8")


def path_state(path):
    if path.is_symlink():
        raise ValueError("symbolic links are unsupported in managed content")
    if not path.exists():
        return None
    entries = {}
    paths = [path] + sorted(path.rglob("*")) if path.is_dir() else [path]
    for item in paths:
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise ValueError("unsupported managed file type: " + str(item))
        name = "." if item == path else item.relative_to(path).as_posix()
        entries[name] = {"mode": stat.S_IMODE(item.stat().st_mode),
                         "type": "directory" if item.is_dir() else "file"}
        if item.is_file():
            entries[name]["sha256"] = sha256(item)
    return entries


def copy_path(source, destination):
    if source.is_dir():
        shutil.copytree(source, destination, copy_function=shutil.copy2)
    else:
        shutil.copy2(source, destination)


def replace_path(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(destination.name + ".ptbr-" + uuid.uuid4().hex)
    copy_path(source, staged)
    if destination.is_dir():
        shutil.rmtree(destination)
    elif source.is_dir() and destination.exists():
        destination.unlink()
    os.replace(staged, destination)


def check_shell_profiles(profiles, temporary):
    for index, source in enumerate(profiles):
        result = subprocess.run(
            ["/bin/zsh", "-f", "-n", str(source)], capture_output=True, text=True,
            env={**os.environ, "HOME": str(temporary), "ZDOTDIR": str(temporary)}, timeout=10,
        )
        if result.returncode:
            raise ValueError("shell profile syntax check failed for profile " + str(index))


def save_receipt(path, receipt):
    temporary = path.with_name("receipt.pending-" + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        temporary.chmod(0o600)
        stream.write(json.dumps(receipt, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def install(artifact_dir, home, official_path=OFFICIAL_PATH, shell_profiles=None):
    home = Path(home).resolve(strict=True)
    official_path = Path(official_path).absolute()
    if not official_path.is_file() or not os.access(official_path, os.X_OK):
        raise ValueError("the official Codex executable is unavailable")
    base = safe_destination(home, home / ".local/share/codex-pt-br")
    release = safe_destination(home, base / "releases" / VERSION)
    language = safe_destination(home, home / ".codex/ccu/languages/pt-BR")
    preference = safe_destination(home, home / ".codex/ui-language")
    launcher = safe_destination(home, base / "bin/codex")
    profiles = [safe_destination(home, Path(path)) for path in
                (shell_profiles or [home / ".zprofile", home / ".zshrc"])]
    if len(set(profiles)) != len(profiles):
        raise ValueError("shell profile paths must be unique")
    with tempfile.TemporaryDirectory(prefix="codex-ptbr-install-") as name:
        temporary = Path(name)
        package = temporary / "package"
        package.mkdir()
        _, manifest_hash = validate_artifact(Path(artifact_dir).resolve(), package)
        generated = temporary / "generated"
        generated.mkdir()
        desired = [(release, package), (language, package / "locale-packs/pt-BR")]
        for filename, data, mode, target in [
            ("preference", b"pt-BR\n", 0o600, preference),
            ("launcher", launcher_content(official_path, release, manifest_hash), 0o755, launcher),
        ]:
            source = generated / filename
            source.write_bytes(data)
            source.chmod(mode)
            desired.append((target, source))
        profile_sources = []
        for index, profile in enumerate(profiles):
            if profile.exists() and not profile.is_file():
                raise ValueError("shell profile is not a regular file")
            original = profile.read_bytes() if profile.exists() else b""
            source = generated / ("profile-" + str(index))
            source.write_bytes(profile_content(original, launcher.parent))
            source.chmod(stat.S_IMODE(profile.stat().st_mode) if profile.exists() else 0o644)
            desired.append((profile, source))
            profile_sources.append(source)
        check_shell_profiles(profile_sources, temporary)
        if len({path for path, _ in desired}) != len(desired):
            raise ValueError("installation paths overlap")
        for target, _ in desired:
            if any(target in other.parents for other, _ in desired if other != target):
                raise ValueError("installation paths overlap")
        changes = []
        for target, source in desired:
            before, after = path_state(target), path_state(source)
            if before != after:
                changes.append((target, source, before, after))
        if not changes:
            return {"status": "unchanged", "release": str(release)}
        backup = safe_destination(home, base / "backups" / uuid.uuid4().hex)
        backup.mkdir(parents=True, mode=0o700)
        receipt = {"schemaVersion": 1, "home": str(home), "entries": [], "status": "prepared"}
        restorer = backup / "restore.py"
        shutil.copy2(Path(__file__).resolve(), restorer)
        restorer.chmod(0o600)
        receipt["restorerSha256"] = sha256(restorer)
        for index, (target, _, before, after) in enumerate(changes):
            snapshot = backup / ("previous-" + str(index))
            if before is not None:
                copy_path(target, snapshot)
                expect(path_state(snapshot), before, "backup verification failed")
            receipt["entries"].append({
                "path": target.relative_to(home).as_posix(), "backup": snapshot.name,
                "before": before, "installed": after,
            })
        receipt_path = backup / "receipt.json"
        save_receipt(receipt_path, receipt)
        applied = []
        try:
            for (target, source, before, after), entry in zip(changes, receipt["entries"]):
                expect(path_state(target), before, "destination changed during installation")
                applied.append(entry)
                replace_path(source, target)
                expect(path_state(target), after, "installed file verification failed")
        except BaseException:
            restore_entries(home, backup, reversed(applied))
            receipt["status"] = "rolled-back"
            save_receipt(receipt_path, receipt)
            raise
        receipt["status"] = "installed"
        save_receipt(receipt_path, receipt)
        return {"status": "installed", "release": str(release), "receipt": str(receipt_path),
                "changedPaths": len(changes), "restoreCommand": shlex.join([
                    "/usr/bin/python3", str(restorer), "--restore", str(receipt_path),
                    "--home", str(home),
                ])}


def restore_entries(home, backup, entries):
    for entry in entries:
        target = safe_destination(home, home / safe_relative(entry["path"]))
        if entry["before"] is None:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        else:
            source = safe_destination(home, backup / safe_relative(entry["backup"]))
            expect(path_state(source), entry["before"], "recovery backup verification failed")
            replace_path(source, target)
        expect(path_state(target), entry["before"], "recovery verification failed")


def restore(receipt_path, home):
    home = Path(home).resolve(strict=True)
    receipt_path = safe_destination(home, Path(receipt_path).absolute())
    backup_root = safe_destination(home, home / ".local/share/codex-pt-br/backups")
    if receipt_path.parent.parent != backup_root or receipt_path.name != "receipt.json":
        raise ValueError("recovery receipt must be in the managed backup directory")
    receipt = json.loads(receipt_path.read_text())
    expect(receipt.get("schemaVersion"), 1, "unsupported recovery receipt")
    expect(receipt.get("home"), str(home), "recovery receipt belongs to another home")
    if receipt.get("status") not in ("installed", "prepared"):
        raise ValueError("this installation cannot be restored")
    interrupted = receipt["status"] == "prepared"
    for entry in receipt["entries"]:
        target = safe_destination(home, home / safe_relative(entry["path"]))
        state = path_state(target)
        accepted = [entry["installed"]]
        if interrupted:
            # A killed process may have left a target untouched, or between
            # removing a backed-up directory and renaming its staged replacement.
            accepted.extend([entry["before"], None])
        if state not in accepted:
            raise ValueError("installed content changed; recovery stopped without overwriting it")
        source = safe_destination(home, receipt_path.parent / safe_relative(entry["backup"]))
        expect(path_state(source), entry["before"], "recovery backup verification failed")
    restore_entries(home, receipt_path.parent, reversed(receipt["entries"]))
    receipt["status"] = "restored"
    save_receipt(receipt_path, receipt)
    return {"status": "restored", "receipt": str(receipt_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--artifact-dir", type=Path)
    action.add_argument("--restore", type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--official-path", type=Path, default=Path(OFFICIAL_PATH))
    parser.add_argument("--shell-profile", action="append", type=Path)
    args = parser.parse_args()
    try:
        result = restore(args.restore, args.home) if args.restore else install(
            args.artifact_dir, args.home, args.official_path, args.shell_profile
        )
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError,
            subprocess.SubprocessError) as error:
        parser.exit(1, "Installation stopped: " + str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
