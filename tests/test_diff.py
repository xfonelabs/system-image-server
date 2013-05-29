import os
import sys
import tarfile
import tempfile
import unittest

from io import BytesIO, StringIO
from phablet.diff import ImageDiff

class DiffTests(unittest.TestCase):
    def setUp(self):
        fd, source_tarball_path = tempfile.mkstemp()
        os.close(fd)
        fd, target_tarball_path = tempfile.mkstemp()
        os.close(fd)
        fd, output_tarball_path = tempfile.mkstemp()
        os.close(fd)

        source_tarball = tarfile.open(source_tarball_path, "w")
        target_tarball = tarfile.open(target_tarball_path, "w")

        # Standard file
        a = tarfile.TarInfo()
        a.name = "a"
        a.size = 4

        # Standard file
        b = tarfile.TarInfo()
        b.name = "b"
        b.size = 4

        # Standard directory
        c_dir = tarfile.TarInfo()
        c_dir.name = "c"
        c_dir.type = tarfile.DIRTYPE
        c_dir.mode = 0o755

        # Standard file
        c = tarfile.TarInfo()
        c.name = "c/c"
        c.size = 4

        # Standard file
        d_source = tarfile.TarInfo()
        d_source.name = "c/d"
        d_source.size = 8
        d_source.mtime = 1000

        # Standard file
        d_target = tarfile.TarInfo()
        d_target.name = "c/d"
        d_target.size = 8
        d_target.mtime = 1234

        # Symlink
        e = tarfile.TarInfo()
        e.name = "e"
        e.type = tarfile.SYMTYPE
        e.linkname = "a"

        # Hard link
        f = tarfile.TarInfo()
        f.name = "f"
        f.type = tarfile.LNKTYPE
        f.linkname = "a"

        # Standard file
        g_source = tarfile.TarInfo()
        g_source.name = "c/g"
        g_source.size = 4
        g_source.mtime = 1000

        # Standard file
        g_target = tarfile.TarInfo()
        g_target.name = "c/g"
        g_target.size = 4
        g_target.mtime = 1001

        # Hard link
        h_source = tarfile.TarInfo()
        h_source.name = "c/h"
        h_source.type = tarfile.LNKTYPE
        h_source.linkname = "d"
        h_source.mtime = 1000

        # Hard link
        h_target = tarfile.TarInfo()
        h_target.name = "c/h"
        h_target.type = tarfile.LNKTYPE
        h_target.linkname = "d"
        h_target.mtime = 1001

        # Hard link
        i = tarfile.TarInfo()
        i.name = "c/a_i"
        i.type = tarfile.LNKTYPE
        i.linkname = "c"

        source_tarball.addfile(a, BytesIO(b"test"))
        source_tarball.addfile(b, BytesIO(b"test"))
        source_tarball.addfile(c_dir)
        source_tarball.addfile(d_source, BytesIO(b"test-abc"))
        source_tarball.addfile(g_source, BytesIO(b"test"))
        source_tarball.addfile(h_source, BytesIO(b"test"))

        target_tarball.addfile(a, BytesIO(b"test"))
        target_tarball.addfile(c_dir)
        target_tarball.addfile(c, BytesIO(b"test"))
        target_tarball.addfile(d_target, BytesIO(b"test-def"))
        target_tarball.addfile(e)
        target_tarball.addfile(f)
        target_tarball.addfile(g_target, BytesIO(b"test"))
        target_tarball.addfile(h_target, BytesIO(b"test"))
        target_tarball.addfile(i)

        source_tarball.close()
        target_tarball.close()

        self.imagediff = ImageDiff(source_tarball_path, target_tarball_path)
        self.source_tarball_path = source_tarball_path
        self.target_tarball_path = target_tarball_path
        self.output_tarball_path = output_tarball_path

    def tearDown(self):
        os.remove(self.source_tarball_path)
        os.remove(self.target_tarball_path)
        os.remove(self.output_tarball_path)

    def test_content(self):
        content_set, content_dict = self.imagediff.scan_content("source")
        self.assertEquals(sorted(content_dict.keys()),
                          ['a', 'b', 'c', 'c/d', 'c/g', 'c/h'])

        content_set, content_dict = self.imagediff.scan_content("target")
        self.assertEquals(sorted(content_dict.keys()),
                          ['a', 'c', 'c/a_i', 'c/c', 'c/d', 'c/g', 'c/h', 'e',
                           'f'])

    def test_content_invalid_image(self):
        self.assertRaises(KeyError, self.imagediff.scan_content, "invalid")

    def test_compare(self):
        diff_set = self.imagediff.compare_images()

    def test_print_changes(self):
        # Redirect stdout
        old_stdout = sys.stdout

        #FIXME: Would be best to have something that works with both version
        if sys.version[0] == "3":
            sys.stdout = StringIO()
        else:
            sys.stdout = BytesIO()

        self.imagediff.print_changes()

        # Unredirect stdout
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        self.assertEquals(output, """ - b (del)
 - c/a_i (add)
 - c/c (add)
 - c/d (mod)
 - e (add)
 - f (add)
""")

    def test_generate_tarball(self):
        self.imagediff.generate_diff_tarball(self.output_tarball_path)
        tarball = tarfile.open(self.output_tarball_path, "r")

        files_list = [entry.name for entry in tarball]
        self.assertEquals(files_list, ['removed', 'c/c', 'c/a_i', 'c/d', 'e',
                                       'f'])
