import os
import shutil
import sys
import tarfile
import tempfile
import unittest

from io import BytesIO, StringIO
from phablet.tools import generate_version_tarball


class DiffTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    def test_generate_version_tarball(self):
        version_tarball = "%s/version.tar" % self.temp_directory
        generate_version_tarball(version_tarball, "1.2.3.4", "a/b/version")

        version_tarfile = tarfile.open(version_tarball, "r:")
        version_file = version_tarfile.extractfile("a/b/version")
        self.assertTrue(version_file)

        self.assertEquals(version_file.read().decode('utf-8'), "1.2.3.4")
