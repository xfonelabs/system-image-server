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

import gzip
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

from io import BytesIO
from systemimage.helpers import chdir


logger = logging.getLogger(__name__)


def expand_path(path, base="/"):
    """
        Takes a path and returns a tuple containing the absolute path
        and a relative path (relative to base).
    """

    if path.startswith(base):
        path = re.sub("^%s" % re.escape(base), "", path)

    if path.startswith(os.sep):
        relpath = path[1:]
    else:
        relpath = path

    abspath = os.path.realpath(os.path.join(base, relpath))

    return abspath, relpath


# Imported from cdimage.osextras
def find_on_path(command):
    """Is command on the executable search path?"""

    if 'PATH' not in os.environ:
        return False
    path = os.environ['PATH']
    for element in path.split(os.pathsep):
        if not element:
            continue
        filename = os.path.join(element, command)
        if os.path.isfile(filename) and os.access(filename, os.X_OK):
            return True
    return False


def generate_version_tarball(config, channel, device, version, path,
                             build_path="system/etc/ubuntu-build",
                             channel_path="system/etc/system-image/"
                                          "channel.ini",
                             version_detail=None,
                             channel_target=None):
    """
        Generates a tarball which contains two files
        (build_path and channel_path).
        The first contains the build id, the second a .ini config file.
        The resulting tarball is written at the provided location (path).
    """

    tarball = tarfile.open(path, 'w:')

    version_file = tarfile.TarInfo()
    version_file.size = len(version) + 1
    version_file.mtime = int(time.strftime("%s", time.localtime()))
    version_file.name = build_path

    # Append a line break
    version += "\n"

    tarball.addfile(version_file, BytesIO(version.encode("utf-8")))

    http_port = config.public_http_port
    https_port = config.public_https_port

    if http_port == 0:
        http_port = "disabled"

    if https_port == 0:
        https_port = "disabled"

    channel = """[service]
base: %s
http_port: %s
https_port: %s
channel: %s
device: %s
build_number: %s
""" % (config.public_fqdn, http_port, https_port,
       channel, device, version.strip())

    if channel_target:
        channel += "channel_target: %s\n" % channel_target

    if version_detail:
        channel += "version_detail: %s\n" % version_detail

    channel_file = tarfile.TarInfo()
    channel_file.size = len(channel)
    channel_file.mtime = int(time.strftime("%s", time.localtime()))
    channel_file.name = channel_path

    tarball.addfile(channel_file, BytesIO(channel.encode("utf-8")))

    # With system-image 3.0, we need a couple of additional files.  For now we
    # can just use symlink, but once support for system-image < 3.0 is
    # removed, these symlinks should become real files and the channel_file
    # should be removed.
    #
    # We use relative paths in the links so that we don't have to worry
    # about the recovery "system/" prefix.
    #
    # The directory needs to be created with drwxrwxr-x permissions.
    config_d = os.path.join(os.path.dirname(channel_path), "config.d")
    directory = tarfile.TarInfo(config_d)
    directory.type = tarfile.DIRTYPE
    directory.mode = 0o775
    tarball.addfile(directory)

    path_00_default = os.path.join(config_d, "00_default.ini")
    default_file = tarfile.TarInfo()
    default_file.name = path_00_default
    default_file.type = tarfile.SYMTYPE
    default_file.linkname = "../client.ini"
    tarball.addfile(default_file)

    path_01_channel = os.path.join(config_d, "01_channel.ini")
    channel_file = tarfile.TarInfo()
    channel_file.name = path_01_channel
    channel_file.type = tarfile.SYMTYPE
    channel_file.linkname = os.path.join(
        "..", os.path.basename(channel_path))
    tarball.addfile(channel_file)

    tarball.close()


def gzip_compress(path, destination=None, level=9):
    """
        Compress a file (path) using gzip.
        By default, creates a .gz version of the file in the same directory.
        An alternate destination path may be provided.
        The compress level is 9 by default but can be overriden.
    """

    if not destination:
        destination = "%s.gz" % path

    if os.path.exists(destination):
        raise Exception("Destination already exists: %s" % destination)

    logger.debug("Gzipping file: %s" % destination)

    uncompressed = open(path, "rb")
    compressed = gzip.open(destination, "wb+", level)
    compressed.writelines(uncompressed)
    compressed.close()
    uncompressed.close()

    return destination


def gzip_uncompress(path, destination=None):
    """
        Uncompress a file (path) using gzip.
        By default, uses the source path without the .gz prefix as the target.
        An alternate destination path may be provided.
    """

    if not destination and path[-3:] != ".gz":
        raise Exception("Unspecified destination and path doesn't end"
                        " with .gz")

    if not destination:
        destination = path[:-3]

    if os.path.exists(destination):
        raise Exception("Destination already exists: %s" % destination)

    logger.debug("Ungzipping {} to: {}".format(path, destination))

    with gzip.open(path, "rb") as compressed:
        with open(destination, "wb+") as uncompressed:
            uncompressed.writelines(compressed)

    return destination


def xz_compress(path, destination=None, level=9):
    """
        Compress a file (path) using xz.
        By default, creates a .xz version of the file in the same directory.
        An alternate destination path may be provided.
        The compress level is 9 by default but can be overriden.
    """

    # NOTE: Once we can drop support for < 3.3, the new lzma module can be used

    if not destination:
        destination = "%s.xz" % path

    if os.path.exists(destination):
        raise Exception("Destination already exists: %s" % destination)

    logger.debug("Xzipping file: %s" % destination)

    if find_on_path("pxz"):
        xz_command = "pxz"
    else:
        xz_command = "xz"

    with open(destination, "wb+") as fd:
        retval = subprocess.call([xz_command, '-z', '-%s' % level, '-c', path],
                                 stdout=fd)
    return retval


def xz_uncompress(path, destination=None):
    """
        Uncompress a file (path) using xz.
        By default, uses the source path without the .xz prefix as the target.
        An alternate destination path may be provided.
    """

    # NOTE: Once we can drop support for < 3.3, the new lzma module can be used

    if not destination and path[-3:] != ".xz":
        raise Exception("Unspecified destination and path doesn't end"
                        " with .xz")

    if not destination:
        destination = path[:-3]

    if os.path.exists(destination):
        raise Exception("Destination already exists: %s" % destination)

    logger.debug("Unxzipping file: %s" % destination)

    with open(destination, "wb+") as fd:
        retval = subprocess.call(['xz', '-d', '-c', path],
                                 stdout=fd)

    return retval


def trigger_mirror(host, port, username, key, command):
    return subprocess.call(['ssh',
                            '-i', key,
                            '-l', username,
                            '-p', str(port),
                            host,
                            command])


def sync_mirrors(config):
    for mirror in sorted(config.mirrors.values(),
                         key=lambda mirror: mirror.ssh_host):
        trigger_mirror(mirror.ssh_host, mirror.ssh_port, mirror.ssh_user,
                       mirror.ssh_key, mirror.ssh_command)


def repack_recovery_keyring(conf, path, keyring_name):
    tempdir = tempfile.mkdtemp()

    xz_uncompress(path, os.path.join(tempdir, "input.tar"))

    input_tarball = tarfile.open(os.path.join(tempdir, "input.tar"), "r:")

    # Make sure the partition is in there
    if "partitions/recovery.img" not in input_tarball.getnames():
        shutil.rmtree(tempdir)
        return False

    input_tarball.extract("partitions/recovery.img", tempdir)

    # Extract the content of the .img
    os.mkdir(os.path.join(tempdir, "img"))
    with chdir(os.path.join(tempdir, "img")):
        cmd = ["abootimg",
               "-x", os.path.join(tempdir, "partitions", "recovery.img")]

        with open(os.path.devnull, "w") as devnull:
            subprocess.call(cmd, stdout=devnull, stderr=devnull)

    # Extract the content of the initrd
    os.mkdir(os.path.join(tempdir, "initrd"))
    state_path = os.path.join(tempdir, "fakeroot_state")

    with chdir(os.path.join(tempdir, "initrd")):
        gzip_uncompress(os.path.join(tempdir, "img", "initrd.img"),
                        os.path.join(tempdir, "img", "initrd"))

        with open(os.path.join(tempdir, "img", "initrd"), "rb") as fd:
            with open(os.path.devnull, "w") as devnull:
                subprocess.call(["fakeroot", "-s", state_path, "cpio", "-i"],
                                stdin=fd, stdout=devnull, stderr=devnull)

    # Swap the files
    keyring_path = os.path.join(conf.gpg_keyring_path, keyring_name)

    shutil.copy("%s.tar.xz" % keyring_path,
                os.path.join(tempdir, "initrd", "etc", "system-image",
                             "%s.tar.xz" % keyring_name))

    shutil.copy("%s.tar.xz.asc" % keyring_path,
                os.path.join(tempdir, "initrd", "etc", "system-image",
                             "%s.tar.xz.asc" % keyring_name))

    # Re-generate the initrd
    with chdir(os.path.join(tempdir, "initrd")):
        find = subprocess.Popen(["find", "."], stdout=subprocess.PIPE)
        with open(os.path.join(tempdir, "img", "initrd"), "w+") as fd:
            with open(os.path.devnull, "w") as devnull:
                subprocess.call(["fakeroot", "-i", state_path, "cpio",
                                 "-o", "--format=newc"],
                                stdin=find.stdout,
                                stdout=fd,
                                stderr=devnull)

    os.rename(os.path.join(tempdir, "img", "initrd.img"),
              os.path.join(tempdir, "img", "initrd.img.bak"))
    gzip_compress(os.path.join(tempdir, "img", "initrd"),
                  os.path.join(tempdir, "img", "initrd.img"))

    # Rewrite bootimg.cfg
    content = ""
    with open(os.path.join(tempdir, "img", "bootimg.cfg"), "r") as source:
        for line in source:
            if line.startswith("bootsize"):
                line = "bootsize=0x900000\n"
            content += line

    with open(os.path.join(tempdir, "img", "bootimg.cfg"), "w+") as dest:
        dest.write(content)

    # Update the partition image
    with open(os.path.devnull, "w") as devnull:
        subprocess.call(['abootimg', '-u',
                         os.path.join(tempdir, "partitions", "recovery.img"),
                         "-f", os.path.join(tempdir, "img", "bootimg.cfg")],
                        stdout=devnull, stderr=devnull)

    # Update the partition image
    with open(os.path.devnull, "w") as devnull:
        subprocess.call(['abootimg', '-u',
                         os.path.join(tempdir, "partitions", "recovery.img"),
                         "-r", os.path.join(tempdir, "img", "initrd.img")],
                        stdout=devnull, stderr=devnull)

    # Generate a new tarball
    output_tarball = tarfile.open(os.path.join(tempdir, "output.tar"), "w:")
    for entry in input_tarball:
        fileptr = None
        if entry.isfile():
            try:
                if entry.name == "partitions/recovery.img":
                    with open(os.path.join(tempdir, "partitions",
                                           "recovery.img"), "rb") as fd:
                        fileptr = BytesIO(fd.read())
                        entry.size = os.stat(
                            os.path.join(tempdir, "partitions",
                                         "recovery.img")).st_size
                else:
                    fileptr = input_tarball.extractfile(entry.name)
            except KeyError:  # pragma: no cover
                pass

        output_tarball.addfile(entry, fileobj=fileptr)
        if fileptr:
            fileptr.close()
            fileptr = None

    output_tarball.close()
    input_tarball.close()

    os.remove(path)
    xz_compress(os.path.join(tempdir, "output.tar"), path)

    shutil.rmtree(tempdir)

    return True
