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

from systemimage import tree
from systemimage import gpg


class TreeTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    def test_channels(self):
        # Test getting a tree instance
        test_tree = tree.Tree(self.temp_directory)
        self.assertEquals(test_tree.list_channels(), {})

        # Test invalid tree path
        self.assertRaises(Exception, tree.Tree,
                          os.path.join(self.temp_directory, "invalid"))

        # Test channel creation
        test_tree.create_channel("first")
        test_tree.create_channel("second")

        self.assertRaises(KeyError, test_tree.create_channel, "second")

        # Test channel removal
        test_tree.remove_channel("first")
        test_tree.remove_channel("second")

        self.assertRaises(KeyError, test_tree.remove_channel, "second")

        # Test invalid json
        with open(test_tree.indexpath, "w+") as fd:
            fd.write("[]")

        self.assertRaises(TypeError, test_tree.list_channels)

        with open(test_tree.indexpath, "w+") as fd:
            fd.write("{'a': 'a'}")
        self.assertRaises(ValueError, test_tree.list_channels)

        os.remove(test_tree.indexpath)

        # Test device creation
        test_tree.create_channel("testing")
        test_tree.create_device("testing", "test")

        self.assertTrue(
            os.path.exists(os.path.join(self.temp_directory,
                                        "testing/test/index.json")))

        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'test':
                                       {'index': '/testing/test/index.json'}}})

        self.assertRaises(KeyError, test_tree.create_device, "invalid", "test")
        self.assertRaises(KeyError, test_tree.create_device, "testing", "test")

        # Test the index generation
        os.mkdir(os.path.join(self.temp_directory, "testing", "empty"))
        self.assertRaises(Exception, test_tree.generate_index)
        test_tree.generate_index("I know what I'm doing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'test':
                                       {'index': '/testing/test/index.json'}}})

        device_keyring = os.path.join(self.temp_directory, "testing",
                          "test", "device.tar.xz")
        open(device_keyring, "w+").close()

        test_tree.generate_index("I know what I'm doing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'test':
                                       {'index': '/testing/test/index.json'}}})

        gpg.sign_file("signing", device_keyring)
        test_tree.generate_index("I know what I'm doing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'test':
                                       {'index': '/testing/test/index.json',
                                        'keyring':
                                       {'path': '/testing/test/device.tar.xz',
                                        'signature': '/testing/test/'
                                                     'device.tar.xz.asc'}}}})


        # Test grabbing a device entry
        self.assertRaises(KeyError, test_tree.get_device, "invalid", "test")
        self.assertRaises(KeyError, test_tree.get_device, "testing", "invalid")
        self.assertTrue(isinstance(test_tree.get_device("testing", "test"),
                                   tree.Device))

        # Test device removal
        test_tree.create_device("testing", "to-remove")
        self.assertTrue(
            os.path.exists(os.path.join(self.temp_directory,
                                        "testing/to-remove/index.json")))
        self.assertRaises(KeyError, test_tree.remove_device, "invalid", "test")
        self.assertRaises(KeyError, test_tree.remove_device, "testing",
                          "invalid")
        test_tree.remove_device("testing", "to-remove")
        self.assertFalse(
            os.path.exists(os.path.join(self.temp_directory,
                                        "testing/to-remove/index.json")))

        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'test':
                                       {'index': '/testing/test/index.json',
                                        'keyring':
                                       {'path': '/testing/test/device.tar.xz',
                                        'signature': '/testing/test/'
                                                     'device.tar.xz.asc'}}}})

        # Test setting the device keyring
        self.assertRaises(KeyError, test_tree.set_device_keyring, "invalid",
                          "test", "invalid")
        self.assertRaises(KeyError, test_tree.set_device_keyring, "testing",
                          "invalid", "invalid")
        test_tree.set_device_keyring("testing", "test",
                                     "testing/test/device.tar.xz")
        self.assertRaises(Exception, test_tree.set_device_keyring, "testing",
                          "test", "invalid")

        unsigned_path = os.path.join(self.temp_directory, "unsigned")
        open(unsigned_path, "w+").close()
        self.assertRaises(Exception, test_tree.set_device_keyring, "testing",
                          "test", "unsigned")
        os.remove(unsigned_path)
