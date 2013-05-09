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

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile


def compare_files(source, target):
    """
        Compare two files.

        Returns True if their content matches.
        Returns False if they don't match.
        Returns None if the files can't be compared.
    """

    if os.path.islink(source) or os.path.islink(target):
        return os.readlink(source) == os.readlink(target)

    if not os.path.isfile(source) or not os.path.isfile(target):
        return None

    hash_source = None
    hash_target = None

    try:
        with open(source, "rb") as fd_source:
            hash_source = hashlib.sha1(fd_source.read()).hexdigest()
    except:
        sys.stderr.write("Unable to hash: %s\n" % source)

    try:
        with open(target, "rb") as fd_target:
            hash_target = hashlib.sha1(fd_target.read()).hexdigest()
    except:
        sys.stderr.write("Unable to hash: %s\n" % target)

    return hash_source == hash_target


def list_tarfile(tarfile):
    """
        Walk through a tarfile and generate a list of the content.

        Returns a tuple containing a set and a dict.
        The set is typically used for simple diffs between tarballs.
        The dict is used to easily grab the details of a specific entry.
    """

    set_content = set()
    dict_content = {}

    for entry in tarfile:
        if entry.isdir():
            set_content.add((entry.path, 'dir', None))
            dict_content[entry.path] = ('dir', None)
        else:
            fhash = ("%s" % entry.mode,
                     "%s" % entry.devmajor,
                     "%s" % entry.devminor,
                     "%s" % entry.type,
                     "%s" % entry.uid,
                     "%s" % entry.gid,
                     "%s" % entry.size,
                     "%s" % entry.mtime)

            set_content.add((entry.path, 'file', fhash))
            dict_content[entry.path] = ('file', fhash)

    return (set_content, dict_content)


class ImageDiff:
    source_content = None
    target_content = None
    diff = None

    def __init__(self, source, target):
        self.source_file = tarfile.open(source)
        self.target_file = tarfile.open(target)

    def scan_content(self, image):
        """
            Scan the content of an image and return the image tuple.
            This also caches the content for further use.
        """

        if image not in ("source", "target"):
            raise KeyError("Invalid image '%s'." % image)

        image_file = getattr(self, "%s_file" % image)

        content = list_tarfile(image_file)

        setattr(self, "%s_content" % image, content)
        return content

    def compare_images(self):
        """
            Compare the file listing of two images and return a set.
            This also caches the diff for further use.

            The set contains tuples of (path, changetype).
        """
        if not self.source_content:
            self.scan_content("source")

        if not self.target_content:
            self.scan_content("target")

        # Find the changes in the two trees
        changes = set()
        for change in self.source_content[0] \
                .symmetric_difference(self.target_content[0]):
            if change[0] not in self.source_content[1]:
                changetype = "add"
            elif change[0] not in self.target_content[1]:
                changetype = "del"
            else:
                changetype = "mod"
            changes.add((change[0], changetype))

        # Unpack both tarballs to allow for quick checksuming
        unpack_source = tempfile.mkdtemp()
        unpack_target = tempfile.mkdtemp()
        with open("/dev/null", "a") as devnull:
            subprocess.call(["tar", "Jxf", self.source_file.name, "-C",
                             unpack_source],
                            stdout=devnull,
                            stderr=devnull)
        with open("/dev/null", "a") as devnull:
            subprocess.call(["tar", "Jxf", self.target_file.name, "-C",
                             unpack_target],
                            stdout=devnull,
                            stderr=devnull)

        # Ignore files that only vary in mtime
        # (separate loop to run after de-dupe)
        for change in sorted(changes):
            if change[1] == "mod":
                fstat_source = self.source_content[1][change[0]][1]
                fstat_target = self.target_content[1][change[0]][1]
                if fstat_source[0:7] == fstat_target[0:7]:
                    source_file = self.source_file.getmember(change[0])
                    target_file = self.target_file.getmember(change[0])

                    if (source_file.linkpath
                            and source_file.linkpath == target_file.linkpath):
                        changes.remove(change)
                        continue

                    if (source_file.isfile() and target_file.isfile()
                            and compare_files("%s/%s" %
                                              (unpack_source, change[0]),
                                              "%s/%s" %
                                              (unpack_target, change[0]))):
                        changes.remove(change)
                        continue

        # Cleanup
        shutil.rmtree(unpack_source)
        shutil.rmtree(unpack_target)

        self.diff = changes
        return changes

    def print_changes(self):
        """
            Simply print the list of changes.
        """

        if not self.diff:
            self.compare_images()

        for change in sorted(self.diff):
            print(" - %s (%s)" % (change[0], change[1]))

    def generate_removal_list(self, path):
        """
            Generate a file containing the list of removed files.
        """

        if not self.diff:
            self.compare_images()

        with open(path, "w+") as fd:
            for change in sorted(self.diff):
                if change[1] != "del":
                    continue

                fd.write("%s\n" % change[0])

    def generate_diff_tarball(self, path):
        """
            Generate a tarball containing all files that are
            different between the source and target iamge as well
            as a file listing all removals.
        """

        if not self.diff:
            self.compare_images()

        output = tarfile.open(path, "w")

        # Add removal list
        removal_list = tempfile.mktemp()
        self.generate_removal_list(removal_list)
        output.add(removal_list, arcname="removed")

        # Copy all the added and modified
        for change in sorted(self.diff):
            if change[1] == "del":
                continue

            newfile = self.target_file.getmember(change[0])
            print("adding: %s" % newfile)
            if newfile.isfile():
                output.addfile(newfile,
                               fileobj=self.target_file.extract(change[0]))
            else:
                output.addfile(newfile)

        output.close()

        # Cleanup
        os.remove(removal_list)
