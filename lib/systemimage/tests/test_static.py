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

import codecs
import os
import subprocess
import unittest

binary = "/usr/bin/pyflakes3"
if not os.path.exists(binary):
    pyflakes = None
else:
    import pyflakes


FILTER_DIRS = [
    ".bzr",
    ".tox",
    "__pycache__",
    ]


class StaticTests(unittest.TestCase):
    def all_paths(self, shebang_py=None):
        paths = []
        for dirpath, dirnames, filenames in os.walk("."):
            for ignore in FILTER_DIRS:
                if ignore in dirnames:
                    dirnames.remove(ignore)
            filenames = [
                n for n in filenames
                if not n.startswith(".") and not n.endswith("~")]
            if dirpath.split(os.sep)[-1] == "bin":
                # Don't return this script unless we either don't care about
                # the shebangs, or it matches what's given in the argument.
                if shebang_py is None:
                    # We don't care, so add them all.
                    paths.extend(os.path.join(dirpath, filename)
                                 for filename in filenames)
                else:
                    # Make sure the last path component of the shebang
                    # matches.  Yes this a dumb, but effective test.
                    for filename in filenames:
                        full_path = os.path.join(dirpath, filename)
                        with codecs.open(
                                full_path, 'r', encoding='utf-8') as fp:
                            first_line = fp.readline()
                        if not first_line.startswith('#!'):
                            # Do we even know if it's Python?  The old code
                            # would assume so, so let's do the same.
                            paths.append(full_path)
                            continue
                        if first_line.split('/')[-1] == shebang_py:
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
        # Ignore some dubious pep8 constraints which are incompatible with this
        # package's existing coding style:
        # * E402 module level import not at top of file
        # * W503 line break before binary operator
        subp = subprocess.Popen(
            ["pep8", "--ignore=E129,E402,W503,W504", "--hang-closing"]
            + self.all_paths(),
            stdout=subprocess.PIPE, universal_newlines=True)
        output = subp.communicate()[0].splitlines()
        for line in output:
            print(line)
        self.assertEqual(0, len(output), output)

    @unittest.skipIf(pyflakes is None, "Missing pyflakes, skipping test.")
    def test_pyflakes3_clean(self):
        subp = subprocess.Popen(
            ["pyflakes3"] + self.all_paths(shebang_py='python3'),
            stdout=subprocess.PIPE, universal_newlines=True)
        output = subp.communicate()[0].splitlines()
        for line in output:
            print(line)
        self.assertEqual(0, len(output))
