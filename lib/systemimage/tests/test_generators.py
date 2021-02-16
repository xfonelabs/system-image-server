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
import socket
import subprocess
import tarfile
import tempfile
import unittest

try:
    from unittest import mock
except ImportError:
    import mock

from hashlib import sha256
from io import BytesIO

from systemimage import config, generators, gpg, tools, tree
from systemimage.testing.helpers import HAS_TEST_KEYS, MISSING_KEYS_WARNING
from systemimage.tools import xz_uncompress


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
""" % (self.temp_directory, os.path.join(os.getcwd(), "tools", "keys")))
        self.config = config.Config(config_path)

        os.mkdir(os.path.join(self.temp_directory, "www"))
        self.tree = tree.Tree(self.config)
        self.tree.create_channel("test")
        self.tree.create_device("test", "test")
        self.device = self.tree.get_device("test", "test")

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    def _publish_dummy_to_channel(self, device):
        """Helper function used to publish a dummy image for selected device"""
        open(os.path.join(self.config.publish_path, "file-1.tar.xz"),
             "w+").close()

        with open(os.path.join(self.config.publish_path, "file-1.json"),
                  "w+") as fd:
            fd.write(json.dumps({'version_detail': "abcd"}))

        gpg.sign_file(self.config, "image-signing",
                      os.path.join(self.config.publish_path, "file-1.tar.xz"))
        device.create_image("full", 1234, "abc", ["file-1.tar.xz"],
                            minversion=1233, bootme=True)

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_unpack_arguments(self):
        self.assertEqual(generators.unpack_arguments("a=1,b=2"),
                         {'a': "1", 'b': "2"})
        self.assertEqual(generators.unpack_arguments("a=1,b=2,c"),
                         {'a': "1", 'b': "2"})
        # Test case if we have = in the value
        self.assertEqual(generators.unpack_arguments(
                         "a=1,b=2=1,c,v=1=1=1=1,d=c"),
                         {'a': "1", 'b': "2=1", "v": "1=1=1=1", "d": "c"})

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_delta(self):
        # Source tarball
        source_path = os.path.join(self.temp_directory, "source.tar")
        source_path_xz = "%s.xz" % source_path
        source_tar = tarfile.open(source_path, "w")
        source_tar.close()
        tools.xz_compress(source_path)
        os.remove(source_path)

        # Source json
        with open(os.path.join(self.temp_directory, "source.json"),
                  "w+") as fd:
            source_json = {}
            source_json['a'] = 1
            fd.write(json.dumps(source_json))

        # Destination tarball
        destination_path = os.path.join(self.temp_directory, "destination.tar")
        destination_path_xz = "%s.xz" % destination_path
        destination_tar = tarfile.open(destination_path, "w")
        destination_tar.close()
        tools.xz_compress(destination_path)
        os.remove(destination_path)

        # Destination json
        with open(os.path.join(self.temp_directory, "destination.json"),
                  "w+") as fd:
            source_json = {}
            source_json['b'] = 2
            fd.write(json.dumps(source_json))

        # Check that version tarballs are just returned
        open(os.path.join(self.temp_directory,
                          "version-1.tar.xz"), "w+").close()
        open(os.path.join(self.temp_directory,
                          "version-2.tar.xz"), "w+").close()
        self.assertEqual(
            generators.generate_delta(
                self.config,
                os.path.join(self.temp_directory, "version-1.tar.xz"),
                os.path.join(self.temp_directory, "version-2.tar.xz")),
            os.path.join(self.temp_directory, "version-2.tar.xz"))

        # Check that keyring tarballs are just returned
        open(os.path.join(self.temp_directory,
                          "keyring-1.tar.xz"), "w+").close()
        self.assertEqual(
            generators.generate_delta(
                self.config,
                os.path.join(self.temp_directory, "keyring-1.tar.xz"),
                os.path.join(self.temp_directory, "keyring-1.tar.xz")),
            os.path.join(self.temp_directory, "keyring-1.tar.xz"))

        # Generate the diff
        self.assertEqual(
            generators.generate_delta(self.config, source_path_xz,
                                      destination_path_xz),
            os.path.join(self.config.publish_path, "pool",
                         "destination.delta-source.tar.xz"))

        # Check that we get cached entries
        generators.generate_delta(self.config, source_path_xz,
                                  destination_path_xz)

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file(self):
        self.assertRaises(Exception, generators.generate_file, self.config,
                          "invalid", [], {})

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file_version(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Ensure we don't generate a new tarball when there are no changes
        environment['new_files'] = []
        self.assertEqual(
            generators.generate_file(self.config, "version", [], environment),
            None)

        # Do a standard run
        environment['new_files'] = ["some-file.tar.xz"]
        self.assertEqual(
            generators.generate_file(self.config, "version", [], environment),
            os.path.realpath(os.path.join(self.device.path,
                             "version-%s.tar.xz" % environment['version'])))

        # Go through the cache code path
        environment['new_files'] = ["some-file.tar.xz"]
        self.assertEqual(
            generators.generate_file(self.config, "version", [], environment),
            os.path.realpath(os.path.join(self.device.path,
                             "version-%s.tar.xz" % environment['version'])))

        # Confirm pool creation
        environment['new_files'] = ["some-file.tar.xz"]
        shutil.rmtree(self.device.path)
        self.assertEqual(
            generators.generate_file(self.config, "version", [], environment),
            os.path.realpath(os.path.join(self.device.path,
                             "version-%s.tar.xz" % environment['version'])))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file_cdimage_device_raw(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "generic_x86"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Check the path and series requirement
        self.assertEqual(
            generators.generate_file_cdimage_device_raw(self.config, [],
                                                        environment),
            None)

        # Check behaviour on invalid cdimage path
        self.assertEqual(
            generators.generate_file_cdimage_device_raw(
                self.config, ['invalid-path', 'invalid-series'],
                environment),
            None)

        # Check behaviour on empty tree
        cdimage_tree = os.path.join(self.temp_directory, "cdimage")
        os.mkdir(cdimage_tree)
        self.assertEqual(
            generators.generate_file_cdimage_device_raw(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing hash
        version_path = os.path.join(cdimage_tree, "1234")
        os.mkdir(version_path)
        self.assertEqual(
            generators.generate_file_cdimage_device_raw(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing files
        for filename in ("SHA256SUMS",
                         "series-preinstalled-core-i386.device.tar.gz",
                         ".marked_good"):
            open(os.path.join(version_path, filename), "w+").close()
            self.assertEqual(
                generators.generate_file_cdimage_device_raw(
                    self.config, [cdimage_tree, 'series', 'import=good'],
                    environment),
                None)

        # Check SHA256SUMS parsing
        with open(os.path.join(version_path, "SHA256SUMS"), "w+") as fd:
            fd.write("\n")

        self.assertEqual(
            generators.generate_file_cdimage_device_raw(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        for device_arch, cdimage_arch in (
                ("generic_x86", "i386"),
                ("generic_i386", "i386"),
                ("generic_amd64", "amd64"),
                ("azure_amd64", "amd64.azure"),
                ("plano", "amd64.plano"),
                ("raspi2_armhf", "armhf.raspi2")):
            environment['device_name'] = device_arch

            for filename in (
                    "SHA256SUMS",
                    "series-preinstalled-core-%s.device.tar.gz" % cdimage_arch,
                    ".marked_good"):
                open(os.path.join(version_path, filename), "w+").close()

            # Working run
            with open(os.path.join(version_path, "SHA256SUMS"), "w+") as fd:
                fd.write("HASH *series-preinstalled-core-%s.device.tar.gz\n" %
                         cdimage_arch)

            self.assertEqual(
                generators.generate_file(
                    self.config, "cdimage-device-raw",
                    [cdimage_tree, 'series'], environment),
                os.path.join(self.config.publish_path, "pool",
                             "device-HASH.tar.xz"))

            # Cached run
            self.assertEqual(
                generators.generate_file_cdimage_device_raw(
                    self.config, [cdimage_tree, 'series'],
                    environment),
                os.path.join(self.config.publish_path, "pool",
                             "device-HASH.tar.xz"))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file_cdimage_ubuntu(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "generic_x86"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Check the path and series requirement
        self.assertEqual(
            generators.generate_file_cdimage_ubuntu(self.config, [],
                                                    environment),
            None)

        # Check behaviour on invalid cdimage path
        self.assertEqual(
            generators.generate_file_cdimage_ubuntu(
                self.config, ['invalid-path', 'invalid-series'],
                environment),
            None)

        # Check behaviour on empty tree
        cdimage_tree = os.path.join(self.temp_directory, "cdimage")
        os.mkdir(cdimage_tree)
        self.assertEqual(
            generators.generate_file_cdimage_ubuntu(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing hash
        version_path = os.path.join(cdimage_tree, "1234")
        os.mkdir(version_path)
        self.assertEqual(
            generators.generate_file_cdimage_ubuntu(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing files
        for filename in ("SHA256SUMS",
                         "series-preinstalled-touch-i386.tar.gz",
                         ".marked_good"):
            open(os.path.join(version_path, filename), "w+").close()
            self.assertEqual(
                generators.generate_file_cdimage_ubuntu(
                    self.config, [cdimage_tree, 'series', 'import=good'],
                    environment),
                None)

        # Working run
        for device_arch, cdimage_arch, cdimage_product, android_hacks in (
                ("generic_x86", "i386", "touch", True),
                ("generic_x86", "i386", "pd", True),
                ("generic_i386", "i386", "core", False),
                ("generic_amd64", "amd64", "core", False)):
            environment['device_name'] = device_arch

            for filename in ("SHA256SUMS",
                             "series-preinstalled-%s-%s.tar.gz" %
                             (cdimage_product, cdimage_arch),
                             ".marked_good"):
                open(os.path.join(version_path, filename), "w+").close()

            with open(os.path.join(version_path, "SHA256SUMS"), "w+") as fd:
                fd.write("HASH *series-preinstalled-%s-%s.tar.gz\n" %
                         (cdimage_product, cdimage_arch))

            tarball = os.path.join(version_path,
                                   "series-preinstalled-%s-%s.tar.gz" %
                                   (cdimage_product, cdimage_arch))
            os.remove(tarball)
            tarball_obj = tarfile.open(tarball, "w:gz")

            # # SWAP.swap
            swap = tarfile.TarInfo()
            swap.name = "SWAP.swap"
            swap.size = 4
            tarball_obj.addfile(swap, BytesIO(b"test"))

            # # /etc/mtab
            mtab = tarfile.TarInfo()
            mtab.name = "etc/mtab"
            mtab.size = 4
            tarball_obj.addfile(mtab, BytesIO(b"test"))

            # # A hard link
            hl = tarfile.TarInfo()
            hl.name = "f"
            hl.type = tarfile.LNKTYPE
            hl.linkname = "a"
            tarball_obj.addfile(hl)

            # # A standard file
            sf = tarfile.TarInfo()
            sf.name = "f"
            sf.size = 4
            tarball_obj.addfile(sf, BytesIO(b"test"))

            tarball_obj.close()

            self.assertEqual(
                generators.generate_file(
                    self.config, "cdimage-ubuntu",
                    [cdimage_tree, 'series', 'product=%s' % cdimage_product],
                    environment),
                os.path.join(self.config.publish_path, "pool",
                             "ubuntu-HASH.tar.xz"))

            # Cached run
            self.assertEqual(
                generators.generate_file_cdimage_ubuntu(
                    self.config, [cdimage_tree, 'series',
                                  'product=%s' % cdimage_product],
                    environment),
                os.path.join(self.config.publish_path, "pool",
                             "ubuntu-HASH.tar.xz"))

            # Check that for touch and pd the android hacks are executed.
            # Python 2.7 does not support tar.xz, so do it another way.
            xz_path = os.path.join(
                self.config.publish_path, "pool",
                "ubuntu-HASH.tar.xz")
            unxz_path = os.path.join(self.temp_directory, "temp-unpack.tar")
            try:
                xz_uncompress(xz_path, unxz_path)
                target_obj = tarfile.open(unxz_path, "r")
                if android_hacks:
                    self.assertIn("system/android", target_obj.getnames())
            finally:
                target_obj.close()
                os.remove(unxz_path)

            for entry in ("ubuntu-HASH.tar.xz", "ubuntu-HASH.tar.xz.asc",
                          "ubuntu-HASH.json", "ubuntu-HASH.json.asc"):
                os.remove(os.path.join(self.config.publish_path,
                                       "pool", entry))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file_cdimage_custom(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "generic_x86"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Check the path and series requirement
        self.assertEqual(
            generators.generate_file_cdimage_custom(self.config, [],
                                                    environment),
            None)

        # Check behaviour on invalid cdimage path
        self.assertEqual(
            generators.generate_file_cdimage_custom(
                self.config, ['invalid-path', 'invalid-series'],
                environment),
            None)

        # Check behaviour on empty tree
        cdimage_tree = os.path.join(self.temp_directory, "cdimage")
        os.mkdir(cdimage_tree)
        self.assertEqual(
            generators.generate_file_cdimage_custom(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing hash
        version_path = os.path.join(cdimage_tree, "1234")
        os.mkdir(version_path)
        self.assertEqual(
            generators.generate_file_cdimage_custom(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing files
        for filename in ("SHA256SUMS",
                         "series-preinstalled-touch-i386.custom.tar.gz",
                         ".marked_good"):
            open(os.path.join(version_path, filename), "w+").close()
            self.assertEqual(
                generators.generate_file_cdimage_custom(
                    self.config, [cdimage_tree, 'series', 'import=good'],
                    environment),
                None)

        # Working run
        for device_arch, cdimage_arch, cdimage_product in (
                ("generic_x86", "i386", "touch"),
                ("generic_i386", "i386", "core"),
                ("generic_amd64", "amd64", "core")):
            environment['device_name'] = device_arch

            for filename in ("SHA256SUMS",
                             "series-preinstalled-%s-%s.custom.tar.gz" %
                             (cdimage_product, cdimage_arch),
                             ".marked_good"):
                open(os.path.join(version_path, filename), "w+").close()

            with open(os.path.join(version_path, "SHA256SUMS"), "w+") as fd:
                fd.write("HASH *series-preinstalled-%s-%s.custom.tar.gz\n" %
                         (cdimage_product, cdimage_arch))

            tarball = os.path.join(version_path,
                                   "series-preinstalled-%s-%s.custom.tar.gz" %
                                   (cdimage_product, cdimage_arch))
            os.remove(tarball)
            tarball_obj = tarfile.open(tarball, "w:gz")
            tarball_obj.close()

            self.assertEqual(
                generators.generate_file(
                    self.config, "cdimage-custom",
                    [cdimage_tree, 'series', 'product=%s' % cdimage_product],
                    environment),
                os.path.join(self.config.publish_path, "pool",
                             "custom-HASH.tar.xz"))

            # Cached run
            self.assertEqual(
                generators.generate_file_cdimage_custom(
                    self.config, [cdimage_tree, 'series',
                                  'product=%s' % cdimage_product],
                    environment),
                os.path.join(self.config.publish_path, "pool",
                             "custom-HASH.tar.xz"))

            for entry in ("custom-HASH.tar.xz", "custom-HASH.tar.xz.asc",
                          "custom-HASH.json", "custom-HASH.json.asc"):
                os.remove(os.path.join(self.config.publish_path,
                                       "pool", entry))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    @mock.patch("systemimage.generators.urlretrieve")
    @mock.patch("systemimage.generators.urlopen")
    def test_generate_file_http(self, mock_urlopen, mock_urlretrieve):
        def urlopen_side_effect(url, timeout=0):
            if url.endswith("timeout"):
                raise socket.timeout

            if url.endswith("error"):
                raise IOError()

            if url.endswith("long"):
                return BytesIO(b"42\n42\n42")

            return BytesIO(b"42")
        mock_urlopen.side_effect = urlopen_side_effect

        def urlretrieve_side_effect(url, location):
            if url.endswith("timeout"):
                raise socket.timeout

            if url.endswith("error"):
                raise IOError()

            with open(location, "w+") as fd:
                fd.write(url)
        mock_urlretrieve.side_effect = urlretrieve_side_effect

        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Without arguments
        self.assertEqual(
            generators.generate_file_http(self.config, [], {}),
            None)

        # Timeout without monitor
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/timeout"],
                                     environment),
            None)

        # Error without monitor
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/error"],
                                     environment),
            None)

        # Timeout with monitor
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/timeout",
                                      "monitor=http://1.2.3.4/timeout"],
                                     environment),
            None)

        # Error with monitor
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/error",
                                      "monitor=http://1.2.3.4/error"],
                                     environment),
            None)

        # Invalid build number with monitor
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file",
                                      "monitor=http://1.2.3.4/long"],
                                     environment),
            None)

        # Normal run without monitor
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-33b3daaf6724164f00467103907a590ca"
                         "2d4c6a0d1b63f93a3018cef1020df3b.tar.xz"))

        # Cached run without monitor
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-33b3daaf6724164f00467103907a590ca"
                         "2d4c6a0d1b63f93a3018cef1020df3b.tar.xz"))

        # Cached run without monitor (no path caching)
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-33b3daaf6724164f00467103907a590ca"
                         "2d4c6a0d1b63f93a3018cef1020df3b.tar.xz"))

        # Normal run with monitor
        generators.CACHE = {}
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file",
                                      "monitor=http://1.2.3.4/buildid"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-f09815f899863cb369f2a12fa6b29ce8bca0d4a"
                         "5cef1809ce82af09d41e2f5af.tar.xz"))

        # Cached run with monitor
        self.assertEqual(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file",
                                      "monitor=http://1.2.3.4/buildid"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-f09815f899863cb369f2a12fa6b29ce8bca0d4a"
                         "5cef1809ce82af09d41e2f5af.tar.xz"))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file_keyring(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['version'] = 1234
        environment['version_detail'] = []

        # Generate the keyring tarballs
        env = dict(os.environ)
        env['SYSTEM_IMAGE_ROOT'] = self.temp_directory
        subprocess.call(["bin/generate-keyrings"], env=env)

        # Ensure we don't generate a new tarball when there are no changes
        environment['new_files'] = []
        self.assertEqual(
            generators.generate_file(self.config, "keyring",
                                     ['archive-master'], environment),
            None)
        environment['new_files'] = ['abc']

        # Check the arguments count
        self.assertEqual(
            generators.generate_file_keyring(self.config, [], environment),
            None)

        # Check for invalid keyring name
        self.assertEqual(
            generators.generate_file_keyring(self.config,
                                             ['invalid'],
                                             environment),
            None)

        keyring_path = os.path.join(self.config.gpg_keyring_path,
                                    "archive-master")

        with open("%s.tar.xz" % keyring_path, "rb") as fd:
            hash_tarball = sha256(fd.read()).hexdigest()

        with open("%s.tar.xz.asc" % keyring_path, "rb") as fd:
            hash_signature = sha256(fd.read()).hexdigest()

        hash_string = "%s/%s" % (hash_tarball, hash_signature)
        global_hash = sha256(hash_string.encode("utf-8")).hexdigest()

        # Normal run
        self.assertEqual(
            generators.generate_file(self.config, "keyring",
                                                  ['archive-master'],
                                                  environment),
            os.path.join(self.config.publish_path, "pool",
                         "keyring-%s.tar.xz" % global_hash))

        # Cached run
        self.assertEqual(
            generators.generate_file(self.config, "keyring",
                                                  ['archive-master'],
                                                  environment),
            os.path.join(self.config.publish_path, "pool",
                         "keyring-%s.tar.xz" % global_hash))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file_system_image(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Check the arguments count
        self.assertEqual(
            generators.generate_file_system_image(self.config, [], {}),
            None)

        # Check for channel name
        self.assertEqual(
            generators.generate_file_system_image(self.config,
                                                  ['invalid', 'file'],
                                                  environment),
            None)

        # Check for device name
        environment['device_name'] = "invalid"
        self.assertEqual(
            generators.generate_file_system_image(self.config,
                                                  ['test', 'file'],
                                                  environment),
            None)

        # Run against an empty channel
        environment['device_name'] = "test"
        self.assertEqual(
            generators.generate_file_system_image(self.config,
                                                  ['test', 'file'],
                                                  environment),
            None)

        # Publish some random stuff
        self._publish_dummy_to_channel(self.device)

        # Invalid filename
        self.assertEqual(
            generators.generate_file_system_image(self.config,
                                                  ['test', 'invalid'],
                                                  environment),
            None)

        # Normal run
        self.assertEqual(
            generators.generate_file(self.config, "system-image",
                                                  ['test', 'file'],
                                                  environment),
            os.path.join(self.config.publish_path, "file-1.tar.xz"))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_generate_file_system_image_different_device(self):
        """Test the system-image generator for a different source device."""
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        self.tree.create_device("test", "source")
        source_device = self.tree.get_device("test", "source")

        # Invalid device
        self.assertIsNone(
            generators.generate_file(self.config, "system-image",
                                     ['test', 'file', 'device=invalid'],
                                     environment))

        # Empty channel in correct device
        self.assertIsNone(
            generators.generate_file(self.config, "system-image",
                                     ['test', 'file', 'device=source'],
                                     environment))

        # Publish some random stuff
        self._publish_dummy_to_channel(source_device)

        # Normal run
        self.assertEqual(
            generators.generate_file(self.config, "system-image",
                                     ['test', 'file', 'device=source'],
                                     environment),
            os.path.join(self.config.publish_path, "file-1.tar.xz"))

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    @mock.patch("systemimage.tools.repack_recovery_keyring")
    @mock.patch("systemimage.generators.urlretrieve")
    @mock.patch("systemimage.generators.urlopen")
    def test_generate_file_remote_system_image(self, mock_urlopen,
                                               mock_urlretrieve,
                                               mock_repack_recovery_keyring):
        def urlopen_side_effect(url):
            if url.startswith("http://timeout"):
                raise socket.timeout

            if url.startswith("http://error"):
                raise IOError()

            if url.startswith("http://index-timeout") and \
               url.endswith("index.json"):
                raise socket.timeout

            if url.startswith("http://index-error") and \
               url.endswith("index.json"):
                raise IOError()

            if url.startswith("http://partial-json/") and \
               url.endswith("channels.json"):
                return BytesIO(json.dumps({"chan": {}}).encode())

            if url.startswith("http://partial-json1/") and \
               url.endswith("channels.json"):
                return BytesIO(json.dumps(
                    {"chan": {"devices": {"test": {}}}})
                    .encode())

            if url.startswith("http://empty-json/") and \
               url.endswith("index.json"):
                return BytesIO(json.dumps({"images": []}).encode())

            if url.endswith("channels.json"):
                return BytesIO(json.dumps(
                    {"chan": {"devices": {"test": {"index": "/index.json"}}}})
                    .encode())

            if url.startswith("http://no-match/") and \
               url.endswith("index.json"):
                return BytesIO(json.dumps(
                    {"images": [{"description": "test",
                                 "type": "full",
                                 "version": 123,
                                 "files": [{'path': '/pool/c-c.tar.xz'},
                                           {'path': '/pool/d-d.tar.xz'}]}]})
                    .encode())

            if url.endswith("index.json"):
                return BytesIO(json.dumps(
                    {"images": [{"description": "test",
                                 "type": "full",
                                 "version": 123,
                                 "files": [{'path': '/pool/a-a.tar.xz'},
                                           {'path': '/pool/b-b.tar.xz'}]}]})
                    .encode())

            return BytesIO(url)
        mock_urlopen.side_effect = urlopen_side_effect

        def urlretrieve_side_effect(url, location):
            if url.startswith("http://timeout"):
                raise socket.timeout

            if url.startswith("http://error"):
                raise IOError()

            if url.startswith("http://meta-timeout") and \
               "/pool/" in url and url.endswith(".json"):
                open(location, "w+").close()
                raise socket.timeout

            if url.startswith("http://meta-error") and \
               "/pool/" in url and url.endswith(".json"):
                open(location, "w+").close()
                raise IOError()

            if url.startswith("http://file-timeout") and \
               "/pool/" in url:
                open(location, "w+").close()
                raise socket.timeout

            if url.startswith("http://file-error") and \
               "/pool/" in url:
                open(location, "w+").close()
                raise IOError()

            if "/pool/" in url and url.endswith(".json"):
                with open(location, "w+") as fd:
                    fd.write(json.dumps({'version_detail': 'abc'}))
                    return

            with open(location, "w+") as fd:
                fd.write(url)
        mock_urlretrieve.side_effect = urlretrieve_side_effect

        def repack_recovery_keyring_effect(conf, path, keyring,
                                           device_name=None):
            if keyring == "fail":
                return False

            return True

        mock_repack_recovery_keyring.side_effect = \
            repack_recovery_keyring_effect

        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Without arguments
        self.assertEqual(
            generators.generate_file_remote_system_image(self.config, [], {}),
            None)

        # Invalid server
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://error', 'chan', 'prefix'],
                environment), None)

        # Server timeout
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://timeout', 'chan', 'prefix'],
                environment), None)

        # Invalid channel
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://valid', 'invalid', 'prefix'],
                environment), None)

        # Missing devices dict
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://partial-json', 'chan', 'prefix'],
                environment), None)

        # Invalid device
        environment['device_name'] = "invalid"
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://channels.json', 'chan', 'prefix'],
                environment), None)
        environment['device_name'] = "test"

        # Invalid device override
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://channels.json', 'chan', 'prefix',
                              'device=invalid'],
                environment), None)

        # Missing index
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://partial-json1', 'chan', 'prefix'],
                environment), None)

        # index.json timeout
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://index-timeout', 'chan', 'prefix'],
                environment), None)

        # index.json error
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://index-error', 'chan', 'prefix'],
                environment), None)

        # empty index.json
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://empty-json', 'chan', 'prefix'],
                environment), None)

        # valid index.json timeout
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://file-timeout', 'chan', 'a',
                              'keyring=fail'],
                environment), None)

        # valid index.json error
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://file-error', 'chan', 'a',
                              'keyring=fail'],
                environment), None)

        # valid index.json, fail at repacking
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://valid-json', 'chan', 'a',
                              'keyring=fail'],
                environment), None)

        # valid index.json, metadata timeout
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://meta-timeout', 'chan', 'a',
                              'keyring=archive-master'],
                environment), "%s/www/pool/a-a.tar.xz" % self.temp_directory)

        # valid index.json, metadata error
        shutil.rmtree("%s/www/pool/" % self.temp_directory)
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://meta-error', 'chan', 'a',
                              'keyring=archive-master'],
                environment), "%s/www/pool/a-a.tar.xz" % self.temp_directory)

        # valid device override
        shutil.rmtree("%s/www/pool/" % self.temp_directory)
        environment['device_name'] = "invalid"
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://valid-json', 'chan', 'a',
                              'keyring=archive-master,device=test'],
                environment), "%s/www/pool/a-a.tar.xz" % self.temp_directory)
        environment['device_name'] = "test"

        # valid index.json
        shutil.rmtree("%s/www/pool/" % self.temp_directory)
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://valid-json', 'chan', 'a',
                              'keyring=archive-master'],
                environment), "%s/www/pool/a-a.tar.xz" % self.temp_directory)

        # from cache
        self.assertEqual(
            generators.generate_file_remote_system_image(
                self.config, ['http://valid-json', 'chan', 'a',
                              'keyring=archive-master'],
                environment), "%s/www/pool/a-a.tar.xz" % self.temp_directory)

        # no match
        shutil.rmtree("%s/www/pool/" % self.temp_directory)
        self.assertEqual(
            generators.generate_file(self.config, "remote-system-image",
                                     ['http://no-match', 'chan', 'a',
                                      'keyring=archive-master'],
                                     environment), None)
