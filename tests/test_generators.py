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

from systemimage import config, generators, tree

import os
import shutil
import tempfile
import unittest


class GeneratorsTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory

        os.mkdir(os.path.join(self.temp_directory, "etc"))
        config_path = os.path.join(self.temp_directory, "etc", "config")
        with open(config_path, "w+") as fd:
            fd.write("""[global]
base_path = %s
gpg_key_path = %s
public_fqdn = system-image.example.net
public_http_port = 880
public_https_port = 8443
""" % (self.temp_directory, os.path.join(os.getcwd(), "tests", "keys")))
        self.config = config.Config(config_path)

        os.mkdir(os.path.join(self.temp_directory, "www"))
        self.tree = tree.Tree(self.config)
        self.tree.create_channel("test")
        self.tree.create_device("test", "test")
        self.device = self.tree.get_device("test", "test")

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    def test_unpack_arguments(self):
        self.assertEquals(generators.unpack_arguments("a=1,b=2"),
                          {'a': "1", 'b': "2"})
        self.assertEquals(generators.unpack_arguments("a=1,b=2,c"),
                          {'a': "1", 'b': "2"})

    def test_generate_file(self):
        self.assertRaises(Exception, generators.generate_file, self.config,
                          "invalid", [], {})

    def test_generate_file_version(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Ensure we don't generate a new tarball when there are no changes
        environment['new_files'] = []
        self.assertEquals(
            generators.generate_file(self.config, "version", [], environment),
            None)

        # Do a standard run
        environment['new_files'] = ["some-file.tar.xz"]
        self.assertEquals(
            generators.generate_file(self.config, "version", [], environment),
            os.path.realpath(os.path.join(self.device.path,
                             "version-%s.tar.xz" % environment['version'])))

        # Go through the cache code path
        environment['new_files'] = ["some-file.tar.xz"]
        self.assertEquals(
            generators.generate_file(self.config, "version", [], environment),
            os.path.realpath(os.path.join(self.device.path,
                             "version-%s.tar.xz" % environment['version'])))

        # Confirm pool creation
        environment['new_files'] = ["some-file.tar.xz"]
        shutil.rmtree(self.device.path)
        self.assertEquals(
            generators.generate_file(self.config, "version", [], environment),
            os.path.realpath(os.path.join(self.device.path,
                             "version-%s.tar.xz" % environment['version'])))
