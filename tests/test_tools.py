# -*- coding: utf-8 -*-

# Copyright (C) 2013 Canonical Ltd.
# Author: Stéphane Graber <stgraber@ubuntu.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import shutil
import tarfile
import tempfile
import unittest

from systemimage import tools


class ToolTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory
        self.old_path = os.environ.get("PATH", None)

    def tearDown(self):
        shutil.rmtree(self.temp_directory)
        if self.old_path:
            os.environ['PATH'] = self.old_path

    def test_generate_version_tarball(self):
        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(version_tarball, "1.2.3.4",
                                       "a/b/version")

        version_tarfile = tarfile.open(version_tarball, "r:")
        version_file = version_tarfile.extractfile("a/b/version")
        self.assertTrue(version_file)

        self.assertEquals(version_file.read().decode('utf-8'), "1.2.3.4\n")

    def test_gzip_compress(self):
        test_string = "test-string"

        # Simple compress/uncompress
        test_file = "%s/test.txt" % self.temp_directory
        with open(test_file, "w+") as fd:
            fd.write(test_string)

        self.assertEquals(tools.gzip_compress(test_file), "%s.gz" % test_file)
        self.assertTrue(os.path.exists("%s.gz" % test_file))

        os.remove(test_file)
        self.assertFalse(os.path.exists(test_file))

        self.assertEquals(tools.gzip_uncompress("%s.gz" % test_file),
                          test_file)
        self.assertTrue(os.path.exists(test_file))

        with open(test_file, "r") as fd:
            self.assertEquals(fd.read(), test_string)

        self.assertRaises(Exception, tools.gzip_compress, test_file)
        self.assertRaises(Exception, tools.gzip_uncompress,
                          "%s.gz" % test_file)
        self.assertRaises(Exception, tools.gzip_uncompress, test_file)

    def test_xz_compress(self):
        test_string = "test-string"

        # Simple compress/uncompress
        test_file = "%s/test.txt" % self.temp_directory
        with open(test_file, "w+") as fd:
            fd.write(test_string)

        self.assertEquals(tools.xz_compress(test_file), 0)
        self.assertTrue(os.path.exists("%s.xz" % test_file))

        os.remove(test_file)
        self.assertFalse(os.path.exists(test_file))

        self.assertEquals(tools.xz_uncompress("%s.xz" % test_file), 0)
        self.assertTrue(os.path.exists(test_file))

        with open(test_file, "r") as fd:
            self.assertEquals(fd.read(), test_string)

        self.assertRaises(Exception, tools.xz_compress, test_file)
        self.assertRaises(Exception, tools.xz_uncompress, "%s.xz" % test_file)
        self.assertRaises(Exception, tools.xz_uncompress, test_file)

    # Imported from cdimage.osextras
    def test_find_on_path_missing_environment(self):
        os.environ.pop("PATH", None)
        self.assertFalse(tools.find_on_path("ls"))

    def test_find_on_path_present_executable(self):
        bin_dir = os.path.join(self.temp_directory, "bin")
        os.mkdir(bin_dir)
        program = os.path.join(bin_dir, "program")
        open(program, "w+").close()
        os.chmod(program, 0o755)
        os.environ["PATH"] = "::%s" % bin_dir
        self.assertTrue(tools.find_on_path("program"))

    def test_find_on_path_present_not_executable(self):
        bin_dir = os.path.join(self.temp_directory, "bin")
        os.mkdir(bin_dir)
        program = os.path.join(bin_dir, "program")
        open(program, "w+").close()
        os.environ["PATH"] = bin_dir
        self.assertFalse(tools.find_on_path("program"))
