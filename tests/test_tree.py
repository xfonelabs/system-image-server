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

import json
import os
import shutil
import tempfile
import unittest

from systemimage import config, gpg, tree, tools


class TreeTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory

        os.mkdir(os.path.join(self.temp_directory, "etc"))
        config_path = os.path.join(self.temp_directory, "etc", "config")
        with open(config_path, "w+") as fd:
            fd.write("""[global]
base_path = %s
gpg_key_path = %s
public_fqdn = example.net
public_http_port = 80
public_https_port = 443
""" % (self.temp_directory, os.path.join(os.getcwd(), "tests", "keys")))
        self.config = config.Config(config_path)
        os.makedirs(self.config.publish_path)

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    @unittest.skipIf(not os.path.exists("tests/keys/generated"),
                     "No GPG testing keys present. Run tests/generate-keys")
    def test_channels(self):
        # Test getting a tree instance
        test_tree = tree.Tree(self.config)
        self.assertEquals(test_tree.list_channels(), {})

        # Test publishing a keyring
        keyring = gpg.Keyring(self.config, "image-signing")
        keyring.set_metadata("image-signing")
        keyring.import_keys(os.path.join(self.config.gpg_key_path,
                            "image-signing"))
        self.assertRaises(Exception, test_tree.publish_keyring,
                          "image-signing")
        keyring_tar = keyring.generate_tarball()
        tools.xz_compress(keyring_tar)
        self.assertRaises(Exception, test_tree.publish_keyring,
                          "image-signing")
        gpg.sign_file(self.config, "image-master", "%s.xz" % keyring_tar)
        test_tree.publish_keyring("image-signing")

        self.assertTrue(os.path.exists(os.path.join(self.config.publish_path,
                                                    "gpg", "image-signing"
                                                           ".tar.xz")))

        self.assertTrue(os.path.exists(os.path.join(self.config.publish_path,
                                                    "gpg", "image-signing"
                                                           ".tar.xz.asc")))

        # Test invalid tree path
        self.assertRaises(Exception, tree.Tree, self.config,
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

        # Test hidding a channel
        test_tree.create_channel("testing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices': {}}})

        test_tree.hide_channel("testing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices': {},
                                        'hidden': True}})

        test_tree.show_channel("testing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices': {}}})

        self.assertRaises(KeyError, test_tree.hide_channel, "invalid")
        self.assertRaises(KeyError, test_tree.show_channel, "invalid")
        test_tree.remove_channel("testing")

        # Test device creation
        test_tree.create_channel("testing")
        test_tree.create_device("testing", "test")

        self.assertTrue(
            os.path.exists(os.path.join(self.config.publish_path,
                                        "testing", "test", "index.json")))

        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices':
                                        {'test': {
                                         'index': '/testing/test/'
                                                  'index.json'}}}})

        self.assertRaises(KeyError, test_tree.create_device, "invalid", "test")
        self.assertRaises(KeyError, test_tree.create_device, "testing", "test")

        # Test the index generation
        os.mkdir(os.path.join(self.config.publish_path, "testing", "empty"))
        self.assertRaises(Exception, test_tree.generate_index)
        test_tree.generate_index("I know what I'm doing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices':
                                        {'test': {
                                         'index': '/testing/test/'
                                                  'index.json'}}}})

        device_keyring = os.path.join(self.config.publish_path, "testing",
                                      "test", "device.tar.xz")
        open(device_keyring, "w+").close()

        test_tree.generate_index("I know what I'm doing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices':
                                        {'test': {
                                         'index': '/testing/test/'
                                                  'index.json'}}}})

        gpg.sign_file(self.config, "image-signing", device_keyring)
        test_tree.generate_index("I know what I'm doing")
        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices':
                                        {'test': {
                                         'index': '/testing/test/index.json',
                                         'keyring': {
                                             'path': '/testing/test/'
                                                     'device.tar.xz',
                                             'signature': '/testing/test/'
                                                          'device.tar'
                                                          '.xz.asc'}}}}})

        # Test grabbing a device entry
        self.assertRaises(KeyError, test_tree.get_device, "invalid", "test")
        self.assertRaises(KeyError, test_tree.get_device, "testing", "invalid")
        self.assertTrue(isinstance(test_tree.get_device("testing", "test"),
                                   tree.Device))

        # Test device removal
        test_tree.create_device("testing", "to-remove")
        self.assertTrue(
            os.path.exists(os.path.join(self.config.publish_path,
                                        "testing", "to-remove", "index.json")))
        self.assertRaises(KeyError, test_tree.remove_device, "invalid", "test")
        self.assertRaises(KeyError, test_tree.remove_device, "testing",
                          "invalid")
        test_tree.remove_device("testing", "to-remove")
        self.assertFalse(
            os.path.exists(os.path.join(self.config.publish_path,
                                        "testing", "to-remove", "index.json")))

        self.assertEquals(
            test_tree.list_channels(), {'testing':
                                       {'devices':
                                        {'test': {
                                         'index': '/testing/test/index.json',
                                         'keyring': {
                                             'path': '/testing/test/device'
                                                     '.tar.xz',
                                             'signature': '/testing/test/devi'
                                                          'ce.tar.xz.asc'}}}}})

        # Test setting the device keyring
        self.assertRaises(KeyError, test_tree.set_device_keyring, "invalid",
                          "test", "invalid")
        self.assertRaises(KeyError, test_tree.set_device_keyring, "testing",
                          "invalid", "invalid")
        test_tree.set_device_keyring("testing", "test",
                                     "testing/test/device.tar.xz")
        self.assertRaises(Exception, test_tree.set_device_keyring, "testing",
                          "test", "invalid")

        unsigned_path = os.path.join(self.config.publish_path, "unsigned")
        open(unsigned_path, "w+").close()
        self.assertRaises(Exception, test_tree.set_device_keyring, "testing",
                          "test", "unsigned")
        os.remove(unsigned_path)

    @unittest.skipIf(not os.path.exists("tests/keys/generated"),
                     "No GPG testing keys present. Run tests/generate-keys")
    def test_alias(self):
        test_tree = tree.Tree(self.config)

        # Create some channels and aliases
        test_tree.create_channel("parent")
        test_tree.create_channel_alias("alias", "parent")

        # Test standard failure cases
        self.assertRaises(KeyError, test_tree.create_channel_alias,
                          "alias", "parent")
        self.assertRaises(KeyError, test_tree.create_channel_alias,
                          "alias1", "parent1")

        self.assertRaises(KeyError, test_tree.change_channel_alias,
                          "alias1", "parent")
        self.assertRaises(KeyError, test_tree.change_channel_alias,
                          "alias", "parent1")

        self.assertRaises(KeyError, test_tree.sync_aliases, "missing")
        self.assertRaises(KeyError, test_tree.sync_alias, "missing")
        self.assertRaises(TypeError, test_tree.sync_alias, "parent")

        test_tree.remove_channel("parent")
        self.assertRaises(KeyError, test_tree.sync_alias, "alias")
        test_tree.create_channel("parent")

        # Publish a basic image
        test_tree.create_device("parent", "device")
        test_tree.create_device("parent", "device2")
        test_tree.create_device("parent", "device3")
        test_tree.create_device("alias", "device")
        test_tree.create_device("alias", "device1")
        test_tree.create_device("alias", "device3")

        ## First file
        first = os.path.join(self.config.publish_path, "parent/device/full")
        open(first, "w+").close()
        gpg.sign_file(self.config, "image-signing", first)

        ## Second file
        second = os.path.join(self.config.publish_path,
                              "parent/device/version-1234.tar.xz")

        tools.generate_version_tarball(self.config, "parent", "1234",
                                       second.replace(".xz", ""))
        tools.xz_compress(second.replace(".xz", ""))
        os.remove(second.replace(".xz", ""))
        gpg.sign_file(self.config, "image-signing", second)

        with open(second.replace(".tar.xz", ".json"), "w+") as fd:
            metadata = {}
            metadata['channel.ini'] = {}
            metadata['channel.ini']['version_detail'] = "test"
            fd.write(json.dumps(metadata))
        gpg.sign_file(self.config, "image-signing",
                      second.replace(".tar.xz", ".json"))

        ## Adding the entry
        device = test_tree.get_device("parent", "device")
        device.create_image("full", 1234, "abc",
                            ["parent/device/full",
                             "parent/device/version-1234.tar.xz"])

        ## Adding a fake entry to the alias channel
        device = test_tree.get_device("alias", "device")
        device.create_image("full", 1235, "abc",
                            ["parent/device/full",
                             "parent/device/version-1234.tar.xz"])

        # Sync the alises
        device3 = test_tree.get_device("alias", "device3")
        shutil.rmtree(device3.path)
        test_tree.sync_aliases("parent")

        test_tree.create_channel("new_parent")
        test_tree.change_channel_alias("alias", "new_parent")

        test_tree.remove_channel("alias")
        test_tree.remove_channel("new_parent")
        test_tree.remove_channel("parent")

    @unittest.skipIf(not os.path.exists("tests/keys/generated"),
                     "No GPG testing keys present. Run tests/generate-keys")
    def test_index(self):
        device = tree.Device(self.config, self.temp_directory)

        # Check without files
        self.assertRaises(Exception, device.create_image, "full", 1234,
                          "test", [])

        # Check with missing file
        self.assertRaises(Exception, device.create_image, "full", 1234,
                          "test", ["file"])

        # Check with missing signature
        open(os.path.join(self.config.publish_path, "file"), "w+").close()
        self.assertRaises(Exception, device.create_image, "full", 1234,
                          "test", ["file"])

        # Check with missing base version
        gpg.sign_file(self.config, "image-signing",
                      os.path.join(self.config.publish_path, "file"))
        self.assertRaises(KeyError, device.create_image, "delta", 1234,
                          "test", ["file"])

        # Check with extra base version
        self.assertRaises(KeyError, device.create_image, "full", 1234,
                          "test", ["file"], base=1233)

        # Check with extra minimum version
        self.assertRaises(KeyError, device.create_image, "delta", 1234,
                          "test", ["file"], base=1233, minversion=1233)

        # Valid full image
        open(os.path.join(self.config.publish_path, "second"), "w+").close()
        gpg.sign_file(self.config, "image-signing",
                      os.path.join(self.config.publish_path, "second"))
        device.create_image("full", 1234, "abc", ["file", "second"],
                            minversion=1233, bootme=True)

        # Valid delta image
        device.create_image("delta", 1234, "abc", ["file", "second"],
                            base=1233, bootme=True)

        # Check the image list
        self.assertEquals(
            device.list_images(),
            [{'bootme': True, 'description': 'abc', 'minversion': 1233,
              'type': 'full', 'version': 1234,
              'files': [{'signature': '/file.asc', 'path': '/file',
                         'checksum': 'e3b0c44298fc1c149afbf4c8996fb924'
                                     '27ae41e4649b934ca495991b7852b855',
                         'size': 0, 'order': 0},
                        {'signature': '/second.asc', 'path': '/second',
                         'checksum': 'e3b0c44298fc1c149afbf4c8996fb924'
                                     '27ae41e4649b934ca495991b7852b855',
                         'size': 0, 'order': 1}]},
             {'bootme': True, 'description': 'abc', 'type': 'delta',
              'base': 1233, 'version': 1234,
              'files': [{'signature': '/file.asc', 'path': '/file',
                         'checksum': 'e3b0c44298fc1c149afbf4c8996fb924'
                                     '27ae41e4649b934ca495991b7852b855',
                         'size': 0, 'order': 0},
                        {'signature': '/second.asc', 'path': '/second',
                         'checksum': 'e3b0c44298fc1c149afbf4c8996fb924'
                                     '27ae41e4649b934ca495991b7852b855',
                         'size': 0, 'order': 1}]}])

        # Set descriptions
        device.set_description("delta", 1234, "test", {"fr": "essai"}, 1233)
        entry = device.get_image("delta", 1234, 1233)
        self.assertEquals(entry['description'], "test")
        self.assertEquals(entry['description_fr'], "essai")

        self.assertRaises(TypeError, device.set_description, "delta", 1234,
                          "test", ['test'], 1233)

        # Remove the images
        device.remove_image("delta", 1234, 1233)
        device.remove_image("full", 1234)
        self.assertEquals(device.list_images(), [])

        # Error case of remove_image
        self.assertRaises(ValueError, device.remove_image, "invalid", 1234)
        self.assertRaises(ValueError, device.remove_image, "delta", 1234)
        self.assertRaises(IndexError, device.remove_image, "delta", 1234, 1232)

        # Test invalid json
        with open(device.indexpath, "w+") as fd:
            fd.write("test")

        self.assertRaises(ValueError, device.list_images)

        with open(device.indexpath, "w+") as fd:
            fd.write("[]")

        self.assertRaises(TypeError, device.list_images)

    def test_file_lists(self):
        test_tree = tree.Tree(self.config)
        test_tree.create_channel("test")
        test_tree.create_device("test", "test")

        self.assertEquals(test_tree.list_missing_files(), [])
        self.assertEquals(test_tree.list_orphaned_files(), [])

        # Confirm that the gpg directory is ignored
        if not os.path.exists(os.path.join(test_tree.path, "gpg")):
            os.mkdir(os.path.join(test_tree.path, "gpg"))
        self.assertEquals(test_tree.list_orphaned_files(), [])

        # Confirm that it picks up extra directories
        os.mkdir(os.path.join(test_tree.path, "invalid"))
        self.assertEquals(test_tree.list_orphaned_files(),
                          [os.path.join(test_tree.path, "invalid")])

        # And that it gets cleared up
        test_tree.cleanup_tree()
        self.assertEquals(test_tree.list_orphaned_files(), [])

        # Confirm that it picks up extra files
        open(os.path.join(test_tree.path, "invalid"), "w+").close()
        self.assertEquals(test_tree.list_orphaned_files(),
                          [os.path.join(test_tree.path, "invalid")])

        # And that it gets cleared up
        test_tree.cleanup_tree()
        self.assertEquals(test_tree.list_orphaned_files(), [])

        # Test that keyrings aren't considered as orphaned files
        keyring_path = os.path.join(test_tree.path, "gpg", "device.tar.xz")
        open(keyring_path, "w+").close()
        gpg.sign_file(self.config, "image-signing", keyring_path)
        test_tree.set_device_keyring("test", "test", keyring_path)
        self.assertEquals(test_tree.list_orphaned_files(), [])

        # Test that images aren't considered as orphaned files
        image_path = os.path.join(test_tree.path,
                                  "test", "test", "image.tar.xz")
        open(image_path, "w+").close()
        gpg.sign_file(self.config, "image-signing", image_path)
        open(image_path.replace(".tar.xz", ".json"), "w+").close()
        gpg.sign_file(self.config, "image-signing",
                      image_path.replace(".tar.xz", ".json"))
        device = test_tree.get_device("test", "test")
        device.create_image("full", 12345, "test", [image_path])
        self.assertEquals(test_tree.list_orphaned_files(), [])

    def test_expiry(self):
        test_tree = tree.Tree(self.config)
        test_tree.create_channel("test")
        test_tree.create_device("test", "test")

        # Insert a few images
        image_path = os.path.join(test_tree.path,
                                  "test", "test", "image.tar.xz")
        open(image_path, "w+").close()
        gpg.sign_file(self.config, "image-signing", image_path)
        device = test_tree.get_device("test", "test")
        device.create_image("full", 1, "test", [image_path])
        device.create_image("full", 2, "test", [image_path])
        device.create_image("delta", 2, "test", [image_path], base=1)
        device.create_image("full", 3, "test", [image_path])
        device.create_image("delta", 3, "test", [image_path], base=2)
        device.create_image("delta", 3, "test", [image_path], base=1)
        device.create_image("full", 4, "test", [image_path])
        device.create_image("delta", 4, "test", [image_path], base=3)
        device.create_image("delta", 4, "test", [image_path], base=2)
        device.create_image("delta", 4, "test", [image_path], base=1)

        self.assertEquals(len(device.list_images()), 10)

        device.expire_images(10)
        self.assertEquals(len(device.list_images()), 10)

        device.expire_images(3)
        self.assertEquals(len(device.list_images()), 6)

        device.expire_images(3)
        self.assertEquals(len(device.list_images()), 6)

        device.expire_images(2)
        self.assertEquals(len(device.list_images()), 3)

        device.expire_images(1)
        self.assertEquals(len(device.list_images()), 1)

        device.expire_images(0)
        self.assertEquals(len(device.list_images()), 0)

    def test_phased_percentage(self):
        test_tree = tree.Tree(self.config)

        # Create a channel, device and images
        test_tree.create_channel("test")
        test_tree.create_device("test", "test")

        ## some file
        first = os.path.join(self.config.publish_path, "test/test/full")
        open(first, "w+").close()
        gpg.sign_file(self.config, "image-signing", first)

        ## Adding a first entry
        device = test_tree.get_device("test", "test")
        device.create_image("full", 1234, "abc",
                            ["test/test/full"])
        device.set_phased_percentage(1234, 20)

        ## Adding a second entry
        device = test_tree.get_device("test", "test")
        device.create_image("full", 1235, "abc",
                            ["test/test/full"])
        device.set_phased_percentage(1235, 0)

        device.set_phased_percentage(1235, 100)

        # Test standard failure cases
        self.assertRaises(TypeError, device.set_phased_percentage,
                          1235, "invalid")
        self.assertRaises(TypeError, device.set_phased_percentage,
                          1235, 10.5)
        self.assertRaises(ValueError, device.set_phased_percentage,
                          1235, 101)
        self.assertRaises(ValueError, device.set_phased_percentage,
                          1235, -1)

        self.assertRaises(IndexError, device.set_phased_percentage,
                          4242, 50)
        self.assertRaises(Exception, device.set_phased_percentage,
                          1234, 50)
