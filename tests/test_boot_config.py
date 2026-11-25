import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("build_assets", SCRIPTS / "build-assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class BootConfigTest(unittest.TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        self.root = Path(storage.name)
        self.game = self.root / "Risk of Rain 2_Data"
        self.game.mkdir()
        self.private = self.root / "kit"
        self.prepared = self.private / "assets" / assets.DATA / "boot.config"
        self.prepared.parent.mkdir(parents=True)
        # Only this synthetic Windows input hash is substituted. The output
        # hashes for both Mac architectures come from the shipping manifest.
        raw = b"hdr-display-enabled=0\nwait-for-native-debugger=0\n"
        (self.game / "boot.config").write_bytes(raw)
        row = next(item for item in assets.load_manifest() if item["path"] == "boot.config")
        self.row = dict(row, input_sha256=hashlib.sha256(raw).hexdigest())

    def build(self, arch):
        output = Path(tempfile.mkdtemp(dir=self.root)) / "Test.app"
        with patch.object(assets, "load_manifest", return_value=[self.row]):
            assets.prepare_assets(self.game, output, self.private, None, False, arch=arch)
        config = (output / assets.DATA / "boot.config").read_bytes()
        self.assertEqual(hashlib.sha256(config).hexdigest(), self.row.get(arch, self.row)["sha256"])
        return config

    def test_fresh_and_prepared_inputs_use_target_architecture(self):
        arm = self.build("arm64")
        intel = self.build("x86_64")
        self.assertEqual(arm.splitlines()[0], b"force-gfx-direct=1")
        self.assertEqual(intel.splitlines()[0], b"gfx-threading-mode=4")
        self.assertEqual(arm.splitlines()[1:], intel.splitlines()[1:])
        (self.game / "boot.config").unlink()
        for prepared in (intel, arm):
            self.prepared.write_bytes(prepared)
            for arch, expected in (("arm64", arm), ("x86_64", intel)):
                with self.subTest(arch=arch, prepared=prepared.splitlines()[0]):
                    self.assertEqual(self.build(arch), expected)

    def test_rejects_unrecognized_prepared_config(self):
        self.prepared.write_bytes(b"force-gfx-direct=1\n")
        with self.assertRaisesRegex(ValueError, "Asset differs"):
            self.build("arm64")


if __name__ == "__main__":
    unittest.main()
