"""Exercise installation, routing, zsh integration and recovery in temporary homes."""

import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def load_installer():
    location = Path(__file__).with_name("install_localized_cli.py")
    spec = importlib.util.spec_from_file_location("localized_installer", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_installer()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-install-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home with [brackets]"
        self.home.mkdir()
        self.version = self.root / "official-version"
        self.version.write_text(installer.VERSION)
        self.official = self.root / "official-codex"
        self.official.write_text(
            "#!" + sys.executable + "\n"
            "import json, sys\nfrom pathlib import Path\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print('codex-cli ' + Path(" + repr(str(self.version)) + ").read_text())\n"
            "else:\n    print(json.dumps({'source':'official','args':sys.argv[1:]}))\n"
        )
        self.official.chmod(0o755)
        self.artifact = self.root / "artifact"
        self.artifact.mkdir()
        self.package = self.root / "package"
        self.package.mkdir()
        self.create_artifact()

    def create_artifact(self):
        files = {
            "bin/codex": (
                "#!" + sys.executable + "\nimport json,sys\n"
                "print(json.dumps({'source':'localized','args':sys.argv[1:]}))\n"
            ).encode(),
            "bin/codex-code-mode-host": b"official code host\n",
            "bin/codex-exec-server": b"official exec server\n",
            "codex-path/rg": b"official ripgrep\n",
            "codex-resources/voice/manifest.json": b'{"version":1}\n',
            "codex-resources/voice/bin/codex-voice-host": b"official voice host\n",
            "codex-package.json": json.dumps({
                "layoutVersion": 1, "version": installer.VERSION,
                "target": installer.TARGET, "variant": "codex", "entrypoint": "bin/codex",
            }).encode(),
        }
        for name, data in files.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            executable = name.startswith(("bin/", "codex-path/")) or "/bin/" in name
            path.chmod(0o755 if executable else 0o644)
        original = installer.inventory(self.package)
        pack = self.package / "locale-packs/pt-BR"
        pack.mkdir(parents=True)
        messages = pack / "messages.ftl"
        messages.write_text("language-picker-title = Selecionar idioma\n")
        (pack / "manifest.json").write_text(json.dumps({
            "schemaVersion": 1, "type": "language", "id": "test.pt-BR", "locale": "pt-BR",
            "i18nApi": {"min": 1, "max": 1},
            "resources": [{"path": "messages.ftl", "sha256": installer.sha256(messages)}],
        }))
        api = {name: "a" * 64 for name in (
            "codex-rs/tui/src/i18n.rs", "codex-rs/tui/src/i18n/language_pack.rs"
        )}
        preserved = {name: digest for name, digest in original.items() if name != "bin/codex"}
        self.manifest = {
            "schemaVersion": 1, "distribution": "unofficial-localized", "locale": "pt-BR",
            "version": installer.VERSION, "target": installer.TARGET, "sourceCommit": "b" * 40,
            "upstreamBase": {"tag": "rust-v" + installer.VERSION, "commit": installer.BASE_COMMIT},
            "binary": {"path": "bin/codex", "sha256": original["bin/codex"], "signature": "ad-hoc"},
            "i18nApi": {"files": api, "sha256": installer.aggregate_hash(api)},
            "localePack": {"path": "locale-packs/pt-BR", "sha256": installer.aggregate_hash(installer.inventory(pack))},
            "officialPackage": {
                "url": installer.OFFICIAL_URL, "sha256": installer.OFFICIAL_SHA256,
                "preservedFileCount": len(preserved),
                "preservedFilesSha256": installer.aggregate_hash(preserved),
            },
        }
        self.repack()

    def repack(self, extra=None):
        data = (json.dumps(self.manifest, indent=2) + "\n").encode()
        (self.artifact / "localized-build.json").write_bytes(data)
        (self.package / "localized-build.json").write_bytes(data)
        archive_path = self.artifact / installer.ARCHIVE_NAME
        with tarfile.open(archive_path, "w:gz") as archive:
            for path in sorted(self.package.rglob("*")):
                archive.add(path, arcname=path.relative_to(self.package), recursive=False)
            if extra:
                member, payload = extra
                archive.addfile(member, io.BytesIO(payload) if member.isfile() else None)
        self.update_checksums()

    def update_checksums(self):
        (self.artifact / "SHA256SUMS").write_text("".join(
            installer.sha256(self.artifact / name) + "  " + name + "\n"
            for name in (installer.ARCHIVE_NAME, "localized-build.json")
        ))

    def install(self, **kwargs):
        return installer.install(self.artifact, self.home, self.official, **kwargs)

    @property
    def release(self):
        return self.home / ".local/share/codex-pt-br/releases" / installer.VERSION

    @property
    def launcher(self):
        return self.home / ".local/share/codex-pt-br/bin/codex"

    def run_launcher(self, *args):
        output = subprocess.check_output([str(self.launcher), *args], text=True)
        return json.loads(output)

    def test_matching_version_uses_complete_localized_package(self):
        result = self.install()
        self.assertEqual(result["status"], "installed")
        self.assertEqual(self.run_launcher("--profile", "work", "exec", "inspect"), {
            "source": "localized", "args": ["--profile", "work", "exec", "inspect"],
        })
        for name in ("bin/codex-code-mode-host", "bin/codex-exec-server", "codex-path/rg",
                     "codex-resources/voice/bin/codex-voice-host"):
            self.assertEqual((self.release / name).read_bytes(), (self.package / name).read_bytes())
        self.assertEqual((self.home / ".codex/ui-language").read_text(), "pt-BR\n")
        self.assertTrue((self.home / ".codex/ccu/languages/pt-BR/messages.ftl").is_file())

    def test_new_official_version_or_modified_manifest_uses_official(self):
        self.install()
        self.version.write_text("0.167.0")
        self.assertEqual(self.run_launcher("exec", "inspect")["source"], "official")
        self.version.write_text(installer.VERSION)
        manifest = self.release / "localized-build.json"
        manifest.write_text(manifest.read_text() + " ")
        self.assertEqual(self.run_launcher("exec", "inspect")["source"], "official")

    def test_update_routes_only_the_actual_subcommand_and_keeps_flags(self):
        self.install()
        for args in [("update",), ("-c", "model='x'", "--profile", "work", "update"),
                     ("--model=gpt", "--search", "update"), ("-mtest", "update"),
                     ("--no-daemon", "--strict-config", "update"),
                     ("--oss", "--local-provider", "ollama", "update")]:
            with self.subTest(args=args):
                self.assertEqual(self.run_launcher(*args), {"source": "official", "args": list(args)})
        for args in [("exec", "update"), ("-m", "update", "exec", "prompt"),
                     ("--", "update"), ("exec", "--", "update")]:
            with self.subTest(args=args):
                self.assertEqual(self.run_launcher(*args)["source"], "localized")

    def test_homebrew_symlink_is_untouched_and_future_target_is_followed(self):
        link = self.root / "homebrew/bin/codex"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.official)
        installer.install(self.artifact, self.home, link)
        self.assertEqual(link.readlink(), self.official)
        self.assertEqual(self.run_launcher("exec", "inspect")["source"], "localized")
        future = self.root / "Caskroom/future/codex"
        future.parent.mkdir(parents=True)
        future.write_text(
            "#!" + sys.executable + "\nimport json,sys\n"
            "if sys.argv[1:] == ['--version']:\n    print('codex-cli 0.167.0')\n"
            "else:\n    print(json.dumps({'source':'official-new','args':sys.argv[1:]}))\n"
        )
        future.chmod(0o755)
        link.unlink()
        link.symlink_to(future)
        self.assertEqual(self.run_launcher("exec", "inspect")["source"], "official-new")
        self.assertNotIn("Caskroom", self.launcher.read_text())

    def test_existing_files_have_verified_backups_and_recover_exactly(self):
        originals = {
            ".zprofile": b"# login profile\nexport USER_SETTING='keep me'\n",
            ".zshrc": b"# interactive profile\nalias important='echo preserved'\n",
            ".codex/ui-language": b"en\n",
            ".codex/ccu/languages/pt-BR/messages.ftl": b"custom = Previous translation\n",
            ".codex/ccu/languages/pt-BR/manifest.json": b"previous manifest\n",
            ".local/share/codex-pt-br/releases/0.166.0/previous-file": b"previous release\n",
            ".local/share/codex-pt-br/bin/codex": b"#!/bin/sh\necho previous\n",
        }
        for name, data in originals.items():
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.home / ".zshrc").chmod(0o600)
        result = self.install()
        receipt = json.loads(Path(result["receipt"]).read_text())
        for entry in receipt["entries"]:
            if entry["before"] is not None:
                snapshot = Path(result["receipt"]).parent / entry["backup"]
                self.assertEqual(installer.path_state(snapshot), entry["before"])
        installer.restore(result["receipt"], self.home)
        for name, data in originals.items():
            self.assertEqual((self.home / name).read_bytes(), data)
        self.assertEqual((self.home / ".zshrc").stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.release / "bin/codex").exists())

    def test_shell_profiles_are_preserved_idempotent_and_work_in_real_zsh(self):
        original = b"# preserve this profile\nexport OTHER_SETTING=yes\n"
        for name in (".zprofile", ".zshrc"):
            (self.home / name).write_bytes(original)
        self.install()
        backup_count = len(list((self.home / ".local/share/codex-pt-br/backups").iterdir()))
        self.assertEqual(self.install()["status"], "unchanged")
        self.assertEqual(len(list((self.home / ".local/share/codex-pt-br/backups").iterdir())), backup_count)
        for name in (".zprofile", ".zshrc"):
            data = (self.home / name).read_bytes()
            self.assertTrue(data.startswith(original))
            self.assertEqual(data.count(installer.MANAGED_START.encode()), 1)
        dedicated = str(self.launcher.parent.resolve())
        env = {**os.environ, "HOME": str(self.home), "ZDOTDIR": str(self.home),
               "PATH": "/opt/homebrew/bin:/usr/bin:/bin:" + str(self.home / ".local/bin")}
        command = 'source "$HOME/.zprofile"; source "$HOME/.zshrc"; source "$HOME/.zshrc"; print -rl -- "${path[@]}"'
        paths = subprocess.check_output(["/bin/zsh", "-f", "-c", command], env=env, text=True).splitlines()
        self.assertEqual(paths[0], dedicated)
        self.assertEqual(paths.count(dedicated), 1)
        self.assertLess(paths.index("/opt/homebrew/bin"), paths.index(str(self.home / ".local/bin")))

    def test_hash_failure_precedes_all_home_mutations(self):
        (self.home / ".zshrc").write_text("# do not change\n")
        before = installer.path_state(self.home)
        with (self.artifact / installer.ARCHIVE_NAME).open("ab") as output:
            output.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.install()
        self.assertEqual(installer.path_state(self.home), before)

    def test_wrong_build_identity_and_modified_resources_are_rejected(self):
        for key, value in [("version", "0.165.0"), ("target", "x86_64-apple-darwin"),
                           ("upstreamBase", {"tag": "rust-v0.166.0", "commit": "f" * 40})]:
            previous = self.manifest[key]
            self.manifest[key] = value
            self.repack()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.install()
            self.assertEqual(list(self.home.iterdir()), [])
            self.manifest[key] = previous
        (self.package / "bin/codex-exec-server").write_bytes(b"modified helper")
        self.repack()
        with self.assertRaisesRegex(ValueError, "helper or resource changed"):
            self.install()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_escaping_archive_entries_and_links_never_reach_home(self):
        for name, kind in [("../escaped", tarfile.REGTYPE), ("/tmp/escaped", tarfile.REGTYPE),
                           ("locale-packs/link", tarfile.SYMTYPE), ("duplicate", tarfile.LNKTYPE)]:
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "../../escaped" if kind != tarfile.REGTYPE else ""
                payload = b"bad" if kind == tarfile.REGTYPE else b""
                member.size = len(payload)
                self.repack((member, payload))
                with self.assertRaises(ValueError):
                    self.install()
                self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse((self.root / "escaped").exists())

    def test_external_profile_paths_and_symlink_destinations_are_rejected(self):
        outside = self.root / "outside-profile"
        outside.write_text("preserved")
        with self.assertRaises(ValueError):
            self.install(shell_profiles=[outside])
        (self.home / ".zshrc").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(outside.read_text(), "preserved")

    def test_failed_mutation_rolls_back_verified_originals(self):
        (self.home / ".zshrc").write_text("# preserved\n")
        original_replace = installer.replace_path
        attempts = []

        def fail_once(source, destination):
            attempts.append(destination)
            if len(attempts) == 3:
                raise OSError("simulated full disk")
            return original_replace(source, destination)

        with mock.patch.object(installer, "replace_path", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "simulated full disk"):
                self.install()
        self.assertFalse(self.release.exists())
        self.assertFalse((self.home / ".codex/ccu/languages/pt-BR").exists())
        self.assertEqual((self.home / ".zshrc").read_text(), "# preserved\n")

    def test_recovery_rejects_subsequent_user_edits_without_overwriting(self):
        result = self.install()
        profile = self.home / ".zshrc"
        profile.write_text(profile.read_text() + "# later user edit\n")
        before = installer.path_state(self.home)
        with self.assertRaisesRegex(ValueError, "content changed"):
            installer.restore(result["receipt"], self.home)
        self.assertEqual(installer.path_state(self.home), before)

    def test_recovery_can_complete_after_a_process_was_killed(self):
        profile = self.home / ".zshrc"
        profile.write_text("# previous profile\n")
        result = self.install()
        receipt_path = Path(result["receipt"])
        receipt = json.loads(receipt_path.read_text())
        receipt["status"] = "prepared"
        installer.save_receipt(receipt_path, receipt)
        # Simulate the window between removing a backed-up target and renaming.
        profile.unlink()
        installer.restore(receipt_path, self.home)
        self.assertEqual(profile.read_text(), "# previous profile\n")
        self.assertFalse(self.release.exists())
        self.assertFalse(self.launcher.exists())

    def test_cli_prints_concrete_install_and_recovery_receipts(self):
        script = Path(installer.__file__)
        result = json.loads(subprocess.check_output([
            sys.executable, str(script), "--artifact-dir", str(self.artifact),
            "--home", str(self.home), "--official-path", str(self.official),
        ], text=True))
        self.assertTrue(Path(result["receipt"]).is_file())
        receipt = json.loads(Path(result["receipt"]).read_text())
        self.assertEqual(installer.sha256(Path(result["receipt"]).parent / "restore.py"),
                         receipt["restorerSha256"])
        restored = json.loads(subprocess.check_output(shlex.split(result["restoreCommand"]), text=True))
        self.assertEqual(restored["status"], "restored")


if __name__ == "__main__":
    unittest.main()
