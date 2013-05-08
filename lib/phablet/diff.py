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


def list_directory(path):
    """
        Walk through a directory and generate a list of the content.

        Returns a tuple containing a set and a dict.
        The set is typically used for simple diffs between directories.
        The dict is used to easily grab the details of a specific entry.
    """

    set_content = set()
    dict_content = {}

    for dirName, subdirList, fileList in os.walk(path):
        dpath = dirName.replace(path, "")

        set_content.add((dpath, 'dir', None))
        dict_content[dpath] = ('dir', None)
        for fname in fileList:
            fpath = "%s/%s" % (dpath, fname)
            fhash = None

            if os.path.exists("%s/%s" % (dirName, fname)):
                fstat = os.stat("%s/%s" % (dirName, fname))
                fhash = ("%s" % fstat.st_mode,
                         "%s" % fstat.st_uid,
                         "%s" % fstat.st_gid,
                         "%s" % fstat.st_size,
                         "%s" % fstat.st_ctime,
                         "%s" % fstat.st_mtime)

            set_content.add((fpath, 'file', fhash))
            dict_content[fpath] = ('file', fhash)

    return (set_content, dict_content)


class ImageDiff:
    source_content = None
    target_content = None
    diff = None

    def __init__(self, source, target):
        if not os.path.isdir(source):
            raise TypeError("source isn't a valid directory.")

        if not os.path.isdir(target):
            raise TypeError("destination isn't a valid directory.")

        self.source_path = source
        self.target_path = target

    def scan_content(self, image):
        """
            Scan the content of an image and return the image tuple.
            This also caches the content for further use.
        """

        if image not in ("source", "target"):
            raise KeyError("Invalid image '%s'." % image)

        image_path = getattr(self, "%s_path" % image)

        content = list_directory(image_path)

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

        # Ignore files that only vary in ctime/mtime
        # (separate loop to run after de-dupe)
        for change in sorted(changes):
            if change[1] == "mod":
                fstat_source = self.source_content[1][change[0]][1]
                fstat_target = self.target_content[1][change[0]][1]
                if (fstat_source[0:4] == fstat_target[0:4] and
                        compare_files("%s/%s" % (self.source_path,
                                                 change[0]),
                                      "%s/%s" % (self.target_path,
                                                 change[0]))):
                    changes.remove(change)

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

    def generate_diff_squashfs(self, path):
        """
            Generate a squashfs image containing all files that are
            different between the source and target iamge.
        """

        if not self.diff:
            self.compare_images()

        output = tempfile.mkdtemp()

        # Copy all the added and modified
        for change in sorted(self.diff):
            if change[1] == "del":
                continue

            ftarget = "%s/%s" % (self.target_path, change[0])
            fdestination = "%s/%s" % (output, change[0])

            fparent = "/".join(change[0].split("/")[0:-1])
            if not os.path.exists("%s/%s" % (output, fparent)):
                os.makedirs("%s/%s" % (output, fparent))

            if subprocess.call(["cp", "-aR", ftarget, fdestination]) != 0:
                sys.stderr.write("Failed to copy: %s\n" % ftarget)

        # Generate a squashfs
        if subprocess.call(["mksquashfs", output, path, "-comp", "xz"]) != 0:
            sys.stderr.write("Failed to generate the squashfs: %s\n" % path)

        shutil.rmtree(output)
