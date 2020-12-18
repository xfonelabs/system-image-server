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
import stat
import subprocess
import tarfile
import tempfile
import unittest
from datetime import datetime
from glob import glob

import six
from systemimage import config, gpg, tools, tree
from systemimage.helpers import chdir
from systemimage.testing.helpers import HAS_TEST_KEYS, MISSING_KEYS_WARNING


def safe_extract(tarfile_path, tempdir):
    # Safely unpack the tarball, ignoring any device nodes or paths that point
    # outside the tempdir (using a shorthand of any absolute paths or
    # references to ../)
    unpackables = []
    with tarfile.open(tarfile_path) as tf:
        for member in tf:
            if member.isdev():
                continue
            # Sanity check the member's path name.  Disallow any absolute paths
            # or paths with .. in them.
            if os.path.isabs(member.name) or '..' in member.name.split('/'):
                continue
            unpackables.append(member)
        # Do the extraction.
        tf.extractall(tempdir, members=unpackables)


class ToolTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory
        self.old_path = os.environ.get("PATH", None)

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

    def tearDown(self):
        shutil.rmtree(self.temp_directory)
        if self.old_path:
            os.environ['PATH'] = self.old_path

    def test_generate_version_tarball(self):
        # Run without version_detail or channel_target
        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(self.config, "testing", "test",
                                       "1.2.3.4",
                                       version_tarball, "a/b/version",
                                       "a/b/channel")

        version_tarfile = tarfile.open(version_tarball, "r:")

        version_file = version_tarfile.extractfile("a/b/version")
        self.assertTrue(version_file)
        self.assertEqual(version_file.read().decode("utf-8"), "1.2.3.4\n")
        version_file.close()

        channel_file = version_tarfile.extractfile("a/b/channel")
        self.assertTrue(channel_file)
        self.assertEqual(channel_file.read().decode("utf-8"), """[service]
base: system-image.example.net
http_port: 880
https_port: 8443
channel: testing
device: test
build_number: 1.2.3.4
""")
        channel_file.close()
        os.remove(version_tarball)

        # Run without version_detail or channel_target but custom ports
        self.config.public_http_port = 0
        self.config.public_https_port = 0

        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(self.config, "testing", "test",
                                       "1.2.3.4",
                                       version_tarball, "a/b/version",
                                       "a/b/channel")

        with tarfile.open(version_tarball, "r:") as version_tarfile:

            version_file = version_tarfile.extractfile("a/b/version")
            self.assertTrue(version_file)
            self.assertEqual(version_file.read().decode("utf-8"), "1.2.3.4\n")
            version_file.close()

            channel_file = version_tarfile.extractfile("a/b/channel")
            self.assertTrue(channel_file)
            self.assertEqual(channel_file.read().decode("utf-8"), """[service]
base: system-image.example.net
http_port: disabled
https_port: disabled
channel: testing
device: test
build_number: 1.2.3.4
""")
            channel_file.close()
        os.remove(version_tarball)
        self.config.public_http_port = 880
        self.config.public_https_port = 8443

        # Run with version_detail and channel_target
        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(self.config, "testing", "test",
                                       "1.2.3.4",
                                       version_tarball, "a/b/version",
                                       "a/b/channel", "abcdef", "origin")

        with tarfile.open(version_tarball, "r:") as version_tarfile:

            version_file = version_tarfile.extractfile("a/b/version")
            self.assertTrue(version_file)
            self.assertEqual(version_file.read().decode("utf-8"), "1.2.3.4\n")
            version_file.close()

            channel_file = version_tarfile.extractfile("a/b/channel")
            self.assertTrue(channel_file)
            self.assertEqual(channel_file.read().decode("utf-8"), """[service]
base: system-image.example.net
http_port: 880
https_port: 8443
channel: testing
device: test
build_number: 1.2.3.4
channel_target: origin
version_detail: abcdef
""")
            channel_file.close()
        os.remove(version_tarball)

    def test_gzip_compress(self):
        test_string = "test-string"

        # Simple compress/uncompress
        test_file = "%s/test.txt" % self.temp_directory
        with open(test_file, "w+") as fd:
            fd.write(test_string)

        self.assertEqual(tools.gzip_compress(test_file), "%s.gz" % test_file)
        self.assertTrue(os.path.exists("%s.gz" % test_file))

        os.remove(test_file)
        self.assertFalse(os.path.exists(test_file))

        self.assertEqual(tools.gzip_uncompress("%s.gz" % test_file),
                         test_file)
        self.assertTrue(os.path.exists(test_file))

        with open(test_file, "r") as fd:
            self.assertEqual(fd.read(), test_string)

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

        self.assertEqual(tools.xz_compress(test_file), 0)
        self.assertTrue(os.path.exists("%s.xz" % test_file))

        os.remove(test_file)
        self.assertFalse(os.path.exists(test_file))

        self.assertEqual(tools.xz_uncompress("%s.xz" % test_file), 0)
        self.assertTrue(os.path.exists(test_file))
        os.remove("%s.xz" % test_file)

        with open(test_file, "r") as fd:
            self.assertEqual(fd.read(), test_string)

        # Forcing xz
        bin_dir = os.path.join(self.temp_directory, "bin")
        os.mkdir(bin_dir)
        os.symlink("/usr/bin/xz", os.path.join(bin_dir, "xz"))
        os.environ['PATH'] = bin_dir

        test_file = "%s/test.txt" % self.temp_directory
        with open(test_file, "w+") as fd:
            fd.write(test_string)

        self.assertEqual(tools.xz_compress(test_file), 0)
        self.assertTrue(os.path.exists("%s.xz" % test_file))

        os.remove(test_file)
        self.assertFalse(os.path.exists(test_file))

        self.assertEqual(tools.xz_uncompress("%s.xz" % test_file), 0)
        self.assertTrue(os.path.exists(test_file))

        with open(test_file, "r") as fd:
            self.assertEqual(fd.read(), test_string)

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
        os.environ['PATH'] = "::%s" % bin_dir
        self.assertTrue(tools.find_on_path("program"))

    def test_find_on_path_present_not_executable(self):
        bin_dir = os.path.join(self.temp_directory, "bin")
        os.mkdir(bin_dir)
        program = os.path.join(bin_dir, "program")
        open(program, "w+").close()
        os.environ['PATH'] = bin_dir
        self.assertFalse(tools.find_on_path("program"))

    def test_manipulate_recovery_header(self):
        """Check if stripping and reattaching recovery headers works."""
        source_path = os.path.join(self.temp_directory, "source")
        stripped_path = os.path.join(self.temp_directory, "stripped")
        reattached_path = os.path.join(self.temp_directory, "reattached")

        header = bytearray(512)
        contents = b"RECOVERY"
        for i in range(0, 64):
            header[i] = i
        with open(source_path, "wb+") as f:
            f.write(header)
            f.write(contents)

        stripped = tools.strip_recovery_header(source_path, stripped_path)
        self.assertEqual(header, bytes(stripped))
        with open(stripped_path, "rb") as f:
            self.assertEqual(f.read(), contents)

        tools.reattach_recovery_header(stripped_path, reattached_path,
                                       stripped)
        with open(reattached_path, "rb") as f, open(source_path, "rb") as fs:
            self.assertEqual(f.read(), fs.read())

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_repack_recovery_keyring(self):
        # Generate the keyring tarballs
        env = dict(os.environ)
        env['SYSTEM_IMAGE_ROOT'] = self.temp_directory
        subprocess.call(["bin/generate-keyrings"], env=env)

        # Generate a fake recovery partition
        os.makedirs("%s/initrd/usr/share/system-image/" % self.temp_directory)
        open("%s/initrd/usr/share/system-image/archive-master.tar.xz" %
             self.temp_directory, "w+").close()
        open("%s/initrd/usr/share/system-image/archive-master.tar.xz.asc" %
             self.temp_directory, "w+").close()

        initrd_dir = os.path.join(self.temp_directory, "initrd")
        with chdir(initrd_dir):
            find = subprocess.Popen(["find", "."], stdout=subprocess.PIPE)
            with open("../initrd.img", "w+") as fd:
                with open(os.path.devnull, "w") as devnull:
                    subprocess.call(["fakeroot", "cpio",
                                     "-o", "--format=newc"],
                                    stdin=find.stdout,
                                    stdout=fd,
                                    stderr=devnull)

        tools.gzip_compress(os.path.join(self.temp_directory, "initrd.img"),
                            os.path.join(self.temp_directory, "initrd.gz"))

        with open("%s/kernel" % self.temp_directory, "w+") as fd:
            fd.write("test")

        with open("%s/bootimg.cfg" % self.temp_directory, "w+") as fd:
            fd.write("""bootsize=0x12345
""")

        os.makedirs("%s/partitions/" % self.temp_directory)
        open("%s/partitions/boot.img" % self.temp_directory, "w+").close()

        with open(os.devnull, "w") as devnull:
            subprocess.call(["abootimg", "--create",
                             "%s/partitions/recovery.img" %
                             self.temp_directory,
                             "-k", "%s/kernel" % self.temp_directory,
                             "-r", "%s/initrd.gz" % self.temp_directory,
                             "-f", "%s/bootimg.cfg" % self.temp_directory],
                            stderr=devnull, stdout=devnull)

            subprocess.call(["tar", "Jcf",
                             "%s/recovery.tar.xz" % self.temp_directory,
                             "-C", self.temp_directory,
                             "partitions/"], stderr=devnull, stdout=devnull)

            subprocess.call(["tar", "Jcf",
                             "%s/empty.tar.xz" % self.temp_directory,
                             "-C", self.temp_directory,
                             "initrd/"], stderr=devnull, stdout=devnull)

        # Try an empty tarball
        self.assertEqual(tools.repack_recovery_keyring(
            self.config, "%s/empty.tar.xz" % self.temp_directory,
            "archive-master"), False)

        # Try a repack
        tools.repack_recovery_keyring(self.config, "%s/recovery.tar.xz" %
                                                   self.temp_directory,
                                      "archive-master")

        tools.reattach_recovery_header(os.path.join(self.temp_directory,
                                                    "initrd.gz"),
                                       os.path.join(self.temp_directory,
                                                    "initrd.header"),
                                       bytearray(512))

        with open(os.devnull, "w") as devnull:
            subprocess.call(["abootimg", "--create",
                             "%s/partitions/recovery.img" %
                             self.temp_directory,
                             "-k", "%s/kernel" % self.temp_directory,
                             "-r", "%s/initrd.header" % self.temp_directory,
                             "-f", "%s/bootimg.cfg" % self.temp_directory],
                            stderr=devnull, stdout=devnull)

            subprocess.call(["tar", "Jcf",
                             "%s/recovery-spec.tar.xz" % self.temp_directory,
                             "-C", self.temp_directory,
                             "partitions/"], stderr=devnull, stdout=devnull)

        # Try repacking in case of a recovery with a special header
        tools.repack_recovery_keyring(self.config, "%s/recovery-spec.tar.xz" %
                                                   self.temp_directory,
                                      "archive-master", "krillin")

    def test_system_image_30_symlinks(self):
        # To support system-image 3.0, generate symlinks for config.d
        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(self.config, "testing", "test",
                                       "1.2.3.4",
                                       version_tarball)
        version_tarfile = tarfile.open(version_tarball, "r:")
        default_ini = version_tarfile.getmember(
            "system/etc/system-image/config.d/00_default.ini")
        self.assertEqual(default_ini.type, tarfile.SYMTYPE)
        self.assertEqual(default_ini.linkname, "../client.ini")
        channel_ini = version_tarfile.getmember(
            "system/etc/system-image/config.d/01_channel.ini")
        self.assertEqual(channel_ini.type, tarfile.SYMTYPE)
        self.assertEqual(channel_ini.linkname, "../channel.ini")

    def test_system_image_30_permissions(self):
        # The etc/system-image/config.d directory should be created with
        # drwxrwxr-x permissions.  LP: #1454447
        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(self.config, "testing", "test",
                                       "1.2.3.4",
                                       version_tarball)
        # Extract the tarfile to another temp directory, so that we can
        # exactly compare extracted directory modes.
        extract_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, extract_dir)
        safe_extract(version_tarball, extract_dir)
        config_d = os.path.join(
            extract_dir, "system", "etc", "system-image", "config.d")
        mode = stat.S_IMODE(os.stat(config_d).st_mode)
        self.assertEqual(mode, 0o775,
                         'got 0o{:o}, expected 0o775'.format(mode))

    def test_system_image_30_mtimes(self):
        # The etc/system-image/config.d directory and the 00_default.ini,
        # 01_channel.ini symlinks should have proper mtimes.  LP: #1558190
        version_tarball = "%s/version.tar" % self.temp_directory
        tools.generate_version_tarball(self.config, "testing", "test",
                                       "1.2.3.4",
                                       version_tarball)
        # Extract the tarfile to another temp directory, so that we can
        # exactly check mtimes.
        extract_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, extract_dir)
        safe_extract(version_tarball, extract_dir)
        config_d = os.path.join(
            extract_dir, "system", "etc", "system-image", "config.d")
        epoch = datetime(1970, 1, 1)
        self.assertGreater(datetime.fromtimestamp(os.stat(config_d).st_mtime),
                           epoch)
        ini_files = glob(os.path.join(config_d, '*.ini'))
        # Future-proof: at least two ini files.
        self.assertGreaterEqual(len(ini_files), 2)
        for ini_file in ini_files:
            mtime = os.lstat(ini_file).st_mtime
            self.assertGreater(datetime.fromtimestamp(mtime), epoch)

    def test_set_tag_on_version_detail(self):
        """Set a basic tag."""
        version_detail_list = [
            "device=20150821-736d127",
            "custom=20150925-901-35-40-vivid",
            "keyring=archive-master",
            "version=6"]
        tools.set_tag_on_version_detail(version_detail_list, "OTA-x")
        self.assertIn("tag=OTA-x", version_detail_list)
        size = len([x for x in version_detail_list if x.startswith("tag=")])
        self.assertEqual(size, 1)

    def test_set_tag_on_version_detail_rewrite(self):
        """Make sure tags can be rewritten."""
        version_detail_list = [
            "device=20150821-736d127",
            "custom=20150925-901-35-40-vivid",
            "tag=something",
            "keyring=archive-master",
            "tag=different",
            "version=6"]
        tools.set_tag_on_version_detail(version_detail_list, "OTA-x")
        self.assertIn("tag=OTA-x", version_detail_list)
        size = len([x for x in version_detail_list if x.startswith("tag=")])
        self.assertEqual(size, 1)

    def test_set_tag_on_version_detail_clear(self):
        """Clear the tag."""
        version_detail_list = [
            "device=20150821-736d127",
            "custom=20150925-901-35-40-vivid",
            "tag=OTA-x",
            "keyring=archive-master"]
        tools.set_tag_on_version_detail(version_detail_list, "")
        self.assertNotIn("tag=OTA-x", version_detail_list)
        size = len([x for x in version_detail_list if x.startswith("tag=")])
        self.assertEqual(size, 0)

    def test_extract_files_and_version(self):
        """Check if version_detail is correctly extracted"""
        os.mkdir(self.config.publish_path)

        version = 12
        version_detail = "device=1.2.3.4,version=12,tag=OTX-x"
        version_file = "version-%s.tar.xz" % version
        version_path = os.path.join(self.config.publish_path, version_file)
        tools.generate_version_metadata(
            self.config,
            version,
            "some/channel",
            "testing",
            version_path,
            version_detail)

        files = [
            {'path': version_file},
            {'path': "some/file"},
            {'path': "some/other"}]
        new_files = []
        expected_files = [os.path.join(
            self.config.publish_path, f['path']) for f in files[1:]]

        returned_detail = tools.extract_files_and_version(
            self.config, files, version, new_files)

        self.assertEqual(returned_detail, version_detail)
        six.assertCountEqual(self, expected_files, new_files)

    @unittest.skip("Current deltabase handling is broken")
    def test_get_required_deltas(self):
        """Check if a proper list of valid deltabases is found."""
        config_path = os.path.join(self.temp_directory, "etc", "config")
        with open(config_path, "w+") as fd:
            fd.write("""[global]
base_path = %s
gpg_key_path = %s
channels = testing
public_fqdn = system-image.example.net
public_http_port = 880
public_https_port = 8443

[channel_testing]
type = manual
deltabase = base1, base2
""" % (self.temp_directory, os.path.join(os.getcwd(), "tools", "keys")))
        test_config = config.Config(config_path)
        os.makedirs(test_config.publish_path)

        test_tree = tree.Tree(test_config)
        test_tree.create_channel("base1")
        test_tree.create_device("base1", "test")
        test_tree.create_channel("base2")
        test_tree.create_device("base2", "test")
        test_tree.create_channel("testing")
        test_tree.create_device("testing", "test")

        image_file = os.path.join(self.config.publish_path, "test_file")
        open(image_file, "w+").close()
        gpg.sign_file(test_config, "image-signing", image_file)

        device = test_tree.get_device("base1", "test")
        device.create_image("full", 1, "abc",
                            [image_file])
        base_image1 = device.get_image("full", 1)

        device = test_tree.get_device("base2", "test")
        device.create_image("full", 21, "abcd",
                            [image_file])
        base_image2 = device.get_image("full", 21)

        device = test_tree.get_device("testing", "test")
        device.create_image("full", 2, "abce",
                            [image_file])

        delta_base = tools.get_required_deltas(
            test_config, test_tree, "testing", "test")

        six.assertCountEqual(
            self, [base_image1, base_image2], delta_base)

    def test_guess_file_compression(self):
        """Check if we can correctly guess compression algorithms."""
        test_string = "test-string"

        # Simple compress/uncompress
        test_file = os.path.join(self.temp_directory, "test.txt")
        with open(test_file, "w+") as fd:
            fd.write(test_string)

        self.assertIsNone(tools.guess_file_compression(test_file))

        xz_file = os.path.join(self.temp_directory, "test.xz")
        tools.xz_compress(test_file, xz_file)
        self.assertEqual(
            tools.guess_file_compression(xz_file), "xz")

        gzip_file = os.path.join(self.temp_directory, "test.gz")
        tools.gzip_compress(test_file, gzip_file)
        self.assertEqual(
            tools.guess_file_compression(gzip_file), "gzip")
