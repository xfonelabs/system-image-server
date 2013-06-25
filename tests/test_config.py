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
import tempfile
import unittest

from systemimage import config
from systemimage import tools

try:
    from unittest import mock
except ImportError:
    import mock


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    @mock.patch("subprocess.call")
    def test_config(self, mock_call):
        # Good complete config
        config_path = os.path.join(self.temp_directory, "config")

        with open(config_path, "w+") as fd:
            fd.write("""[global]
base_path = %s
mirrors = a, b

[mirror_default]
ssh_user = user
ssh_key = key
ssh_port = 22
ssh_command = command

[mirror_a]
ssh_host = hosta

[mirror_b]
ssh_host = hostb
""" % self.temp_directory)

        conf = config.Config(config_path)

        # Test ssh sync
        tools.sync_mirrors(conf)
        expected_calls = [((['ssh', '-i', 'key', '-l', 'user',
                             '-p', '22', 'hosta', 'command'],), {}),
                          ((['ssh', '-i', 'key', '-l', 'user',
                             '-p', '22', 'hostb', 'command'],), {})]
        self.assertEquals(mock_call.call_args_list, expected_calls)

        # Invalid config
        invalid_config_path = os.path.join(self.temp_directory,
                                           "invalid_config")
        with open(invalid_config_path, "w+") as fd:
            fd.write("""invalid""")

        self.assertEquals(config.parse_config(invalid_config_path), {})

        self.assertRaises(
            Exception, config.Config, os.path.join(self.temp_directory,
                                                   "invalid"))

        # Empty config
        empty_config_path = os.path.join(self.temp_directory,
                                         "empty_config")
        with open(empty_config_path, "w+") as fd:
            fd.write("")

        conf = config.Config(empty_config_path)
        self.assertEquals(conf.base_path, os.getcwd())

        # Single mirror config
        single_mirror_config_path = os.path.join(self.temp_directory,
                                                 "single_mirror_config")
        with open(single_mirror_config_path, "w+") as fd:
            fd.write("""[global]
mirrors = a

[mirror_default]
ssh_user = user
ssh_key = key
ssh_port = 22
ssh_command = command

[mirror_a]
ssh_host = host
""")

        conf = config.Config(single_mirror_config_path)
        self.assertEquals(conf.mirrors[0].ssh_command, "command")

        # Missing mirror_default
        missing_default_config_path = os.path.join(self.temp_directory,
                                                   "missing_default_config")
        with open(missing_default_config_path, "w+") as fd:
            fd.write("""[global]
mirrors = a

[mirror_a]
ssh_host = host
""")

        self.assertRaises(KeyError, config.Config, missing_default_config_path)

        # Missing mirror key
        missing_key_config_path = os.path.join(self.temp_directory,
                                               "missing_key_config")
        with open(missing_key_config_path, "w+") as fd:
            fd.write("""[global]
mirrors = a

[mirror_default]
ssh_user = user
ssh_port = 22
ssh_command = command

[mirror_a]
ssh_host = host
""")

        self.assertRaises(KeyError, config.Config, missing_key_config_path)

        # Missing mirror
        missing_mirror_config_path = os.path.join(self.temp_directory,
                                                  "missing_mirror_config")
        with open(missing_mirror_config_path, "w+") as fd:
            fd.write("""[global]
mirrors = a

[mirror_default]
ssh_user = user
ssh_port = 22
ssh_command = command
ssh_key = key
""")

        self.assertRaises(KeyError, config.Config, missing_mirror_config_path)

        # Missing ssh_host
        missing_host_config_path = os.path.join(self.temp_directory,
                                                "missing_host_config")
        with open(missing_host_config_path, "w+") as fd:
            fd.write("""[global]
mirrors = a

[mirror_default]
ssh_user = user
ssh_port = 22
ssh_command = command
ssh_key = key

[mirror_a]
ssh_user = other-user
""")

        self.assertRaises(KeyError, config.Config, missing_host_config_path)

        # Test with env path
        test_path = os.path.join(self.temp_directory, "a", "b")
        os.makedirs(os.path.join(test_path, "etc"))
        with open(os.path.join(test_path, "etc", "config"), "w+") as fd:
            fd.write("[global]\nbase_path = a/b/c")
        os.environ['SYSTEM_IMAGE_ROOT'] = test_path
        test_config = config.Config()
        self.assertEquals(test_config.base_path, "a/b/c")
