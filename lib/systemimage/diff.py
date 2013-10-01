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
import tarfile
import time

from io import BytesIO


def compare_files(fd_source, fd_target):
    """
        Compare two files.

        Returns True if their content matches.
        Returns False if they don't match.
        Returns None if the files can't be compared.
    """

    if fd_source == fd_target:
        return True

    if not fd_source or not fd_target:
        return False

    return fd_source.read() == fd_target.read()


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
                     "%s" % entry.type.decode('utf-8'),
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
        self.source_file = tarfile.open(source, 'r:')
        self.target_file = tarfile.open(target, 'r:')

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

        # Ignore files that only vary in mtime
        # (separate loop to run after de-dupe)
        for change in sorted(changes):
            if change[1] == "mod":
                fstat_source = self.source_content[1][change[0]][1]
                fstat_target = self.target_content[1][change[0]][1]

                # Skip differences between directories and files
                if not fstat_source or not fstat_target:  # pragma: no cover
                    continue

                # Deal with switched hardlinks
                if (fstat_source[0:2] == fstat_target[0:2] and
                        fstat_source[3] != fstat_target[3] and
                        (fstat_source[3] == "1" or fstat_target[3] == "1") and
                        fstat_source[4:5] == fstat_target[4:5] and
                        fstat_source[7] == fstat_target[7]):
                    source_file = self.source_file.getmember(change[0])
                    target_file = self.target_file.getmember(change[0])
                    if compare_files(
                            self.source_file.extractfile(change[0]),
                            self.target_file.extractfile(change[0])):
                        changes.remove(change)
                        continue

                # Deal with regular files
                if fstat_source[0:7] == fstat_target[0:7]:
                    source_file = self.source_file.getmember(change[0])
                    target_file = self.target_file.getmember(change[0])

                    if (source_file.linkpath
                            and source_file.linkpath == target_file.linkpath):
                        changes.remove(change)
                        continue

                    if (source_file.isfile() and target_file.isfile()
                            and compare_files(
                                self.source_file.extractfile(change[0]),
                                self.target_file.extractfile(change[0]))):
                        changes.remove(change)
                        continue

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

    def generate_diff_tarball(self, path):
        """
            Generate a tarball containing all files that are
            different between the source and target iamge as well
            as a file listing all removals.
        """

        if not self.diff:
            self.compare_images()

        output = tarfile.open(path, 'w:')

        # List both deleted files and modified files in the removal list
        # that's needed to allow file type change (e.g. directory to symlink)
        removed_files_list = [entry[0] for entry in self.diff
                              if entry[1] in ("del", "mod")]

        removed_files = "\n".join(removed_files_list)
        removed_files = "%s\n" % removed_files.encode('utf-8')

        removals = tarfile.TarInfo()
        removals.name = "removed"
        removals.size = len(removed_files)
        removals.mtime = int(time.strftime("%s", time.localtime()))
        removals.uname = "root"
        removals.gname = "root"

        output.addfile(removals, BytesIO(removed_files.encode('utf-8')))

        # Copy all the added and modified
        added = []
        for name, action in sorted(self.diff):
            if action == 'del':
                continue

            if name in added:
                continue

            newfile = self.target_file.getmember(name)
            if newfile.islnk():
                targetfile_path = os.path.normpath(os.path.join(
                    os.path.dirname(newfile.name), newfile.linkname))

                targetfile = self.target_file.getmember(targetfile_path)

                if ((targetfile_path, 'add') in self.diff or
                        (targetfile_path, 'mod') in self.diff) and \
                        targetfile_path not in added:
                    fileptr = self.target_file.extractfile(targetfile)
                    output.addfile(targetfile, fileptr)
                    added.append(targetfile.name)

            fileptr = None
            if newfile.isfile():
                fileptr = self.target_file.extractfile(name)
            output.addfile(newfile, fileobj=fileptr)
            added.append(newfile.name)

        output.close()
