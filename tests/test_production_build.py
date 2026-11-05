"""Build guards use synthetic archives; no index access or package install."""
import importlib.util
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('production_build', ROOT / 'scripts/production/build_release.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class ProductionBuildTests(unittest.TestCase):
    def archive(self, name='safe/file.txt', *, link=False):
        value = io.BytesIO()
        with tarfile.open(fileobj=value, mode='w') as archive:
            info = tarfile.TarInfo(name)
            if link:
                info.type = tarfile.SYMTYPE
                info.linkname = '/private'
                archive.addfile(info)
            else:
                info.size = 3
                archive.addfile(info, io.BytesIO(b'abc'))
        return value.getvalue()

    def test_safe_archive_extracts_data_privately_and_no_code_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build.extract_archive(self.archive(), root)
            self.assertEqual((root / 'safe/file.txt').read_bytes(), b'abc')
            if os.name == 'posix':
                self.assertEqual((root / 'safe/file.txt').stat().st_mode & 0o777, 0o600)

    def test_traversal_absolute_links_rejected(self):
        for name, link in (('../private', False), ('/absolute', False), ('safe/link', True), ('..\\private', False)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(build.BuildError):
                    build.extract_archive(self.archive(name, link=link), Path(directory))

    def test_build_requires_exact_commit_and_explicit_installed_toolchain(self):
        calls = []
        for commit, tools in (('main', {}), ('a' * 40, {})):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(build.BuildError):
                build.build(Path(directory), commit, Path(directory) / 'new', tools,
                            runner=lambda *a, **k: calls.append(a))
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
