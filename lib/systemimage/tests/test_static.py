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

# Mostly copy/pasted from the cdimage test of the same name.

import os
import subprocess
import unittest


FILTER_DIRS = [
    '.bzr',
    '.tox',
    '__pycache__',
    ]


class StaticTests(unittest.TestCase):
    def all_paths(self):
        paths = []
        for dirpath, dirnames, filenames in os.walk("."):
            for ignore in FILTER_DIRS:
                if ignore in dirnames:
                    dirnames.remove(ignore)
            filenames = [
                n for n in filenames
                if not n.startswith(".") and not n.endswith("~")]
            if dirpath.split(os.sep)[-1] == "bin":
                for filename in filenames:
                    if filename in ("simg2img"):
                        continue
                    full_path = os.path.join(dirpath, filename)
                    paths.append(full_path)
            else:
                for filename in filenames:
                    if filename.endswith(".py"):
                        full_path = os.path.join(dirpath, filename)
                        paths.append(full_path)
        return paths

    @unittest.skipIf(not os.path.exists("/usr/bin/pep8"),
                     "Missing pep8, skipping test.")
    def test_pep8_clean(self):
        subp = subprocess.Popen(
            ["pep8"] + self.all_paths(),
            stdout=subprocess.PIPE, universal_newlines=True)
        output = subp.communicate()[0].splitlines()
        for line in output:
            print(line)
        self.assertEqual(0, len(output))

    @unittest.skipIf(not os.path.exists("/usr/bin/pyflakes"),
                     "Missing pyflakes, skipping test.")
    def test_pyflakes_clean(self):
        subp = subprocess.Popen(
            ["pyflakes"] + self.all_paths(),
            stdout=subprocess.PIPE, universal_newlines=True)
        output = subp.communicate()[0].splitlines()
        for line in output:
            print(line)
        self.assertEqual(0, len(output))

    @unittest.skipIf(not os.path.exists("/usr/bin/pyflakes3"),
                     "Missing pyflakes, skipping test.")
    def test_pyflakes3_clean(self):
        subp = subprocess.Popen(
            ["pyflakes3"] + self.all_paths(),
            stdout=subprocess.PIPE, universal_newlines=True)
        output = subp.communicate()[0].splitlines()
        for line in output:
            print(line)
        self.assertEqual(0, len(output))
