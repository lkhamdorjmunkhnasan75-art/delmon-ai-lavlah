"""Offline security regression tests. Never contact a provider or real Docker daemon."""
import contextlib
from hashlib import sha256
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from scripts import scan_secrets

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts/scan_secrets.py"
SELECTOR = ROOT / "tests/ci_postgres_container.sh"
IMAGE = "postgres:16@sha256:07abc3f43c9395b0bdbbab36bc25ddb0e8d83cd4fcafb5fb7d6abe14ff156dd8"

def fixture_url(host="fixture.example.test"):
    # Assemble a fake URL only at runtime so the test source is not a credential.
    return ("https://" + "synthetic-user" + ":" + "synthetic-pass" + "@" + host + "/").encode()

class ScannerTests(unittest.TestCase):
    def test_all_supported_patterns(self):
        samples = {
            "private_key": b"-----BEGIN " + b"PRIVATE KEY-----",
            "github_token": b"gh" + b"p_" + b"Z" * 36,
            "aws_access_id": b"AK" + b"IA" + b"Z" * 16,
            "openai_key": b"sk" + b"-" + b"Z" * 32,
            "credential_url": fixture_url(),
        }
        for rule, data in samples.items():
            with self.subTest(rule=rule):
                counts = dict.fromkeys(scan_secrets.RULES, 0)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    scan_secrets.inspect(data, counts, "synthetic-location")
                self.assertEqual(counts[rule], 1)
                self.assertNotIn(data.decode(), output.getvalue(), "fixture leaked")
    def test_clean_content(self):
        counts = dict.fromkeys(scan_secrets.RULES, 0)
        scan_secrets.inspect(b"plain text https://fixture.example.test/path", counts, "test")
        self.assertFalse(any(counts.values()))
    def test_host_classification_never_exempts(self):
        for host, label in (("fixture.example.test", "reserved-test-host"),
                            ("fixture.example.invalid", "other-or-unknown-host")):
            counts = dict.fromkeys(scan_secrets.RULES, 0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                scan_secrets.inspect(fixture_url(host), counts, "test")
            self.assertEqual(counts["credential_url"], 1)
            self.assertIn(label, output.getvalue())
            self.assertNotIn(host, output.getvalue(), "hostname leaked")
            self.assertNotIn("synthetic-pass", output.getvalue(), "fixture leaked")

class ScannerRepository(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        for key in tuple(self.env):
            if key.startswith("GIT_") and key not in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"):
                self.env.pop(key)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.test")
        self.git("config", "user.name", "Synthetic Fixture")
        self.git("config", "commit.gpgsign", "false")
        self.file = self.repo / "fixture.txt"
        self.file.write_bytes(b"clean")
        self.commit()
    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    def commit(self):
        self.git("add", "fixture.txt")
        self.git("commit", "-qm", "synthetic test")
    def scan(self, cwd=None):
        result = subprocess.run([sys.executable, str(SCANNER)], cwd=cwd or self.repo,
                                env=self.env, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        self.assertNotIn("synthetic-pass", output, "fixture leaked")
        self.assertNotIn("fixture.example.test", output, "hostname leaked")
        return result.returncode, output


class HistoryTests(ScannerRepository):
    def test_clean_repository(self):
        code, output = self.scan()
        self.assertEqual(code, 0)
        self.assertIn("Reachable historical blobs scanned:", output)
    def test_tracked_uncommitted_secret(self):
        self.file.write_bytes(fixture_url())
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("tracked path sha256=", output)
        self.assertNotIn("historical blob=", output)
    def test_deleted_secret_still_blocks(self):
        self.file.write_bytes(fixture_url())
        self.commit()
        self.file.write_bytes(b"clean again")
        self.commit()
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertNotIn("tracked path sha256=", output)
        self.assertIn("historical blob=", output)
    def test_secret_on_other_ref(self):
        self.git("checkout", "-qb", "fixture-branch")
        self.file.write_bytes(fixture_url())
        self.commit()
        self.git("checkout", "-q", "-")
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("historical blob=", output)
    def test_shallow_repository_denied(self):
        dest = self.repo.parent / (self.repo.name + "-shallow")
        self.addCleanup(__import__("shutil").rmtree, dest, True)
        self.git("clone", "-q", "--depth", "1", self.repo.as_uri(), str(dest))
        code, output = self.scan(dest)
        self.assertNotEqual(code, 0)
        self.assertIn("Full reachable history required", output)

class ReviewedHistoryTests(ScannerRepository):
    # Use two approved synthetic blobs in a disposable repository. Python CI
    # can run these tests even when the project checkout is shallow.
    def setUp(self):
        super().setUp()
        self.dispositions = {}
        for content in (b"first\n" + fixture_url(), b"second\n" + fixture_url()):
            self.file.write_bytes(content)
            self.commit()
            blob = self.git("rev-parse", "HEAD:fixture.txt").stdout.decode().strip()
            commit = self.git("rev-parse", "HEAD").stdout.decode().strip()
            self.dispositions[blob] = (sha256(content).hexdigest(), commit, "fixture.txt", 2)
        self.file.write_bytes(b"clean")
        self.commit()

    def reviewed_scan(self):
        program = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from scripts import scan_secrets; from ast import literal_eval; "
            "scan_secrets.REVIEWED_HISTORY = literal_eval(sys.argv[2]); "
            "sys.exit(scan_secrets.main(apply_reviewed_history=True))"
        )
        result = subprocess.run([sys.executable, "-B", "-c", program, str(ROOT), repr(self.dispositions)],
                                cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        self.assertNotIn("synthetic-pass", output)
        self.assertNotIn("fixture.example.test", output)
        return result.returncode, output

    def test_only_reviewed_history_passes(self):
        code, output = self.reviewed_scan()
        self.assertEqual(code, 0, output)
        self.assertIn("'credential_url': 2", output)
        for blob in self.dispositions:
            self.assertIn("Credential URL candidate: historical blob=" + blob, output)
            self.assertIn("Reviewed historical credential URL: " + blob, output)
        self.assertEqual(self.scan()[0], 1)

    def test_tracked_copy_of_reviewed_blob_blocks(self):
        self.file.write_bytes(b"first\n" + fixture_url())
        code, output = self.reviewed_scan()
        self.assertEqual(code, 1, output)
        self.assertIn("tracked path sha256=", output)

    def test_unreviewed_historical_url_blocks(self):
        self.git("switch", "-qc", "extra-history")
        self.file.write_bytes(b"first\n" + fixture_url() + b"\ncopy")
        self.commit()
        self.file.write_bytes(fixture_url().replace(b"synthetic-pass", b"different-password"))
        self.commit()
        self.git("switch", "-q", "-")
        code, output = self.reviewed_scan()
        self.assertEqual(code, 1, output)
        self.assertIn("'credential_url': 4", output)
        self.assertNotIn("different-password", output)

    def test_exact_blob_at_new_historical_path_blocks(self):
        copy = self.repo / "copied.txt"
        copy.write_bytes(b"first\n" + fixture_url())
        self.git("add", "copied.txt")
        self.commit()
        self.git("rm", "copied.txt")
        self.commit()
        code, output = self.reviewed_scan()
        self.assertEqual(code, 1, output)
        self.assertIn("Historical disposition did not match:", output)

    def test_new_token_blocks(self):
        token = b"gh" + b"p_" + b"Z" * 36
        self.file.write_bytes(token)
        code, output = self.reviewed_scan()
        self.assertEqual(code, 1, output)
        self.assertIn("'github_token': 1", output)
        self.assertNotIn(token.decode(), output)

    def test_disposition_mismatch_blocks(self):
        blob = next(iter(self.dispositions))
        digest, commit, path, line = self.dispositions[blob]
        self.dispositions[blob] = ("0" * len(digest), commit, path, line)
        code, output = self.reviewed_scan()
        self.assertEqual(code, 1, output)
        self.assertIn("Historical disposition did not match: " + blob, output)


class ContainerSelectorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        docker = root / "docker"
        docker.write_text("""#!/bin/bash
case "$1" in
image) printf '%s\\n' "$MOCK_IMAGE_ID";;
ps) printf '%s\\n' "$MOCK_CONTAINERS";;
inspect) printf '%s\\n' "$MOCK_ACTUAL_ID";;
*) exit 99;;
esac
""")
        docker.chmod(0o700)
        self.env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ["PATH"],
                        CI="true", GITHUB_ACTIONS="true", PGHOST="localhost",
                        PGDATABASE="postgres", PGUSER="postgres",
                        LAVLAH_POSTGRES_IMAGE=IMAGE, MOCK_IMAGE_ID="sha256:"+"a"*64,
                        MOCK_ACTUAL_ID="sha256:"+"a"*64, MOCK_CONTAINERS="abcdef012345")
    def run_selector(self, **changes):
        return subprocess.run(["bash", str(SELECTOR)], env=self.env | changes,
                              capture_output=True, text=True, timeout=5)
    def test_expected_single_container(self):
        result = self.run_selector()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "abcdef012345")
    def test_wrong_ci_context(self):
        for change in ({"CI":"false"}, {"GITHUB_ACTIONS":"false"}, {"PGHOST":"remote"},
                       {"PGDATABASE":"production"}, {"PGUSER":"other"}):
            with self.subTest(change=change):
                self.assertNotEqual(self.run_selector(**change).returncode, 0)
    def test_wrong_digest(self):
        self.assertNotEqual(self.run_selector(LAVLAH_POSTGRES_IMAGE="postgres:16").returncode, 0)
    def test_zero_or_multiple_containers(self):
        for value in ("", "abcdef012345\nabcdef678901"):
            self.assertNotEqual(self.run_selector(MOCK_CONTAINERS=value).returncode, 0)
    def test_invalid_or_mismatched_image_id(self):
        for change in ({"MOCK_IMAGE_ID":"not-a-digest"}, {"MOCK_ACTUAL_ID":"sha256:"+"b"*64}):
            self.assertNotEqual(self.run_selector(**change).returncode, 0)
