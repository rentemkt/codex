import contextlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_localized_cli as packaging


class LocalizedPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="localized-package-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.official = self.root / "official"
        self.official.mkdir()
        package_manifest = {
            "layoutVersion": 1,
            "version": "0.166.0",
            "target": "aarch64-apple-darwin",
            "variant": "codex",
            "entrypoint": "bin/codex",
        }
        self.resources = {
            "codex-package.json": json.dumps(package_manifest).encode(),
            "bin/codex": b"official binary",
            "bin/codex-code-mode-host": b"code mode and Python helper",
            "bin/codex-exec-server": b"exec helper",
            "codex-path/rg": b"ripgrep",
            "codex-resources/voice/manifest.json": b"{}",
            "codex-resources/voice/bin/codex-voice-host": b"voice helper",
            "codex-resources/voice/lib/audio.dylib": b"official audio runtime",
            "codex-resources/voice/licenses/LICENSE": b"upstream license",
        }
        for name, content in self.resources.items():
            path = self.official / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.archive = self.root / "official.tar.gz"
        with tarfile.open(self.archive, "w:gz") as archive:
            for path in self.official.rglob("*"):
                archive.add(
                    path, arcname=path.relative_to(self.official), recursive=False
                )

    def test_only_cli_changes_and_provenance_identifies_the_variant(self):
        source = self.root / "source"
        module = source / "codex-rs/tui/src/i18n.rs"
        loader = module.with_suffix("") / "language_pack.rs"
        loader.parent.mkdir(parents=True)
        module.write_text("// localized interface\n")
        loader.write_text("// external pack loader\n")
        (source / "codex-rs/Cargo.toml").write_text('version = "0.166.0"\n')
        locale = source / ".github/locale-packs/pt-BR/messages.ftl"
        locale.parent.mkdir(parents=True)
        locale.write_text("hello = Olá\n", encoding="utf-8")
        binary = self.root / "localized-codex"
        binary.write_bytes(b"localized binary")
        output = self.root / "output"
        with (
            patch.object(
                packaging, "OFFICIAL_ARCHIVE_SHA256", packaging.sha256(self.archive)
            ),
            patch.object(packaging.subprocess, "check_output", return_value="a" * 40),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            packaging.package_localized_cli(source, binary, self.archive, output)
        archive_path = next(output.glob("*.tar.gz"))
        with tarfile.open(archive_path) as archive:
            for name, original in self.resources.items():
                expected = b"localized binary" if name == "bin/codex" else original
                self.assertEqual(archive.extractfile(name).read(), expected, name)
            self.assertEqual(
                archive.extractfile("locale-packs/pt-BR/messages.ftl").read(),
                locale.read_bytes(),
            )
            manifest = json.load(archive.extractfile("localized-build.json"))
        self.assertEqual(manifest["distribution"], "unofficial-localized")
        self.assertEqual(manifest["version"], "0.166.0")
        self.assertEqual(manifest["sourceCommit"], "a" * 40)
        self.assertEqual(
            manifest["officialPackage"]["preservedFileCount"], len(self.resources) - 1
        )
        self.assertEqual(manifest["binary"]["sha256"], packaging.sha256(binary))
        self.assertEqual(len(manifest["i18nApi"]["files"]), 2)
        for line in (output / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(digest, packaging.sha256(output / name))

    def test_incorrect_official_hash_fails_before_extraction(self):
        destination = self.root / "extracted"
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            packaging.stage_official_archive(self.archive, destination, "0" * 64)
        self.assertFalse(destination.exists())

    def test_archive_cannot_create_links_or_escape_its_directory(self):
        for name, entry_type in [
            ("../escape", tarfile.REGTYPE),
            ("link", tarfile.SYMTYPE),
        ]:
            with self.subTest(name=name):
                archive_path = self.root / "unsafe.tar.gz"
                with tarfile.open(archive_path, "w:gz") as archive:
                    entry = tarfile.TarInfo(name)
                    entry.type = entry_type
                    entry.linkname = "../escape"
                    archive.addfile(entry)
                with self.assertRaisesRegex(
                    ValueError, "unsupported official package entry"
                ):
                    packaging.stage_official_archive(
                        archive_path,
                        self.root / name.replace("/", "-"),
                        packaging.sha256(archive_path),
                    )
        self.assertFalse((self.root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
