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
import sys
import tarfile
import tempfile
import unittest
from io import BytesIO, StringIO

from systemimage.diff import ImageDiff, compare_files


class DiffTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temp_directory = temp_directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_directory)

        source_tarball_path = os.path.join(temp_directory, "source.tar")
        target_tarball_path = os.path.join(temp_directory, "target.tar")

        source_tarball = tarfile.open(
            source_tarball_path, "w", encoding="utf-8")
        target_tarball = tarfile.open(
            target_tarball_path, "w", encoding="utf-8")

        # Standard file
        a = tarfile.TarInfo()
        a.name = "a"
        a.size = 4

        # Standard file
        b = tarfile.TarInfo()
        b.name = "b"
        b.size = 4

        # Standard directory
        c_dir = tarfile.TarInfo()
        c_dir.name = "c"
        c_dir.type = tarfile.DIRTYPE
        c_dir.mode = 0o755

        # Standard file
        c = tarfile.TarInfo()
        c.name = "c/c"
        c.size = 4

        # Standard file
        d_source = tarfile.TarInfo()
        d_source.name = "c/d"
        d_source.size = 8
        d_source.mtime = 1000

        # Standard file
        d_target = tarfile.TarInfo()
        d_target.name = "c/d"
        d_target.size = 8
        d_target.mtime = 1234

        # Symlink
        e = tarfile.TarInfo()
        e.name = "e"
        e.type = tarfile.SYMTYPE
        e.linkname = "a"

        # Hard link
        f = tarfile.TarInfo()
        f.name = "f"
        f.type = tarfile.LNKTYPE
        f.linkname = "a"

        # Standard file
        g_source = tarfile.TarInfo()
        g_source.name = "c/g"
        g_source.size = 4
        g_source.mtime = 1000

        # Standard file
        g_target = tarfile.TarInfo()
        g_target.name = "c/g"
        g_target.size = 4
        g_target.mtime = 1001

        # Hard link
        h_source = tarfile.TarInfo()
        h_source.name = "c/h"
        h_source.type = tarfile.LNKTYPE
        h_source.linkname = "d"
        h_source.mtime = 1000

        # Hard link
        h_target = tarfile.TarInfo()
        h_target.name = "c/h"
        h_target.type = tarfile.LNKTYPE
        h_target.linkname = "d"
        h_target.mtime = 1001

        # Hard link
        i = tarfile.TarInfo()
        i.name = "c/a_i"
        i.type = tarfile.LNKTYPE
        i.linkname = "c"

        # Dangling symlink
        j = tarfile.TarInfo()
        j.name = "c/j"
        j.type = tarfile.SYMTYPE
        j.linkname = "j_non-existent"

        # Standard directory
        k_dir = tarfile.TarInfo()
        k_dir.name = "dir"
        k_dir.type = tarfile.DIRTYPE
        k_dir.mode = 0o755

        # Dangling symlink
        link = tarfile.TarInfo()
        link.name = "dir"
        link.type = tarfile.SYMTYPE
        link.linkname = "l_non-existent"

        # Standard file
        m_source = tarfile.TarInfo()
        m_source.name = "m"
        m_source.size = 4

        # Hard link
        m_target = tarfile.TarInfo()
        m_target.name = "m"
        m_target.type = tarfile.LNKTYPE
        m_target.linkname = "n"

        # Hard link
        n_source = tarfile.TarInfo()
        n_source.name = "n"
        n_source.type = tarfile.LNKTYPE
        n_source.linkname = "m"

        # Standard file
        n_target = tarfile.TarInfo()
        n_target.name = "n"
        n_target.size = 4

        # Hard link
        o_source = tarfile.TarInfo()
        o_source.name = "system/o.1"
        o_source.type = tarfile.LNKTYPE
        o_source.linkname = "system/o"

        # Standard file
        o_target = tarfile.TarInfo()
        o_target.name = "system/o"
        o_target.size = 4

        # Unicode file
        p_source = tarfile.TarInfo()
        p_source.name = u"system/中文中文中文"
        p_source.size = 4

        source_tarball.addfile(a, BytesIO(b"test"))
        source_tarball.addfile(a, BytesIO(b"test"))
        source_tarball.addfile(a, BytesIO(b"test"))
        source_tarball.addfile(b, BytesIO(b"test"))
        source_tarball.addfile(c_dir)
        source_tarball.addfile(d_source, BytesIO(b"test-abc"))
        source_tarball.addfile(g_source, BytesIO(b"test"))
        source_tarball.addfile(h_source, BytesIO(b"test"))
        source_tarball.addfile(k_dir)
        source_tarball.addfile(m_source, BytesIO(b"test"))
        source_tarball.addfile(n_source)
        source_tarball.addfile(p_source)

        target_tarball.addfile(a, BytesIO(b"test"))
        target_tarball.addfile(c_dir)
        target_tarball.addfile(c, BytesIO(b"test"))
        target_tarball.addfile(d_target, BytesIO(b"test-def"))
        target_tarball.addfile(e)
        target_tarball.addfile(f)
        target_tarball.addfile(g_target, BytesIO(b"test"))
        target_tarball.addfile(h_target, BytesIO(b"test"))
        target_tarball.addfile(i)
        target_tarball.addfile(j)
        target_tarball.addfile(link)
        target_tarball.addfile(n_target, BytesIO(b"test"))
        target_tarball.addfile(m_target)
        target_tarball.addfile(o_source)
        target_tarball.addfile(o_target)

        source_tarball.close()
        target_tarball.close()

        self.imagediff = ImageDiff(source_tarball_path, target_tarball_path)
        self.source_tarball_path = source_tarball_path
        self.target_tarball_path = target_tarball_path

    def test_content(self):
        content_set, content_dict = self.imagediff.scan_content("source")
        self.assertEqual(sorted(content_dict.keys()),
                         ['a', 'b', 'c', 'c/d', 'c/g', 'c/h', 'dir', 'm',
                          'n', 'system/中文中文中文'])

        content_set, content_dict = self.imagediff.scan_content("target")
        self.assertEqual(sorted(content_dict.keys()),
                         ['a', 'c', 'c/a_i', 'c/c', 'c/d', 'c/g', 'c/h',
                          'c/j', 'dir', 'e', 'f', 'm', 'n', 'system/o',
                          'system/o.1'])

    def test_content_invalid_image(self):
        self.assertRaises(KeyError, self.imagediff.scan_content, "invalid")

    def test_compare_files(self):
        self.assertEqual(compare_files(None, None), True)
        self.assertEqual(compare_files(None, BytesIO(b"abc")), False)

    def test_compare_image(self):
        diff_set = self.imagediff.compare_images()
        self.assertTrue(("c/a_i", "add") in diff_set)

    def test_print_changes(self):
        # Redirect stdout
        old_stdout = sys.stdout

        # FIXME: Would be best to have something that works with both version
        if sys.version[0] == "3":
            sys.stdout = StringIO()
        else:
            sys.stdout = BytesIO()

        self.imagediff.print_changes()

        # Unredirect stdout
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        self.assertMultiLineEqual(output, """ - b (del)
 - c/a_i (add)
 - c/c (add)
 - c/d (mod)
 - c/h (mod)
 - c/j (add)
 - dir (mod)
 - e (add)
 - f (add)
 - system/o (add)
 - system/o.1 (add)
 - system/中文中文中文 (del)
""")

    def test_generate_tarball(self):
        output_tarball = "%s/output.tar" % self.temp_directory

        self.imagediff.generate_diff_tarball(output_tarball)
        tarball = tarfile.open(output_tarball, "r")

        files_list = [entry.name for entry in tarball]
        self.assertEqual(files_list, [
            'removed',
            'c/c',
            'c/a_i',
            'c/d',
            'c/h',
            'c/j',
            'dir',
            'e',
            'f',
            'system/o',
            'system/o.1',
            ])
        removed_list = tarball.extractfile("removed")
        self.assertEqual(removed_list.read().decode("utf-8"), u"""b
c/d
c/h
dir
system/中文中文中文
""")


class TestHardLinkTargetIsModified(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_directory)

    def _make_tarballs(self, order):
        source_tarball_path = os.path.join(self.temp_directory, "source.tar")
        target_tarball_path = os.path.join(self.temp_directory, "target.tar")

        # Use an ExitStack() when we drop Python 2.7 compatibility.
        source_tarball = tarfile.open(
            source_tarball_path, "w", encoding="utf-8")
        target_tarball = tarfile.open(
            target_tarball_path, "w", encoding="utf-8")

        if order == "a->b":
            # Add a regular file to the source.
            a_source = tarfile.TarInfo()
            a_source.name = "a"
            a_source.size = 4
            source_tarball.addfile(a_source, BytesIO(b"XXXX"))

            # Add a hardlink to this file.
            b = tarfile.TarInfo()
            b.name = "b"
            b.type = tarfile.LNKTYPE
            b.linkname = "a"
            source_tarball.addfile(b)

            # Change the content of link's target, i.e. the "a" file in the
            # target tarball, but keep the hardlink pointing at it.
            a_target = tarfile.TarInfo()
            a_target.name = "a"
            a_target.size = 5

            target_tarball.addfile(a_target, BytesIO(b"YYYYY"))
            target_tarball.addfile(b)
        else:
            assert order == "b->a", "Bad order: {}".format(order)
            # Add a regular file to the source.
            a_source = tarfile.TarInfo()
            a_source.name = "a"
            a_source.size = 4
            source_tarball.addfile(a_source, BytesIO(b"XXXX"))

            # Add a hardlink to this file.
            b_source = tarfile.TarInfo()
            b_source.name = "b"
            b_source.type = tarfile.LNKTYPE
            b_source.linkname = "a"
            source_tarball.addfile(b_source)

            # Swap things around in the target such that 'b' is the regular
            # file and 'a' is the hardlink to b.
            b_target = tarfile.TarInfo()
            b_target.name = "b"
            b_target.size = 5
            target_tarball.addfile(b_target, BytesIO(b"YYYYY"))

            a_target = tarfile.TarInfo()
            a_target.name = "a"
            a_target.type = tarfile.LNKTYPE
            a_target.linkname = "b"
            target_tarball.addfile(a_target)

        source_tarball.close()
        target_tarball.close()

        return source_tarball_path, target_tarball_path

    def test_link_count_2_order_ab(self):
        # LP: #1444347 - a file with link count 2 (i.e. two hardlinks to the
        # same inode) doesn't get both sources updated.
        diff = ImageDiff(*self._make_tarballs("a->b"))
        change_set = diff.compare_images()
        self.assertEqual(change_set, {("a", "mod"), ("b", "mod")})

    def test_unpack_ab(self):
        # Ensure that the unpacked target tarball has a correct hardlink.
        source_path, target_path = self._make_tarballs("a->b")
        diff = ImageDiff(source_path, target_path)
        diff_path = os.path.join(self.temp_directory, "diff.tar")
        diff.generate_diff_tarball(diff_path)
        # Unpack the source, then unpack the target over that.
        unpack_path = os.path.join(self.temp_directory, "unpack")
        os.mkdir(unpack_path)
        with tarfile.open(source_path, "r:", encoding="utf-8") as tf:
            tf.extractall(unpack_path)
        # Before applying the diff, "b" contains the old "a" file's contents.
        with open(os.path.join(unpack_path, "b"), "rb") as fp:
            contents = fp.read()
        self.assertEqual(contents, b"XXXX")
        # Unpack the diff, which changes both the contents of 'a' and the
        # hardlink 'b'.
        with tarfile.open(diff_path, "r:", encoding="utf-8") as tf:
            # Process any file removals first.
            removed_list = tf.extractfile("removed")
            for line in removed_list:
                os.unlink(os.path.join(unpack_path,
                                       line.decode("utf-8").rstrip()))
            tf.extractall(unpack_path)
        with open(os.path.join(unpack_path, "b"), "rb") as fp:
            contents = fp.read()
        self.assertEqual(contents, b"YYYYY")

    def test_link_count_2_swap_roles(self):
        # Like above but the source has regular file 'a' with hardlink 'b'
        # pointing to it, while the target has regular file 'b' with the
        # hardlink 'a' pointing to it.  Both must be properly updated.
        diff = ImageDiff(*self._make_tarballs("b->a"))
        change_set = diff.compare_images()
        self.assertEqual(change_set, {("a", "mod"), ("b", "mod")})

    def test_unpack_ab_swap_roles(self):
        # Ensure that the unpacked target tarball has a correct hardlink.
        source_path, target_path = self._make_tarballs("b->a")
        diff = ImageDiff(source_path, target_path)
        diff_path = os.path.join(self.temp_directory, "diff.tar")
        diff.generate_diff_tarball(diff_path)
        # Unpack the source, then unpack the target over that.
        unpack_path = os.path.join(self.temp_directory, "unpack")
        os.mkdir(unpack_path)
        with tarfile.open(source_path, "r:", encoding="utf-8") as tf:
            tf.extractall(unpack_path)
        # Before applying the diff, "b" contains the old "a" file's contents.
        with open(os.path.join(unpack_path, "b"), "rb") as fp:
            contents = fp.read()
        self.assertEqual(contents, b"XXXX")
        # Unpack the diff, which changes both the contents of 'a' and the
        # hardlink 'b'.
        with tarfile.open(diff_path, "r:", encoding="utf-8") as tf:
            # Process any file removals first.
            removed_list = tf.extractfile("removed")
            for line in removed_list:
                os.unlink(os.path.join(unpack_path,
                                       line.decode("utf-8").rstrip()))
            tf.extractall(unpack_path)
        with open(os.path.join(unpack_path, "b"), "rb") as fp:
            contents = fp.read()
        self.assertEqual(contents, b"YYYYY")
