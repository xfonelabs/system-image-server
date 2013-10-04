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

from io import BytesIO, StringIO
from systemimage import config, generators, gpg, tools, tree

import json
import os
import shutil
import socket
import tarfile
import tempfile
import unittest

try:
    from unittest import mock
except ImportError:
    import mock


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
        self.assertEquals(
            generators.generate_delta(
                self.config,
                os.path.join(self.temp_directory, "version-1.tar.xz"),
                os.path.join(self.temp_directory, "version-2.tar.xz")),
            os.path.join(self.temp_directory, "version-2.tar.xz"))

        # Generate the diff
        self.assertEquals(
            generators.generate_delta(self.config, source_path_xz,
                                      destination_path_xz),
            os.path.join(self.config.publish_path, "pool",
                         "destination.delta-source.tar.xz"))

        # Check that we get cached entries
        generators.generate_delta(self.config, source_path_xz,
                                  destination_path_xz)

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

    @mock.patch("subprocess.call")
    def test_generate_file_cdimage_device(self, mock_call):
        def call_side_effect(cmd, stdout=None, stderr=None):
            if cmd[0] == "simg2img":
                shutil.copy(cmd[1], cmd[2])

            return True

        mock_call.side_effect = call_side_effect

        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Check the path and series requirement
        self.assertEquals(
            generators.generate_file_cdimage_device(self.config, [],
                                                    environment),
            None)

        # Check behaviour on invalid cdimage path
        self.assertEquals(
            generators.generate_file_cdimage_device(
                self.config, ['invalid-path', 'invalid-series'],
                environment),
            None)

        # Check behaviour on empty tree
        cdimage_tree = os.path.join(self.temp_directory, "cdimage")
        os.mkdir(cdimage_tree)
        self.assertEquals(
            generators.generate_file_cdimage_device(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing hash
        version_path = os.path.join(cdimage_tree, "1234")
        os.mkdir(version_path)
        self.assertEquals(
            generators.generate_file_cdimage_device(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing files
        for filename in ("SHA256SUMS",
                         "series-preinstalled-boot-armhf+test.img",
                         "series-preinstalled-recovery-armel+test.img",
                         "series-preinstalled-system-armel+test.img",
                         ".marked_good"):
            open(os.path.join(version_path, filename), "w+").close()
            self.assertEquals(
                generators.generate_file_cdimage_device(
                    self.config, [cdimage_tree, 'series', 'import=good'],
                    environment),
                None)

        # Check SHA256SUMS parsing
        with open(os.path.join(version_path, "SHA256SUMS"), "w+") as fd:
            fd.write("HASH *series-preinstalled-boot-armhf+test.img\n")
            fd.write("HASH *series-preinstalled-recovery-armel+test.img\n")

        self.assertEquals(
            generators.generate_file_cdimage_device(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Working run
        with open(os.path.join(version_path, "SHA256SUMS"), "w+") as fd:
            fd.write("HASH *series-preinstalled-boot-armhf+test.img\n")
            fd.write("HASH *series-preinstalled-recovery-armel+test.img\n")
            fd.write("HASH *series-preinstalled-system-armel+test.img\n")

        self.assertEquals(
            generators.generate_file(
                self.config, "cdimage-device", [cdimage_tree, 'series'],
                environment),
            os.path.join(self.config.publish_path, "pool",
                         "device-cbafd7270154b197d8a963751d653f968"
                         "1fef86f8ec1e6e679f55f677a3a1b94.tar.xz"))

        # Cached run
        self.assertEquals(
            generators.generate_file_cdimage_device(
                self.config, [cdimage_tree, 'series'],
                environment),
            os.path.join(self.config.publish_path, "pool",
                         "device-cbafd7270154b197d8a963751d653f968"
                         "1fef86f8ec1e6e679f55f677a3a1b94.tar.xz"))

    def test_generate_file_cdimage_ubuntu(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Check the path and series requirement
        self.assertEquals(
            generators.generate_file_cdimage_ubuntu(self.config, [],
                                                    environment),
            None)

        # Check behaviour on invalid cdimage path
        self.assertEquals(
            generators.generate_file_cdimage_ubuntu(
                self.config, ['invalid-path', 'invalid-series'],
                environment),
            None)

        # Check behaviour on empty tree
        cdimage_tree = os.path.join(self.temp_directory, "cdimage")
        os.mkdir(cdimage_tree)
        self.assertEquals(
            generators.generate_file_cdimage_ubuntu(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing hash
        version_path = os.path.join(cdimage_tree, "1234")
        os.mkdir(version_path)
        self.assertEquals(
            generators.generate_file_cdimage_ubuntu(
                self.config, [cdimage_tree, 'series'],
                environment),
            None)

        # Check behaviour on missing files
        for filename in ("SHA256SUMS",
                         "series-preinstalled-touch-armhf.tar.gz",
                         ".marked_good"):
            open(os.path.join(version_path, filename), "w+").close()
            self.assertEquals(
                generators.generate_file_cdimage_ubuntu(
                    self.config, [cdimage_tree, 'series', 'import=good'],
                    environment),
                None)

        # Working run
        with open(os.path.join(version_path, "SHA256SUMS"), "w+") as fd:
            fd.write("HASH *series-preinstalled-touch-armhf.tar.gz\n")

        tarball = os.path.join(version_path,
                               "series-preinstalled-touch-armhf.tar.gz")
        os.remove(tarball)
        tarball_obj = tarfile.open(tarball, "w:gz")

        ## SWAP.swap
        swap = tarfile.TarInfo()
        swap.name = "SWAP.swap"
        swap.size = 4
        tarball_obj.addfile(swap, BytesIO(b"test"))

        ## /etc/mtab
        mtab = tarfile.TarInfo()
        mtab.name = "etc/mtab"
        mtab.size = 4
        tarball_obj.addfile(mtab, BytesIO(b"test"))

        ## A hard link
        hl = tarfile.TarInfo()
        hl.name = "f"
        hl.type = tarfile.LNKTYPE
        hl.linkname = "a"
        tarball_obj.addfile(hl)

        ## A standard file
        sf = tarfile.TarInfo()
        sf.name = "f"
        sf.size = 4
        tarball_obj.addfile(sf, BytesIO(b"test"))

        tarball_obj.close()

        self.assertEquals(
            generators.generate_file(
                self.config, "cdimage-ubuntu", [cdimage_tree, 'series'],
                environment),
            os.path.join(self.config.publish_path, "pool",
                         "ubuntu-HASH.tar.xz"))

        # Cached run
        self.assertEquals(
            generators.generate_file_cdimage_ubuntu(
                self.config, [cdimage_tree, 'series'],
                environment),
            os.path.join(self.config.publish_path, "pool",
                         "ubuntu-HASH.tar.xz"))

    @mock.patch("systemimage.generators.urlretrieve")
    @mock.patch("systemimage.generators.urlopen")
    def test_generate_file_http(self, mock_urlopen, mock_urlretrieve):
        def urlopen_side_effect(url):
            if url.endswith("timeout"):
                raise socket.timeout

            if url.endswith("error"):
                raise IOError()

            return StringIO(u"42")
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
        self.assertEquals(
            generators.generate_file_http(self.config, [], {}),
            None)

        # Timeout without monitor
        generators.CACHE = {}
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/timeout"],
                                     environment),
            None)

        # Error without monitor
        generators.CACHE = {}
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/error"],
                                     environment),
            None)

        # Timeout with monitor
        generators.CACHE = {}
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/timeout",
                                      "monitor=http://1.2.3.4/timeout"],
                                     environment),
            None)

        # Error with monitor
        generators.CACHE = {}
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/error",
                                      "monitor=http://1.2.3.4/error"],
                                     environment),
            None)

        # Normal run without monitor
        generators.CACHE = {}
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-33b3daaf6724164f00467103907a590ca"
                         "2d4c6a0d1b63f93a3018cef1020df3b.tar.xz"))

        # Cached run without monitor
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-33b3daaf6724164f00467103907a590ca"
                         "2d4c6a0d1b63f93a3018cef1020df3b.tar.xz"))

        # Cached run without monitor (no path caching)
        generators.CACHE = {}
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file"],
                                     environment),
            os.path.join(self.config.publish_path, "pool",
                         "http-33b3daaf6724164f00467103907a590ca"
                         "2d4c6a0d1b63f93a3018cef1020df3b.tar.xz"))

        # Normal run with monitor
        generators.CACHE = {}
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file",
                                      "monitor=http://1.2.3.4/buildid"],
                                     environment),
            os.path.join(self.config.publish_path, "pool", "http-42.tar.xz"))

        # Cached run with monitor
        self.assertEquals(
            generators.generate_file(self.config, "http",
                                     ["http://1.2.3.4/file",
                                      "monitor=http://1.2.3.4/buildid"],
                                     environment),
            os.path.join(self.config.publish_path, "pool", "http-42.tar.xz"))

    def test_generate_file_system_image(self):
        environment = {}
        environment['channel_name'] = "test"
        environment['device'] = self.device
        environment['device_name'] = "test"
        environment['new_files'] = []
        environment['version'] = 1234
        environment['version_detail'] = []

        # Check the arguments count
        self.assertEquals(
            generators.generate_file_system_image(self.config, [], {}),
            None)

        # Check for channel name
        self.assertEquals(
            generators.generate_file_system_image(self.config,
                                                  ['invalid', 'file'],
                                                  {}),
            None)

        # Check for device name
        environment['device_name'] = "invalid"
        self.assertEquals(
            generators.generate_file_system_image(self.config,
                                                  ['test', 'file'],
                                                  environment),
            None)

        # Run against an empty channel
        environment['device_name'] = "test"
        self.assertEquals(
            generators.generate_file_system_image(self.config,
                                                  ['test', 'file'],
                                                  environment),
            None)

        # Publish some random stuff
        open(os.path.join(self.config.publish_path, "file-1.tar.xz"),
             "w+").close()

        with open(os.path.join(self.config.publish_path, "file-1.json"),
                  "w+") as fd:
            fd.write(json.dumps({'version_detail': "abcd"}))

        gpg.sign_file(self.config, "image-signing",
                      os.path.join(self.config.publish_path, "file-1.tar.xz"))
        self.device.create_image("full", 1234, "abc", ["file-1.tar.xz"],
                                 minversion=1233, bootme=True)

        # Invalid filename
        self.assertEquals(
            generators.generate_file_system_image(self.config,
                                                  ['test', 'invalid'],
                                                  environment),
            None)

        # Normal run
        self.assertEquals(
            generators.generate_file(self.config, "system-image",
                                                  ['test', 'file'],
                                                  environment),
            os.path.join(self.config.publish_path, "file-1.tar.xz"))
