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
import sys
import tarfile
import time
from collections import namedtuple
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


# For the data portion of the set and dict contents.
FHash = namedtuple('FHash', 'mode devmajor devminor type uid gid size mtime')
# The set contents record.
SContent = namedtuple('SContent', 'path filetype data')
# The dict contents record.
DContent = namedtuple('DContent', 'filetype data')


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
            set_content.add(SContent(entry.path, "dir", None))
            dict_content[entry.path] = DContent("dir", None)
        else:
            fhash = FHash(
                "%s" % entry.mode,
                "%s" % entry.devmajor,
                "%s" % entry.devminor,
                "%s" % entry.type.decode("utf-8"),
                "%s" % entry.uid,
                "%s" % entry.gid,
                "%s" % entry.size,
                "%s" % entry.mtime)

            set_content.add(SContent(entry.path, "file", fhash))
            dict_content[entry.path] = DContent("file", fhash)

    return set_content, dict_content


class ImageDiff:
    source_content = None
    target_content = None
    diff = None

    def __init__(self, source, target):
        self.source_file = tarfile.open(source, 'r:', encoding='utf-8')
        self.target_file = tarfile.open(target, 'r:', encoding='utf-8')

    def scan_content(self, image):
        """
            Scan the content of an image and return the image tuple.
            This also caches the content for further use.
        """
        image_file = getattr(self, image + "_file", None)
        if image_file is None:
            raise KeyError("Invalid image '%s'." % image)

        content = list_tarfile(image_file)
        setattr(self, image + "_content", content)
        return content

    def compare_images(self):
        """
            Compare the file listing of two images and return a set.
            This also caches the diff for further use.

            The set contains tuples of (path, changetype).
        """
        if self.source_content is None:
            self.scan_content("source")

        if self.target_content is None:
            self.scan_content("target")

        source_set, source_dict = self.source_content
        target_set, target_dict = self.target_content

        # Find the changes in the two trees
        changes = set()
        for change in source_set.symmetric_difference(target_set):
            if change.path not in source_dict:
                change_type = "add"
            elif change.path not in target_dict:
                change_type = "del"
            else:
                change_type = "mod"
            changes.add((change.path, change_type))

        # Do a second pass through the source and target sets, looking for any
        # hardlinks that point to a file that's being modified in the target.
        # These links must get also get modified or they'll end up pointing to
        # the old inode.
        for no_change in source_set.intersection(target_set):
            if no_change.filetype == "file" and no_change.data.type == "1":
                # This is a hardlink which exists in both the source and
                # target, *and* points to the same link target (by virtue of
                # the set intersection).
                changes.add((no_change.path, "mod"))

        # Ignore files that only vary in mtime
        # (separate loop to run after de-dupe)
        for change in sorted(changes):
            change_path, change_type = change
            if change_type == "mod":
                fstat_source = source_dict[change_path].data
                fstat_target = target_dict[change_path].data

                # Skip differences between directories and files
                if not fstat_source or not fstat_target:  # pragma: no cover
                    continue

                # Deal with switched hardlinks.
                #
                # stgraber says on 2015-05-27: this was trying to solve the
                # case where the hardlink target would be placed *after* the
                # hardlink in the tar archive, leading to a hardlink being
                # created to the wrong file at unpack.  barry thinks: ???
                if (
                        fstat_source.mode == fstat_target.mode
                        and fstat_source.devmajor == fstat_target.devmajor
                        and fstat_source.devminor == fstat_target.devminor
                        # "1" is the LNKTYPE, i.e. hard link.
                        and (fstat_source.type == "1" or
                             fstat_target.type == "1")
                        and fstat_source.uid == fstat_target.uid
                        and fstat_source.gid == fstat_target.gid
                        # size is ignored since it is always 0 for hardlinks.
                        and fstat_source.mtime == fstat_target.mtime):
                    source_file = self.source_file.getmember(change_path)
                    target_file = self.target_file.getmember(change_path)
                    if compare_files(
                            self.source_file.extractfile(change_path),
                            self.target_file.extractfile(change_path)):
                        changes.remove(change)
                        continue

                # Deal with regular files.  Compare all attributes of the file
                # except the mtime.
                if fstat_source[0:7] == fstat_target[0:7]:
                    source_file = self.source_file.getmember(change_path)
                    target_file = self.target_file.getmember(change_path)
                    # Symlinks that point to the same file in both the source
                    # and target can be ignored, however *hardlinks* cannot,
                    # since the inode they point to may change out from
                    # underneath them.
                    if (
                            source_file.type == "2"
                            and target_file.type == "2"
                            and source_file.linkpath == target_file.linkpath):
                        changes.remove(change)
                        continue

                    if (source_file.isfile() and target_file.isfile()
                            and compare_files(
                                self.source_file.extractfile(change_path),
                                self.target_file.extractfile(change_path))):
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

        output = tarfile.open(path, 'w:', format=tarfile.GNU_FORMAT)

        # List both deleted files and modified files in the removal list
        # that's needed to allow file type change (e.g. directory to symlink)
        removed_files_list = sorted([entry[0] for entry in self.diff
                                     if entry[1] in ("del", "mod")])

        removed_files = "%s\n" % "\n".join(removed_files_list)

        if sys.version_info.major > 2:  # pragma: no cover
            removed_files = removed_files.encode("utf-8")

        removals = tarfile.TarInfo()
        removals.name = "removed"
        removals.size = len(removed_files)
        removals.mtime = int(time.strftime("%s", time.localtime()))
        removals.uname = "root"
        removals.gname = "root"

        output.addfile(removals, BytesIO(removed_files))

        # Copy all the added and modified
        added = []
        for name, action in sorted(self.diff):
            if action == 'del':
                continue

            if name in added:
                continue

            newfile = self.target_file.getmember(name)
            if newfile.islnk():
                if newfile.linkname.startswith("system/"):
                    targetfile_path = newfile.linkname
                else:
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
