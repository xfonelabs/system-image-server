# -*- coding: utf-8 -*-

# Copyright (C) 2015 Canonical Ltd.
# Author: Łukasz 'sil2100' Zemczak <lukasz.zemczak@ubuntu.com>

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
import imp
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest

from systemimage.helpers import chdir
from systemimage.testing.helpers import HAS_TEST_KEYS, MISSING_KEYS_WARNING


class TagImageScriptTests(unittest.TestCase):
    def setUp(self):
        bin_dir = os.path.dirname(os.path.dirname(__file__))
        self.script_name = "tag-image"
        self.script = imp.load_source(
            self.script_name,
            os.path.join(bin_dir, self.script_name))

    def test_set_tag(self):
        """Set a basic tag."""
        version_detail_list = [
            "device=20150821-736d127",
            "custom=20150925-901-35-40-vivid",
            "keyring=archive-master",
            "version=6"]
        self.script.set_tag(version_detail_list, "OTA-x")
        self.assertTrue("tag=OTA-x" in version_detail_list)
        size = len([x for x in version_detail_list if x.startswith("tag=")])
        self.assertEqual(size, 1)

    def test_set_tag_rewrite(self):
        """Make sure tags can be rewritten."""
        version_detail_list = [
            "device=20150821-736d127",
            "custom=20150925-901-35-40-vivid",
            "tag=something",
            "keyring=archive-master",
            "tag=different",
            "version=6"]
        self.script.set_tag(version_detail_list, "OTA-x")
        self.assertTrue("tag=OTA-x" in version_detail_list)
        size = len([x for x in version_detail_list if x.startswith("tag=")])
        self.assertEqual(size, 1)

#    @unittest.skipUnless(HAS_TEST_KEYS, MISSING_KEYS_WARNING)
#    def test_channels(self):
        