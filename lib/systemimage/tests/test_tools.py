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

from systemimage import config, tools
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

    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
    def test_repack_recovery_keyring(self):
        # Generate the keyring tarballs
        env = dict(os.environ)
        env['SYSTEM_IMAGE_ROOT'] = self.temp_directory
        subprocess.call(["bin/generate-keyrings"], env=env)

        # Generate a fake recovery partition
        os.makedirs("%s/initrd/etc/system-image/" % self.temp_directory)
        open("%s/initrd/etc/system-image/archive-master.tar.xz" %
             self.temp_directory, "w+").close()
        open("%s/initrd/etc/system-image/archive-master.tar.xz.asc" %
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
        try:
            safe_extract(version_tarball, extract_dir)
            config_d = os.path.join(
                extract_dir, "system", "etc", "system-image", "config.d")
            mode = stat.S_IMODE(os.stat(config_d).st_mode)
        finally:
            shutil.rmtree(extract_dir)
        self.assertEqual(mode, 0o775,
                         'got 0o{:o}, expected 0o775'.format(mode))