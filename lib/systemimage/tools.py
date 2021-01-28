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
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from io import BytesIO
from operator import itemgetter

from systemimage import gpg
from systemimage.helpers import chdir

READ_SIZE = 1024 * 1024

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
    now_mtime = int(time.time())

    version_file = tarfile.TarInfo()
    version_file.size = len(version) + 1
    version_file.mtime = now_mtime
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
    channel_file.mtime = now_mtime
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
    directory.mtime = now_mtime
    tarball.addfile(directory)

    path_00_default = os.path.join(config_d, "00_default.ini")
    default_file = tarfile.TarInfo()
    default_file.name = path_00_default
    default_file.type = tarfile.SYMTYPE
    default_file.linkname = "../client.ini"
    default_file.mtime = now_mtime
    tarball.addfile(default_file)

    path_01_channel = os.path.join(config_d, "01_channel.ini")
    channel_file = tarfile.TarInfo()
    channel_file.name = path_01_channel
    channel_file.type = tarfile.SYMTYPE
    channel_file.linkname = os.path.join(
        "..", os.path.basename(channel_path))
    channel_file.mtime = now_mtime
    tarball.addfile(channel_file)

    tarball.close()


def generate_version_metadata(config, version, channel, device, path,
                              version_detail=""):
    """
        Helper function that will take selected version info and create
        the .json version file for the corresponding version tarball.
    """

    metadata = {}
    metadata['generator'] = "version"
    metadata['version'] = version
    metadata['version_detail'] = "version=%s" % version
    metadata['channel.ini'] = {}
    metadata['channel.ini']['channel'] = channel
    metadata['channel.ini']['device'] = device
    metadata['channel.ini']['version'] = str(version)
    metadata['channel.ini']['version_detail'] = version_detail

    with open(path.replace(".tar.xz", ".json"), "w+") as fd:
        fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                     indent=4, separators=(",", ": ")))
    gpg.sign_file(config, "image-signing", path.replace(".tar.xz", ".json"))


def guess_file_compression(path):
    """
        Try to guess through the magic signature in the first bytes of the
        file.
    """

    compressions = {
        b"\x1f\x8b\x08": "gzip",
        b"\xfd\x37\x7a\x58\x5a\x00": "xz"
        }
    length = max(len(x) for x in compressions)

    with open(path, 'rb') as f:
        start = f.read(length)
    for magic, compression in compressions.items():
        if start.startswith(magic):
            return compression

    return None


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
        The compress level is 9 by default but can be overridden.
    """

    if not destination:
        destination = "%s.xz" % path

    if os.path.exists(destination):
        raise Exception("Destination already exists: %s" % destination)

    logger.debug("Xzipping file: %s" % destination)

    with open(destination, "wb+") as fd:
        retval = subprocess.call([
            'xz', '--memlimit=70%', '--threads=0', '-z', '-%s' % level,
            '-c', path
            ],
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
        retval = subprocess.call([
            'xz', '--memlimit=70%', '--threads=0', '-d', '-c', path
            ],
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


def strip_recovery_header(source_path, dest_path):
    """
        Strip the first 512 bytes of the custom header from the source_path
        file (initrd). Writes the stripped file to dest_path and returns the
        header contents.
    """

    with open(source_path, "rb") as source:
        header_contents = source.read(512)
        with open(dest_path, "wb") as dest:
            data = source.read(READ_SIZE)
            while data:
                dest.write(data)
                data = source.read(READ_SIZE)
    return header_contents


def reattach_recovery_header(source_path, dest_path, header_contents):
    """
        Reattach the stripped header (in header_contents) in front of the
        source_path file contents. This writes the end file to dest_path.
    """

    with open(dest_path, "wb") as dest:
        dest.write(header_contents)
        with open(source_path, "rb") as source:
            data = source.read(READ_SIZE)
            while data:
                dest.write(data)
                data = source.read(READ_SIZE)


def repack_recovery_keyring(conf, path, keyring_name, device_name=None):
    tempdir = tempfile.mkdtemp()

    # In case of certain devices, special care of the recovery is needed
    additional_header = False
    if device_name in ("krillin", "vegetahd", "arale"):
        logging.debug("Expecting additional header in recovery image.")
        additional_header = True

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
        initrdimg_path = os.path.join(tempdir, "img", "initrd.img")
        initrd_path = os.path.join(tempdir, "img", "initrd")

        if additional_header:
            # Remove the 512 header bytes before unpacking
            tmp_path = os.path.join(tempdir, "img", "initrd.img.tmp")
            header_contents = strip_recovery_header(initrdimg_path, tmp_path)
            os.rename(tmp_path, initrdimg_path)

        # The initrd can be either compressed or uncompressed
        compression = guess_file_compression(initrdimg_path)
        if compression == "gzip":
            gzip_uncompress(initrdimg_path, initrd_path)
        elif compression == "xz":
            xz_uncompress(initrdimg_path, initrd_path)
        else:
            shutil.copyfile(initrdimg_path, initrd_path)

        with open(initrd_path, "rb") as fd:
            with open(os.path.devnull, "w") as devnull:
                subprocess.call(["fakeroot", "-s", state_path, "cpio", "-i"],
                                stdin=fd, stdout=devnull, stderr=devnull)

    # Swap the files
    keyring_path = os.path.join(conf.gpg_keyring_path, keyring_name)

    # Handle two different keyring paths in the recovery
    dest_keyring_path = os.path.join(tempdir, "initrd", "usr", "share",
                                     "system-image", keyring_name)
    if not os.path.exists("%s.tar.xz" % dest_keyring_path):
        dest_keyring_path = os.path.join(tempdir, "initrd", "etc",
                                         "system-image", keyring_name)

    shutil.copy("%s.tar.xz" % keyring_path,
                "%s.tar.xz" % dest_keyring_path)

    shutil.copy("%s.tar.xz.asc" % keyring_path,
                "%s.tar.xz.asc" % dest_keyring_path)

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

    if compression == "gzip":
        gzip_compress(initrd_path, initrdimg_path)
    elif compression == "xz":
        xz_compress(initrd_path, initrdimg_path)
    else:
        shutil.copyfile(initrd_path, initrdimg_path)

    if additional_header:
        # Append the previously removed header
        tmp_path = os.path.join(tempdir, "img", "initrd.img.tmp")
        reattach_recovery_header(initrdimg_path, tmp_path, header_contents)
        os.rename(tmp_path, initrdimg_path)

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
    output_tarball = tarfile.open(os.path.join(tempdir, "output.tar"), "w:",
                                  format=tarfile.GNU_FORMAT)
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


def get_required_deltas(conf, pub, channel, device_name):
    """
        Fetch the list of deltas for the selected channel and device.
    """

    device = pub.get_device(channel, device_name)

    full_images = {image['version']: image
                   for image in device.list_images()
                   if image['type'] == "full"}

    delta_base = []

    # If channel not configured, use dest channel as a deltabase by default
    conf_deltabase = (conf.channels[channel].deltabase
                      if channel in conf.channels
                      else [channel])

    for base_channel in conf_deltabase:
        # Skip missing channels
        if base_channel not in pub.list_channels():
            continue

        # Skip missing devices
        if device_name not in (pub.list_channels()
                               [base_channel]['devices']):
            continue

        # Extract the latest full image
        base_device = pub.get_device(base_channel, device_name)
        base_images = sorted([image
                              for image in base_device.list_images()
                              if image['type'] == "full"],
                             key=itemgetter('version'))

        # Check if the version is valid and add it
        if base_images and base_images[-1]['version'] in full_images:
            if full_images[base_images[-1]['version']] not in delta_base:
                delta_base.append(full_images
                                  [base_images[-1]['version']])
                logging.debug("Source version for delta: %s" %
                              base_images[-1]['version'])

    return delta_base


def extract_files_and_version(conf, base_files, version, files):
    """
        Helper function for scripts.
        Fill in the files array with all the files from the selected image
        (copying the paths over) and return the version_detail extracted from
        the version json file. base_files are to be in non-absolute paths.
    """

    version_detail = ""

    # Fetch all files and the version_detail
    for entry in base_files:
        path = os.path.realpath("%s/%s" % (conf.publish_path, entry['path']))
        print(path)

        filename = path.split("/")[-1]

        # Look for version-X.tar.xz
        if filename == "version-%s.tar.xz" % version:
            # Extract the metadata
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())
                    if "channel.ini" in metadata:
                        version_detail = metadata['channel.ini'].get(
                            "version_detail", None)
        else:
            files.append(path)

    return version_detail


def set_tag_on_version_detail(version_detail_list, tag):
    """
        Append a tag to the version_detail array.
    """

    clean_tags_on_version_detail(version_detail_list)

    if tag:
        version_detail_list.append("tag=%s" % tag)


def clean_tags_on_version_detail(version_detail_list):
    """
        Remove all tags from the version_detail array.
    """

    for detail in version_detail_list:
        if detail.startswith("tag="):
            version_detail_list.remove(detail)


def get_tags_on_version_detail(version_detail_list):
    """
        gets tags from the version_detail array.
    """

    tag = None
    for detail in version_detail_list:
        if detail.startswith("tag="):
            tag = detail.split("=")[1]
            break
    return tag
