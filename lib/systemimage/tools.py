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

from io import BytesIO
import gzip
import os
import re
import subprocess
import tarfile
import time


def expand_path(path, base="/"):
    """
        Takes a path and returns a tuple containing the absolute path
        and a relative path (relative to base).
    """

    if path.startswith(base):
        path = re.sub('^%s' % re.escape(base), "", path)

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


def generate_version_tarball(config, channel, version, path,
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

    tarball.addfile(version_file, BytesIO(version.encode('utf-8')))

    channel = """[service]
base: %s
http_port: %s
https_port: %s
channel: %s
build_number: %s
""" % (config.public_fqdn, config.public_http_port, config.public_https_port,
       channel, version.strip())

    if channel_target:
        channel += "channel_target: %s\n" % channel_target

    if version_detail:
        channel += "version_detail: %s\n" % version_detail

    channel_file = tarfile.TarInfo()
    channel_file.size = len(channel)
    channel_file.mtime = int(time.strftime("%s", time.localtime()))
    channel_file.name = channel_path

    tarball.addfile(channel_file, BytesIO(channel.encode('utf-8')))

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
        raise Exception("destination already exists.")

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
        raise Exception("unspecified destination and path doesn't end"
                        " with .gz")

    if not destination:
        destination = path[:-3]

    if os.path.exists(destination):
        raise Exception("destination already exists.")

    compressed = gzip.open(path, "rb")
    uncompressed = open(destination, "wb+")
    uncompressed.writelines(compressed)
    uncompressed.close()
    compressed.close()

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
        raise Exception("destination already exists.")

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
        raise Exception("unspecified destination and path doesn't end"
                        " with .xz")

    if not destination:
        destination = path[:-3]

    if os.path.exists(destination):
        raise Exception("destination already exists.")

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
