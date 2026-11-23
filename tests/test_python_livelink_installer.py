"""Installer version guards, lock use, idempotence and rollback on write error."""
from pathlib import Path
from contextlib import contextmanager
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT))
import apply_python_livelink as installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name); (self.root/'mocap').mkdir()
        self.stream=self.root/'mocap/stream_ui.py'
        self.original=(ROOT/'tests/fixtures/stream_vmc_baseline.py.txt').read_bytes()
        self.stream.write_bytes(self.original)
        self.locked=False
        @contextmanager
        def app_lock(root):
            self.assertEqual(root,self.root); self.locked=True; yield
        mod=types.ModuleType('tools.session_lock'); mod.app_lock=app_lock
        self.modules=patch.dict(sys.modules,{'tools':types.ModuleType('tools'),'tools.session_lock':mod})
        self.modules.start()
    def tearDown(self):
        self.modules.stop(); self.temp.cleanup()

    def test_install_lock_and_idempotence(self):
        installer.install(self.root,True); self.assertFalse(self.locked)
        self.assertEqual(self.stream.read_bytes(),self.original)
        installer.install(self.root); self.assertTrue(self.locked)
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        installer.install(self.root)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertIn(installer.MARKER,self.stream.read_text())
        self.assertTrue(list((self.root/'local_patches').rglob('manifest.json')))

    def test_reject_unknown_source_or_existing_module(self):
        self.stream.write_text(self.stream.read_text()+'\n# changed\n')
        with self.assertRaises(ValueError): installer.install(self.root)
        self.stream.write_bytes(self.original)
        (self.root/installer.FILES[0]).write_text('user changes')
        with self.assertRaises(ValueError): installer.install(self.root)
        self.assertFalse(self.locked)

    def test_rollback(self):
        write=Path.write_bytes; fail_path=self.root/installer.FILES[2]
        def failing(path,data):
            if path==fail_path: raise OSError('simulated disk failure')
            return write(path,data)
        with patch.object(Path,'write_bytes',failing):
            with self.assertRaises(OSError): installer.install(self.root)
        self.assertEqual(self.stream.read_bytes(),self.original)
        self.assertTrue(all(not (self.root/name).exists() for name in installer.FILES))

if __name__=='__main__': unittest.main(verbosity=2)
