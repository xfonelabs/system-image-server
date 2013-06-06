import glob
import os
import shutil
import tarfile
import tempfile
import unittest

from systemimage import tools


class DiffTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    def test_generate_version_tarball(self):
        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(version_tarball, "1.2.3.4",
                                       "a/b/version")

        version_tarfile = tarfile.open(version_tarball, "r:")
        version_file = version_tarfile.extractfile("a/b/version")
        self.assertTrue(version_file)

        self.assertEquals(version_file.read().decode('utf-8'), "1.2.3.4")

    def test_xz_compress(self):
        test_string = "test-string"

        # Simple compress/uncompress
        test_file = "%s/test.txt" % self.temp_directory
        with open(test_file, "w+") as fd:
            fd.write(test_string)

        self.assertEquals(tools.xz_compress(test_file), 0)
        self.assertTrue(os.path.exists("%s.xz" % test_file))

        os.remove(test_file)
        self.assertTrue(not os.path.exists(test_file))

        self.assertEquals(tools.xz_uncompress("%s.xz" % test_file), 0)
        self.assertTrue(os.path.exists(test_file))

        with open(test_file, "r") as fd:
            self.assertEquals(fd.read(), test_string)

        self.assertRaises(Exception, tools.xz_compress, test_file)
        self.assertRaises(Exception, tools.xz_uncompress, "%s.xz" % test_file)
        self.assertRaises(Exception, tools.xz_uncompress, test_file)
