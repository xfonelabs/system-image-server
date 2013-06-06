import glob
import os
import shutil
import tarfile
import tempfile
import unittest

from systemimage import gpg


class DiffTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.mkdtemp()
        self.temp_directory = temp_directory

    def tearDown(self):
        shutil.rmtree(self.temp_directory)

    def test_sign_file(self):
        if not os.path.isdir("gpg/keys/signing"):
            print("Missing signing key, can't proceed")
            return

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
