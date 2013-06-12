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

import glob
import gpgme
import os
import shutil
import tempfile
import time
import unittest

from systemimage import gpg


class GPGTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        os.mkdir("%s/keyrings" % temp_directory)
        self.temp_directory = temp_directory

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    @unittest.skipIf(not os.path.exists("tests/keys/generated"),
                     "No GPG testing keys present. Run tests/generate-keys")
    def test_sign_file(self):
        test_string = "test-string"

        test_file = "%s/test.txt" % self.temp_directory
        with open(test_file, "w+") as fd:
            fd.write(test_string)

        # Detached armored signature
        [os.remove(path) for path in glob.glob("%s.*" % test_file)]
        self.assertTrue(gpg.sign_file("signing", test_file))
        self.assertTrue(os.path.exists("%s.asc" % test_file))

        # Detached binary signature
        [os.remove(path) for path in glob.glob("%s.*" % test_file)]
        self.assertTrue(gpg.sign_file("signing", test_file, armor=False))
        self.assertTrue(os.path.exists("%s.sig" % test_file))

        # Standard armored signature
        [os.remove(path) for path in glob.glob("%s.*" % test_file)]
        self.assertTrue(gpg.sign_file("signing", test_file, detach=False))
        self.assertTrue(os.path.exists("%s.asc" % test_file))

        # Standard binary signature
        [os.remove(path) for path in glob.glob("%s.*" % test_file)]
        self.assertTrue(gpg.sign_file("signing", test_file, detach=False,
                                      armor=False))
        self.assertTrue(os.path.exists("%s.gpg" % test_file))

        # Failure cases
        self.assertRaises(Exception, gpg.sign_file, "invalid", test_file)
        [os.remove(path) for path in glob.glob("%s.*" % test_file)]
        gpg.sign_file("signing", test_file)
        self.assertRaises(Exception, gpg.sign_file, "signing", test_file)
        self.assertRaises(Exception, gpg.sign_file, "signing", "invalid")

    @unittest.skipIf(not os.path.exists("tests/keys/generated"),
                     "No GPG testing keys present. Run tests/generate-keys")
    def test_keyring(self):
        keyring_path = "%s/keyrings" % self.temp_directory

        os.environ['KEYRING_PATH'] = keyring_path
        keyring = gpg.Keyring("testing")
        self.assertTrue(os.path.exists("%s/testing" % keyring_path))
        self.assertEquals(keyring.keyring_model, None)
        self.assertEquals(keyring.keyring_name, "testing")
        self.assertEquals(keyring.keyring_type, None)
        self.assertEquals(keyring.keyring_expiry, None)

        expiry = int(time.strftime("%s", time.gmtime()))
        keyring.set_metadata(keyring_type="test", keyring_model="test",
                             keyring_expiry=expiry)

        keyring = gpg.Keyring("testing")
        self.assertEquals(keyring.keyring_model, "test")
        self.assertEquals(keyring.keyring_name, "testing")
        self.assertEquals(keyring.keyring_type, "test")
        self.assertEquals(keyring.keyring_expiry, expiry)

        keyring.import_keys("tests/keys/signing/")

        # Check that the keyring matches
        keys = keyring.list_keys()
        self.assertTrue(len(keys), 1)
        key_id, key_bit, [key_desc] = keys[0]
        self.assertEquals(key_bit, 2048)
        self.assertEquals(key_desc,
                          "[TESTING] Ubuntu System Image Signing Key (YYYY) "
                          "<system-image@ubuntu.com>")

        temp_key = "%s/key.asc" % self.temp_directory
        keyring.export_key(temp_key, key_id)
        self.assertTrue(os.path.exists(temp_key))
        keyring.del_key(key_id)
        self.assertEquals(keyring.list_keys(), [])
        keyring.import_key(temp_key)

        # Check that the keyring matches
        keys = keyring.list_keys()
        self.assertTrue(len(keys), 1)
        key_id, key_bit, [key_desc] = keys[0]
        self.assertEquals(key_bit, 2048)
        self.assertEquals(key_desc,
                          "[TESTING] Ubuntu System Image Signing Key (YYYY) "
                          "<system-image@ubuntu.com>")

        self.assertRaises(gpgme.GpgmeError, keyring.export_key,
                          "missing", "abcd")
        self.assertRaises(gpgme.GpgmeError, keyring.del_key, "abcd")

        temp_tarball = "%s/keyring.tar" % self.temp_directory
        keyring.generate_tarball(temp_tarball)
        keyring.generate_tarball(temp_tarball)
        self.assertTrue(os.path.exists(temp_tarball))

        keyring.generate_tarball()
        self.assertTrue(os.path.exists("%s/testing.tar" % keyring_path))

        os.remove("%s/testing.tar" % keyring_path)
        shutil.rmtree("%s/testing" % keyring_path)
