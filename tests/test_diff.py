import os
import shutil
import sys
import tarfile
import tempfile
import unittest

from io import BytesIO, StringIO
from phablet.diff import ImageDiff, compare_files


class DiffTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()

        source_tarball_path = "%s/source.tar" % temp_directory
        target_tarball_path = "%s/target.tar" % temp_directory

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

        # Dangling symlink
        j = tarfile.TarInfo()
        j.name = "c/j"
        j.type = tarfile.SYMTYPE
        j.linkname = "j_non-existent"

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
        target_tarball.addfile(j)

        source_tarball.close()
        target_tarball.close()

        self.imagediff = ImageDiff(source_tarball_path, target_tarball_path)
        self.source_tarball_path = source_tarball_path
        self.target_tarball_path = target_tarball_path
        self.temp_directory = temp_directory

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    def test_content(self):
        content_set, content_dict = self.imagediff.scan_content("source")
        self.assertEquals(sorted(content_dict.keys()),
                          ['a', 'b', 'c', 'c/d', 'c/g', 'c/h'])

        content_set, content_dict = self.imagediff.scan_content("target")
        self.assertEquals(sorted(content_dict.keys()),
                          ['a', 'c', 'c/a_i', 'c/c', 'c/d', 'c/g', 'c/h',
                           'c/j', 'e', 'f'])

    def test_content_invalid_image(self):
        self.assertRaises(KeyError, self.imagediff.scan_content, "invalid")

    def test_compare_files(self):
        missing_file = "%s/missing" % self.temp_directory
        self.assertEquals(compare_files(missing_file, missing_file), None)

        same_symlink = "%s/symlink" % self.temp_directory
        os.symlink("/a/b/c", same_symlink)
        self.assertEquals(compare_files(same_symlink, same_symlink), True)

        # Redirect output
        old_stderr = sys.stderr
        if sys.version[0] == "3":
            sys.stderr = StringIO()
        else:
            sys.stderr = BytesIO()

        good_file = "%s/good-file" % self.temp_directory
        open(good_file, "w+").close()
        unreadable_file = "%s/unreadable-file" % self.temp_directory
        open(unreadable_file, "w+").close()
        os.chmod(unreadable_file, 0o000)
        self.assertEquals(compare_files(unreadable_file, good_file), False)
        self.assertEquals(compare_files(good_file, unreadable_file), False)

        # Unredirect output
        output = sys.stderr.getvalue()
        sys.stderr = old_stderr

        self.assertEquals("Unable to hash: %s\nUnable to hash: %s\n" %
                          (unreadable_file, unreadable_file), output)

        self.assertEquals(compare_files(same_symlink, good_file), False)
        self.assertEquals(compare_files(good_file, same_symlink), False)

    def test_compare_image(self):
        diff_set = self.imagediff.compare_images()
        self.assertTrue(("c/a_i", "add") in diff_set)

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
 - c/j (add)
 - e (add)
 - f (add)
""")

    def test_generate_tarball(self):
        output_tarball = "%s/output.tar" % self.temp_directory

        self.imagediff.generate_diff_tarball(output_tarball)
        tarball = tarfile.open(output_tarball, "r")

        files_list = [entry.name for entry in tarball]
        self.assertEquals(files_list, ['removed', 'c/c', 'c/a_i', 'c/d', 'c/j',
                                       'e', 'f'])
