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

import json
import logging
import os
import shutil
import socket
import tarfile
import tempfile
import time
from hashlib import sha256
from urllib.request import urlopen, urlretrieve, build_opener, install_opener

from systemimage import diff, gpg, tools, tree

# Global
CACHE = {}
OPENER = build_opener()
OPENER.addheaders = [("User-Agent", "system-image-server")]
install_opener(OPENER)

logger = logging.getLogger(__name__)


class VersionError(Exception):
    """Raised when the monitor version is invalid"""


def list_versions(cdimage_path):
    versions = sorted([version for version in os.listdir(cdimage_path)
                      if version not in ("pending", "current")],
                      reverse=True)
    logger.debug("Versions detected: %s" % versions)
    return versions


def root_ownership(tarinfo):
    tarinfo.mode = 0o644
    tarinfo.mtime = int(time.strftime("%s", time.localtime()))
    tarinfo.uname = "root"
    tarinfo.gname = "root"
    return tarinfo


def unpack_arguments(arguments):
    """
        Takes a string representing comma separate key=value options and
        returns a dict.
    """
    arg_dict = {}

    for option in arguments.split(","):
        fields = option.split("=", 1)
        if len(fields) != 2:
            continue

        arg_dict[fields[0]] = fields[1]

    return arg_dict


def generate_delta(conf, source_path, target_path):
    """
        Take two .tar.xz file and generate a third file, stored in the pool.
        The path to the pool file is then returned and <path>.asc is also
        generated using the default signing key.
    """
    source_filename = source_path.split("/")[-1].replace(".tar.xz", "")
    target_filename = target_path.split("/")[-1].replace(".tar.xz", "")

    # FIXME: This is a bit of an hack, it'd be better not to have to hardcode
    #        that kind of stuff...
    if (source_filename.startswith("version-")
            and target_filename.startswith("version-")):
        return target_path

    if (source_filename.startswith("keyring-")
            and target_filename.startswith("keyring-")):
        return target_path

        # skip creating delta for android9+ device overlay
    if (source_filename.startswith("boot-")
            and target_filename.startswith("boot-")):
        return target_path

    # Now for everything else
    path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                         "%s.delta-%s.tar.xz" %
                                         (target_filename, source_filename)))
    logger.debug("Path generated: %s" % path)

    # Return pre-existing entries
    if os.path.exists(path):
        return path

    # Create the pool if it doesn't exist
    if not os.path.exists(os.path.join(conf.publish_path, "pool")):
        os.makedirs(os.path.join(conf.publish_path, "pool"))

    # Generate the diff
    tempdir = tempfile.mkdtemp()
    tools.xz_uncompress(source_path, os.path.join(tempdir, "source.tar"))
    tools.xz_uncompress(target_path, os.path.join(tempdir, "target.tar"))

    imagediff = diff.ImageDiff(os.path.join(tempdir, "source.tar"),
                               os.path.join(tempdir, "target.tar"))

    imagediff.generate_diff_tarball(os.path.join(tempdir, "output.tar"))
    tools.xz_compress(os.path.join(tempdir, "output.tar"), path)
    shutil.rmtree(tempdir)

    # Sign the result
    gpg.sign_file(conf, "image-signing", path)

    # Generate the metadata file
    metadata = {}
    metadata['generator'] = "delta"
    metadata['source'] = {}
    metadata['target'] = {}

    if os.path.exists(source_path.replace(".tar.xz", ".json")):
        with open(source_path.replace(".tar.xz", ".json"), "r") as fd:
            metadata['source'] = json.loads(fd.read())

    if os.path.exists(target_path.replace(".tar.xz", ".json")):
        with open(target_path.replace(".tar.xz", ".json"), "r") as fd:
            metadata['target'] = json.loads(fd.read())

    with open(path.replace(".tar.xz", ".json"), "w+") as fd:
        fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                     indent=4, separators=(",", ": ")))
    gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

    return path


def generate_file(conf, generator, arguments, environment):
    """
        Dispatcher for the various generators and importers.
        It calls the right generator and signs the generated file
        before returning the path.
    """

    if generator == "version":
        path = generate_file_version(conf, arguments, environment)
    elif generator == "cdimage-ubuntu":
        path = generate_file_cdimage_ubuntu(conf, arguments, environment)
    elif generator == "cdimage-custom":
        path = generate_file_cdimage_custom(conf, arguments, environment)
    elif generator == "cdimage-device-raw":
        path = generate_file_cdimage_device_raw(conf, arguments, environment)
    elif generator == "http":
        path = generate_file_http(conf, arguments, environment)
    elif generator == "http-cdimage":
        path = generate_file_http_livecd_rootfs(conf, arguments, environment)
    elif generator == "keyring":
        path = generate_file_keyring(conf, arguments, environment)
    elif generator == "system-image":
        path = generate_file_system_image(conf, arguments, environment)
    elif generator == "remote-system-image":
        path = generate_file_remote_system_image(conf, arguments, environment)
    else:
        raise Exception("Invalid generator: %s" % generator)

    return path


def get_monitor_version(url):
    """
        Retrieve the version number given at URL
    """
    try:
        version = urlopen(url, timeout=5).read().decode("utf-8").strip()
    except (socket.timeout, IOError) as e:
        logger.exception(e)
        logger.error("Failed to download %s", url)
        raise e

    # Validate the version number
    if not version or len(version.split("\n")) > 1:
        logger.error("Invalid or missing version number %s", version)
        raise VersionError()

    return version


def generate_file_http_livecd_rootfs(conf, arguments, environment):
    """
        Grab, cache and returns a file using http/https.
    """

    # We need at least a URL
    if len(arguments) == 0:
        logger.debug("Too few arguments")
        return None

    # Read the arguments
    url = arguments[0]

    options = {}
    if len(arguments) > 1:
        options = unpack_arguments(arguments[1])

    path = None
    version = None

    if "http_%s" % url in CACHE:
        version = CACHE['http_%s' % url]

    # Get the version/build number
    if "monitor" in options or version:
        if not version:
            try:
                version = get_monitor_version(options['monitor'])
            except (VersionError, socket.timeout, IOError):
                return None

            # Push the result in the cache
            CACHE['http_%s' % url] = version

        # Set version_detail
        version_detail = "%s=%s" % (options.get("name", "http-cdimage"),
                                    version)

        # FIXME: can be dropped once all the non-hased tarballs are gone
        old_path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                                 "%s-%s.tar.xz" %
                                                 (options.get("name",
                                                              "http-cdimage"),
                                                  version)))
        logger.debug("Path generated: %s" % old_path)

        if os.path.exists(old_path):
            # Get the real version number (in case it got copied)
            if os.path.exists(old_path.replace(".tar.xz", ".json")):
                with open(old_path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            return old_path

        # Build the path, hasing together the URL and version
        hash_string = "%s:%s" % (url, version)
        global_hash = sha256(hash_string.encode("utf-8")).hexdigest()
        path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                             "%s-%s.tar.xz" %
                                             (options.get("name",
                                                          "http-cdimage"),
                                              global_hash)))
        logger.debug("Path generated: %s" % path)

        # Return pre-existing entries
        if os.path.exists(path):
            # Get the real version number (in case it got copied)
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            return path

    # Grab the real thing
    tempdir = tempfile.mkdtemp()
    old_timeout = socket.getdefaulttimeout()
    # Give it 20 minutes to download, this should be plenty
    socket.setdefaulttimeout(20)
    try:
        urlretrieve(url, os.path.join(tempdir, "download"))
    except (socket.timeout, IOError) as e:
        logger.exception(e)
        logger.error("Failed to retrieve url %s", url)
        shutil.rmtree(tempdir)
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)

    # Hash it if we don't have a version number
    if not version:
        # Hash the file
        with open(os.path.join(tempdir, "download"), "rb") as fd:
            version = sha256(fd.read()).hexdigest()

        # Set version_detail
        version_detail = "%s=%s" % (options.get("name", "http-cdimage"),
                                    version)

        # Push the result in the cache
        CACHE['http_%s' % url] = version

        # Build the path
        path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                             "%s-%s.tar.xz" %
                                             (options.get("name",
                                                          "http-cdimage"),
                                              version)))
        logger.debug("Path generated: %s" % path)

        # Return pre-existing entries
        if os.path.exists(path):
            # Get the real version number (in case it got copied)
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            shutil.rmtree(tempdir)
            return path

    temp_dir = tempfile.mkdtemp()
    rootfs_path = os.path.join(tempdir, "download")

    # Unpack the source tarball
    logger.debug("Opening tarball for processing")
    tools.gzip_uncompress(rootfs_path, os.path.join(temp_dir,
                                                    "source.tar"))

    # Generate a new shifted tarball
    source_tarball = tarfile.open(os.path.join(temp_dir, "source.tar"),
                                  "r:")
    target_tarball = tarfile.open(os.path.join(temp_dir, "target.tar"),
                                  "w:", format=tarfile.GNU_FORMAT)

    for entry in source_tarball:
        # FIXME: Will need to be done on the real rootfs
        # Skip some files
        if entry.name in ("SWAP.swap", "etc/mtab"):
            continue

        fileptr = None
        if entry.isfile():
            try:
                fileptr = source_tarball.extractfile(entry.name)
            except KeyError:  # pragma: no cover
                pass

        # Update hardlinks to point to the right target
        if entry.islnk():
            entry.linkname = "system/%s" % entry.linkname

        entry.name = "system/%s" % entry.name
        target_tarball.addfile(entry, fileobj=fileptr)

    new_file = tarfile.TarInfo()
    new_file.type = tarfile.DIRTYPE
    new_file.name = "system/android"
    new_file.mode = 0o755
    new_file.mtime = int(time.strftime("%s", time.localtime()))
    new_file.uname = "root"
    new_file.gname = "root"
    target_tarball.addfile(new_file)

    # # Android partitions
    for android_path in ("cache", "data", "factory", "firmware",
                         "persist", "system", "odm"):
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.SYMTYPE
        new_file.name = "system/%s" % android_path
        new_file.linkname = "/android/%s" % android_path
        new_file.mode = 0o755
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

    # # /vendor
    new_file = tarfile.TarInfo()
    new_file.type = tarfile.SYMTYPE
    new_file.name = "system/vendor"
    new_file.linkname = "/android/system/vendor"
    new_file.mode = 0o755
    new_file.mtime = int(time.strftime("%s", time.localtime()))
    new_file.uname = "root"
    new_file.gname = "root"
    target_tarball.addfile(new_file)

    # writable partition
    # (/userdata for Touch, /writable for Core)
    new_file = tarfile.TarInfo()
    new_file.type = tarfile.DIRTYPE

    if options.get("product", "touch") == "core":
        new_file.name = "system/writable"
    else:
        new_file.name = "system/userdata"

    new_file.mode = 0o755
    new_file.mtime = int(time.strftime("%s", time.localtime()))
    new_file.uname = "root"
    new_file.gname = "root"
    target_tarball.addfile(new_file)

    # # /etc/mtab
    new_file = tarfile.TarInfo()
    new_file.type = tarfile.SYMTYPE
    new_file.name = "system/etc/mtab"
    new_file.linkname = "/proc/mounts"
    new_file.mode = 0o444
    new_file.mtime = int(time.strftime("%s", time.localtime()))
    new_file.uname = "root"
    new_file.gname = "root"
    target_tarball.addfile(new_file)

    # # /lib/modules
    new_file = tarfile.TarInfo()
    new_file.type = tarfile.DIRTYPE
    new_file.name = "system/lib/modules"
    new_file.mode = 0o755
    new_file.mtime = int(time.strftime("%s", time.localtime()))
    new_file.uname = "root"
    new_file.gname = "root"
    target_tarball.addfile(new_file)

    logger.debug("Closing tarball")
    source_tarball.close()
    target_tarball.close()

    # Create the pool if it doesn't exist
    if not os.path.exists(os.path.join(conf.publish_path, "pool")):
        os.makedirs(os.path.join(conf.publish_path, "pool"))

    # Compress the target tarball and sign it
    tools.xz_compress(os.path.join(temp_dir, "target.tar"), path)
    gpg.sign_file(conf, "image-signing", path)

    # Generate the metadata file
    metadata = {}
    metadata['generator'] = "cdimage-ubports"
    metadata['version'] = version
    metadata['version_detail'] = version_detail
    metadata['rootfs_path'] = rootfs_path
    metadata['url'] = url

    with open(path.replace(".tar.xz", ".json"), "w+") as fd:
        fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                     indent=4, separators=(",", ": ")))
    gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

    # Cleanup
    shutil.rmtree(temp_dir)
    shutil.rmtree(tempdir)

    environment['version_detail'].append(version_detail)
    return path


def generate_file_cdimage_ubuntu(conf, arguments, environment):
    """
        Scan a cdimage tree for new ubuntu files.
    """

    # We need at least a path and a series
    if len(arguments) < 2:
        logger.debug("Too few arguments")
        return None

    # Read the arguments
    cdimage_path = arguments[0]
    series = arguments[1]

    options = {}
    if len(arguments) > 2:
        options = unpack_arguments(arguments[2])

    arch = "armhf"
    if environment['device_name'] in ("generic_x86", "generic_i386"):
        arch = "i386"
    elif environment['device_name'] in ("generic_amd64", "azure_amd64",
                                        "plano"):
        arch = "amd64"
    elif environment['device_name'] in ("generic_arm64", "frieza_arm64"):
        arch = "arm64"

    # Check that the directory exists
    if not os.path.exists(cdimage_path):
        logger.debug("Directory not found: %s" % cdimage_path)
        return None

    for version in list_versions(cdimage_path):
        # Skip directory without checksums
        checksum_path = os.path.exists(os.path.join(cdimage_path, version,
                                       "SHA256SUMS"))
        if not checksum_path:
            logger.debug("Missing checksum: %s" % checksum_path)
            continue

        # Check for the rootfs
        rootfs_path = os.path.join(cdimage_path, version,
                                   "%s-preinstalled-%s-%s.tar.gz" %
                                   (series, options.get("product", "touch"),
                                    arch))
        if not os.path.exists(rootfs_path):
            logger.debug("Missing rootfs tarball: %s" % rootfs_path)
            continue

        # Check if we should only import tested images
        if options.get("import", "any") == "good":
            if not os.path.exists(os.path.join(cdimage_path, version,
                                               ".marked_good")):
                continue

        # Set the version_detail string
        version_detail = "ubuntu=%s" % version

        # Extract the hash
        rootfs_hash = None
        with open(os.path.join(cdimage_path, version,
                               "SHA256SUMS"), "r") as fd:
            for line in fd:
                line = line.strip()
                if line.endswith(rootfs_path.split("/")[-1]):
                    rootfs_hash = line.split()[0]
                    break

        if not rootfs_hash:
            continue

        # Generate the path
        path = os.path.join(conf.publish_path, "pool",
                            "ubuntu-%s.tar.xz" % rootfs_hash)
        logger.debug("Path generated: %s" % path)

        # Return pre-existing entries
        if os.path.exists(path):
            # Get the real version number (in case it got copied)
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            return path

        temp_dir = tempfile.mkdtemp()

        # Unpack the source tarball
        logger.debug("Opening tarball for processing")
        tools.gzip_uncompress(rootfs_path, os.path.join(temp_dir,
                                                        "source.tar"))

        # Generate a new shifted tarball
        source_tarball = tarfile.open(os.path.join(temp_dir, "source.tar"),
                                      "r:")
        target_tarball = tarfile.open(os.path.join(temp_dir, "target.tar"),
                                      "w:", format=tarfile.GNU_FORMAT)

        for entry in source_tarball:
            # FIXME: Will need to be done on the real rootfs
            # Skip some files
            if entry.name in ("SWAP.swap", "etc/mtab"):
                continue

            fileptr = None
            if entry.isfile():
                try:
                    fileptr = source_tarball.extractfile(entry.name)
                except KeyError:  # pragma: no cover
                    pass

            # Update hardlinks to point to the right target
            if entry.islnk():
                entry.linkname = "system/%s" % entry.linkname

            entry.name = "system/%s" % entry.name
            target_tarball.addfile(entry, fileobj=fileptr)

        # The touch and pocket-desktop products are the same.
        if options.get("product", "touch") in ("touch", "pd"):
            # FIXME: Will need to be done on the real rootfs
            # Add some symlinks and directories
            # # /android
            new_file = tarfile.TarInfo()
            new_file.type = tarfile.DIRTYPE
            new_file.name = "system/android"
            new_file.mode = 0o755
            new_file.mtime = int(time.strftime("%s", time.localtime()))
            new_file.uname = "root"
            new_file.gname = "root"
            target_tarball.addfile(new_file)

            # # Android partitions
            for android_path in ("cache", "data", "factory", "firmware",
                                 "persist", "system", "odm"):
                new_file = tarfile.TarInfo()
                new_file.type = tarfile.SYMTYPE
                new_file.name = "system/%s" % android_path
                new_file.linkname = "/android/%s" % android_path
                new_file.mode = 0o755
                new_file.mtime = int(time.strftime("%s", time.localtime()))
                new_file.uname = "root"
                new_file.gname = "root"
                target_tarball.addfile(new_file)

            # # /vendor
            new_file = tarfile.TarInfo()
            new_file.type = tarfile.SYMTYPE
            new_file.name = "system/vendor"
            new_file.linkname = "/android/system/vendor"
            new_file.mode = 0o755
            new_file.mtime = int(time.strftime("%s", time.localtime()))
            new_file.uname = "root"
            new_file.gname = "root"
            target_tarball.addfile(new_file)

        # writable partition
        # (/userdata for Touch, /writable for Core)
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.DIRTYPE

        if options.get("product", "touch") == "core":
            new_file.name = "system/writable"
        else:
            new_file.name = "system/userdata"

        new_file.mode = 0o755
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

        # # /etc/mtab
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.SYMTYPE
        new_file.name = "system/etc/mtab"
        new_file.linkname = "/proc/mounts"
        new_file.mode = 0o444
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

        # # /lib/modules
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.DIRTYPE
        new_file.name = "system/lib/modules"
        new_file.mode = 0o755
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

        logger.debug("Closing tarball")
        source_tarball.close()
        target_tarball.close()

        # Create the pool if it doesn't exist
        if not os.path.exists(os.path.join(conf.publish_path, "pool")):
            os.makedirs(os.path.join(conf.publish_path, "pool"))

        # Compress the target tarball and sign it
        tools.xz_compress(os.path.join(temp_dir, "target.tar"), path)
        gpg.sign_file(conf, "image-signing", path)

        # Generate the metadata file
        metadata = {}
        metadata['generator'] = "cdimage-ubuntu"
        metadata['version'] = version
        metadata['version_detail'] = version_detail
        metadata['series'] = series
        metadata['rootfs_path'] = rootfs_path
        metadata['rootfs_checksum'] = rootfs_hash

        with open(path.replace(".tar.xz", ".json"), "w+") as fd:
            fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                         indent=4, separators=(",", ": ")))
        gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

        # Cleanup
        shutil.rmtree(temp_dir)

        environment['version_detail'].append(version_detail)
        return path

    return None


def generate_file_cdimage_custom(conf, arguments, environment):
    """
        Scan a cdimage tree for new custom files.
    """

    # We need at least a path and a series
    if len(arguments) < 2:
        logger.debug("Too few arguments")
        return None

    # Read the arguments
    cdimage_path = arguments[0]
    series = arguments[1]

    options = {}
    if len(arguments) > 2:
        options = unpack_arguments(arguments[2])

    arch = "armhf"
    if environment['device_name'] in ("generic_x86", "generic_i386"):
        arch = "i386"
    elif environment['device_name'] in ("generic_amd64",):
        arch = "amd64"
    elif environment['device_name'] in ("generic_arm64", "frieza_arm64"):
        arch = "arm64"

    # Check that the directory exists
    if not os.path.exists(cdimage_path):
        logger.debug("Directory not found: %s" % cdimage_path)
        return None

    for version in list_versions(cdimage_path):
        # Skip directory without checksums
        checksum_path = os.path.exists(os.path.join(cdimage_path, version,
                                       "SHA256SUMS"))
        if not checksum_path:
            logger.debug("Missing checksum: %s" % checksum_path)
            continue

        # Check for the custom tarball
        custom_path = os.path.join(cdimage_path, version,
                                   "%s-preinstalled-%s-%s.custom.tar.gz" %
                                   (series, options.get("product", "touch"),
                                    arch))
        if not os.path.exists(custom_path):
            logger.debug("Missing custom tarball: %s" % custom_path)
            continue

        # Check if we should only import tested images
        if options.get("import", "any") == "good":
            if not os.path.exists(os.path.join(cdimage_path, version,
                                               ".marked_good")):
                continue

        # Set the version_detail string
        version_detail = "custom=%s" % version

        # Extract the hash
        custom_hash = None
        with open(os.path.join(cdimage_path, version,
                               "SHA256SUMS"), "r") as fd:
            for line in fd:
                line = line.strip()
                if line.endswith(custom_path.split("/")[-1]):
                    custom_hash = line.split()[0]
                    break

        if not custom_hash:
            continue

        # Generate the path
        path = os.path.join(conf.publish_path, "pool",
                            "custom-%s.tar.xz" % custom_hash)
        logger.debug("Path generated: %s" % path)

        # Return pre-existing entries
        if os.path.exists(path):
            # Get the real version number (in case it got copied)
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            return path

        temp_dir = tempfile.mkdtemp()

        # Unpack the source tarball
        tools.gzip_uncompress(custom_path, os.path.join(temp_dir,
                                                        "source.tar"))

        # Create the pool if it doesn't exist
        if not os.path.exists(os.path.join(conf.publish_path, "pool")):
            os.makedirs(os.path.join(conf.publish_path, "pool"))

        # Compress the target tarball and sign it
        tools.xz_compress(os.path.join(temp_dir, "source.tar"), path)
        gpg.sign_file(conf, "image-signing", path)

        # Generate the metadata file
        metadata = {}
        metadata['generator'] = "cdimage-custom"
        metadata['version'] = version
        metadata['version_detail'] = version_detail
        metadata['series'] = series
        metadata['custom_path'] = custom_path
        metadata['custom_checksum'] = custom_hash

        with open(path.replace(".tar.xz", ".json"), "w+") as fd:
            fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                         indent=4, separators=(",", ": ")))
        gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

        # Cleanup
        shutil.rmtree(temp_dir)

        environment['version_detail'].append(version_detail)
        return path

    return None


def generate_file_cdimage_device_raw(conf, arguments, environment):
    """
        Scan a cdimage tree for new device files that can be unpacked as is
    """

    # We need at least a path and a series
    if len(arguments) < 2:
        logger.debug("Too few arguments")
        return None

    # Read the arguments
    cdimage_path = arguments[0]
    series = arguments[1]

    options = {}
    if len(arguments) > 2:
        options = unpack_arguments(arguments[2])

    arch = "armhf"
    if environment['device_name'] in ("generic_x86", "generic_i386"):
        arch = "i386"
    elif environment['device_name'] in ("generic_amd64",):
        arch = "amd64"
    elif environment['device_name'] == "azure_amd64":
        arch = "amd64.azure"
    elif environment['device_name'] == "plano":
        arch = "amd64.plano"
    elif environment['device_name'] == "raspi2_armhf":
        arch = "armhf.raspi2"
    elif environment['device_name'] == "generic_arm64":
        arch = "arm64"

    # Check that the directory exists
    if not os.path.exists(cdimage_path):
        logger.debug("Directory not found: %s" % cdimage_path)
        return None

    for version in list_versions(cdimage_path):
        # Skip directory without checksums
        if not os.path.exists(os.path.join(cdimage_path, version,
                                           "SHA256SUMS")):
            continue

        # Check for the custom tarball
        raw_device_path = os.path.join(
            cdimage_path, version,
            "%s-preinstalled-%s-%s.device.tar.gz" %
            (series, options.get("product", "core"),
             arch))
        if not os.path.exists(raw_device_path):
            continue

        # Check if we should only import tested images
        if options.get("import", "any") == "good":
            if not os.path.exists(os.path.join(cdimage_path, version,
                                               ".marked_good")):
                continue

        # Set the version_detail string
        version_detail = "raw-device=%s" % version

        # Extract the hash
        raw_device_hash = None
        with open(os.path.join(cdimage_path, version,
                               "SHA256SUMS"), "r") as fd:
            for line in fd:
                line = line.strip()
                if line.endswith(raw_device_path.split("/")[-1]):
                    raw_device_hash = line.split()[0]
                    break

        if not raw_device_hash:
            continue

        # Generate the path
        path = os.path.join(conf.publish_path, "pool",
                            "device-%s.tar.xz" % raw_device_hash)
        logger.debug("Path generated: %s" % path)

        # Return pre-existing entries
        if os.path.exists(path):
            # Get the real version number (in case it got copied)
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            return path

        temp_dir = tempfile.mkdtemp()

        # Unpack the source tarball
        tools.gzip_uncompress(raw_device_path, os.path.join(temp_dir,
                                                            "source.tar"))

        # Create the pool if it doesn't exist
        if not os.path.exists(os.path.join(conf.publish_path, "pool")):
            os.makedirs(os.path.join(conf.publish_path, "pool"))

        # Compress the target tarball and sign it
        tools.xz_compress(os.path.join(temp_dir, "source.tar"), path)
        gpg.sign_file(conf, "image-signing", path)

        # Generate the metadata file
        metadata = {}
        metadata['generator'] = "cdimage-device-raw"
        metadata['version'] = version
        metadata['version_detail'] = version_detail
        metadata['series'] = series
        metadata['raw_device_path'] = raw_device_path
        metadata['raw_device_checksum'] = raw_device_hash
        metadata['device'] = environment.get("device_name", "none")

        with open(path.replace(".tar.xz", ".json"), "w+") as fd:
            fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                         indent=4, separators=(",", ": ")))
        gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

        # Cleanup
        shutil.rmtree(temp_dir)

        environment['version_detail'].append(version_detail)
        return path

    return None


def generate_file_http(conf, arguments, environment):
    """
        Grab, cache and returns a file using http/https.
    """

    # We need at least a URL
    if len(arguments) == 0:
        logger.debug("Too few arguments")
        return None

    # Read the arguments
    url = arguments[0]

    options = {}
    if len(arguments) > 1:
        options = unpack_arguments(arguments[1])

    path = None
    version = None

    if "http_%s" % url in CACHE:
        version = CACHE['http_%s' % url]

    # Get the version/build number
    if "monitor" in options or version:
        if not version:
            try:
                version = get_monitor_version(options['monitor'])
            except (VersionError, socket.timeout, IOError):
                return None

            # Push the result in the cache
            CACHE['http_%s' % url] = version

        # Set version_detail
        version_detail = "%s=%s" % (options.get("name", "http"), version)

        # FIXME: can be dropped once all the non-hased tarballs are gone
        old_path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                                 "%s-%s.tar.xz" %
                                                 (options.get("name", "http"),
                                                  version)))
        logger.debug("Path generated: %s" % old_path)

        if os.path.exists(old_path):
            # Get the real version number (in case it got copied)
            if os.path.exists(old_path.replace(".tar.xz", ".json")):
                with open(old_path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            return old_path

        # Build the path, hasing together the URL and version
        hash_string = "%s:%s" % (url, version)
        global_hash = sha256(hash_string.encode("utf-8")).hexdigest()
        path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                             "%s-%s.tar.xz" %
                                             (options.get("name", "http"),
                                              global_hash)))
        logger.debug("Path generated: %s" % path)

        # Return pre-existing entries
        if os.path.exists(path):
            # Get the real version number (in case it got copied)
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            return path

    # Grab the real thing
    tempdir = tempfile.mkdtemp()
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        urlretrieve(url, os.path.join(tempdir, "download"))
    except (socket.timeout, IOError) as e:
        logger.exception(e)
        logger.error("Failed to retrieve url %s", url)
        shutil.rmtree(tempdir)
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)

    # Hash it if we don't have a version number
    if not version:
        # Hash the file
        with open(os.path.join(tempdir, "download"), "rb") as fd:
            version = sha256(fd.read()).hexdigest()

        # Set version_detail
        version_detail = "%s=%s" % (options.get("name", "http"), version)

        # Push the result in the cache
        CACHE['http_%s' % url] = version

        # Build the path
        path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                             "%s-%s.tar.xz" %
                                             (options.get("name", "http"),
                                              version)))
        logger.debug("Path generated: %s" % path)

        # Return pre-existing entries
        if os.path.exists(path):
            # Get the real version number (in case it got copied)
            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    version_detail = metadata['version_detail']

            environment['version_detail'].append(version_detail)
            shutil.rmtree(tempdir)
            return path

    # Create the pool if it doesn't exist
    if not os.path.exists(os.path.join(conf.publish_path, "pool")):
        os.makedirs(os.path.join(conf.publish_path, "pool"))

    # Move the file to the pool and sign it
    shutil.move(os.path.join(tempdir, "download"), path)
    gpg.sign_file(conf, "image-signing", path)

    # Generate the metadata file
    metadata = {}
    metadata['generator'] = "http"
    metadata['version'] = version
    metadata['version_detail'] = version_detail
    metadata['url'] = url

    with open(path.replace(".tar.xz", ".json"), "w+") as fd:
        fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                     indent=4, separators=(",", ": ")))
    gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

    # Cleanup
    shutil.rmtree(tempdir)

    environment['version_detail'].append(version_detail)
    return path


def generate_file_keyring(conf, arguments, environment):
    """
        Generate a keyring tarball or return a pre-existing one.
    """

    # Don't generate keyring tarballs when nothing changed
    if len(environment['new_files']) == 0:
        logger.debug("Nothing has changed, no new files")
        return None

    # We need a keyring name
    if len(arguments) == 0:
        logger.debug("Too few arguments")
        return None

    # Read the arguments
    keyring_name = arguments[0]
    keyring_path = os.path.join(conf.gpg_keyring_path, keyring_name)

    # Fail on missing keyring
    if not os.path.exists("%s.tar.xz" % keyring_path) or \
            not os.path.exists("%s.tar.xz.asc" % keyring_path):
        return None

    with open("%s.tar.xz" % keyring_path, "rb") as fd:
        hash_tarball = sha256(fd.read()).hexdigest()

    with open("%s.tar.xz.asc" % keyring_path, "rb") as fd:
        hash_signature = sha256(fd.read()).hexdigest()

    hash_string = "%s/%s" % (hash_tarball, hash_signature)
    global_hash = sha256(hash_string.encode("utf-8")).hexdigest()

    # Build the path
    path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                         "keyring-%s.tar.xz" %
                                         global_hash))
    logger.debug("Path generated: %s" % path)

    # Set the version_detail string
    environment['version_detail'].append("keyring=%s" % keyring_name)

    # Don't bother re-generating a file if it already exists
    if os.path.exists(path):
        return path

    # Create temporary directory
    tempdir = tempfile.mkdtemp()

    # Generate the tarball
    tarball = tarfile.open(os.path.join(tempdir, "output.tar"), "w:",
                           format=tarfile.GNU_FORMAT)
    tarball.add("%s.tar.xz" % keyring_path,
                arcname="/system/usr/share/system-image/"
                        "archive-master.tar.xz",
                filter=root_ownership)
    tarball.add("%s.tar.xz.asc" % keyring_path,
                arcname="/system/usr/share/system-image/"
                        "archive-master.tar.xz.asc",
                filter=root_ownership)
    tarball.close()

    # Create the pool if it doesn't exist
    if not os.path.exists(os.path.join(conf.publish_path, "pool")):
        os.makedirs(os.path.join(conf.publish_path, "pool"))

    # Compress and sign it
    tools.xz_compress(os.path.join(tempdir, "output.tar"), path)
    gpg.sign_file(conf, "image-signing", path)

    # Generate the metadata file
    metadata = {}
    metadata['generator'] = "keyring"
    metadata['version'] = global_hash
    metadata['version_detail'] = "keyring=%s" % keyring_name
    metadata['path'] = keyring_path

    with open(path.replace(".tar.xz", ".json"), "w+") as fd:
        fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                     indent=4, separators=(",", ": ")))
    gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

    # Cleanup
    shutil.rmtree(tempdir)

    return path


def generate_file_remote_system_image(conf, arguments, environment):
    """
        Import files from a remote system-image server
    """

    # We need at least a channel name and a file prefix
    if len(arguments) < 3:
        logger.debug("Too few arguments")
        return None

    # Read the arguments
    base_url = arguments[0]
    channel_name = arguments[1]
    prefix = arguments[2]

    options = {}
    if len(arguments) > 3:
        options = unpack_arguments(arguments[3])

    device_name = environment['device_name']
    if 'device' in options:
        device_name = options['device']

    # Fetch and validate the remote channels.json
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    url = "%s/channels.json" % base_url
    try:
        channel_json = json.loads(urlopen(url).read().decode().strip())
    except (socket.timeout, IOError) as e:
        logger.exception(e)
        logger.error("Failed to retrieve url %s", url)
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)

    if channel_name not in channel_json:
        logger.debug("Missing channel name in JSON: %s" % channel_name)
        return None

    if "devices" not in channel_json[channel_name]:
        logger.debug("Missing devices for channel name in JSON")
        return None

    if device_name not in channel_json[channel_name]['devices']:
        logger.debug("Missing device name in JSON: %s" % device_name)
        return None

    if "index" not in (channel_json[channel_name]['devices']
                       [device_name]):
        logger.debug("Missing index for the channel device in JSON")
        return None

    index_url = "%s/%s" % (base_url, channel_json[channel_name]['devices']
                           [device_name]['index'])
    logger.debug("Index file for the devices in channel: %s" % index_url)

    # Fetch and validate the remote index.json
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        index_json = json.loads(urlopen(index_url).read().decode())
    except (socket.timeout, IOError) as e:
        logger.exception(e)
        logger.error("Failed to retrieve url %s", index_url)
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)

    # Grab the list of full images
    full_images = sorted([image for image in index_json['images']
                          if image['type'] == "full"],
                         key=lambda image: image['version'])
    logger.debug("List of full images founds %s" % full_images)

    # No images
    if not full_images:
        return None

    # Found an image, so let's try to find a match
    for file_entry in full_images[-1]['files']:
        file_name = file_entry['path'].split("/")[-1]
        file_prefix = file_name.rsplit("-", 1)[0]
        if file_prefix == prefix:
            path = os.path.realpath("%s/%s" % (conf.publish_path,
                                               file_entry['path']))
            logger.debug("Path generated: %s" % path)

            if os.path.exists(path):
                return path

            # Create the target if needed
            if not os.path.exists(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))

            # Grab the file
            file_url = "%s/%s" % (base_url, file_entry['path'])
            socket.setdefaulttimeout(5)
            try:
                urlretrieve(file_url, path)
            except (socket.timeout, IOError) as e:
                logger.exception(e)
                logger.error("Failed to retrieve url %s", file_url)
                if os.path.exists(path):
                    os.remove(path)
                return None
            finally:
                socket.setdefaulttimeout(old_timeout)

            if "keyring" in options:
                if not tools.repack_recovery_keyring(conf, path,
                                                     options['keyring'],
                                                     device_name):
                    if os.path.exists(path):
                        os.remove(path)
                    return None

            gpg.sign_file(conf, "image-signing", path)

            # Attempt to grab an associated json
            socket.setdefaulttimeout(5)
            json_path = path.replace(".tar.xz", ".json")
            json_url = file_url.replace(".tar.xz", ".json")
            try:
                urlretrieve(json_url, json_path),
            except (socket.timeout, IOError) as e:
                logger.exception(e)
                logger.error("Failed to retrieve url %s", json_url)
                if os.path.exists(json_path):
                    os.remove(json_path)
            finally:
                socket.setdefaulttimeout(old_timeout)

            if os.path.exists(json_path):
                gpg.sign_file(conf, "image-signing", json_path)
                with open(json_path, "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    environment['version_detail'].append(
                        metadata['version_detail'])

            return path

    return None


def generate_file_system_image(conf, arguments, environment):
    """
        Copy a file from another channel.
    """

    # We need at least a channel name and a file prefix
    if len(arguments) < 2:
        logger.error("Too few arguments")
        return None

    # Read the arguments
    channel_name = arguments[0]
    prefix = arguments[1]

    options = {}
    if len(arguments) > 2:
        options = unpack_arguments(arguments[2])

    # We also support an optional argument to use a different source device
    device_name = environment['device_name']
    if 'device' in options:
        device_name = options['device']

    # Run some checks
    pub = tree.Tree(conf)
    if channel_name not in pub.list_channels():
        logger.error("Channel not in the published list: %s", channel_name)
        return None

    if (device_name not in
            pub.list_channels()[channel_name]['devices']):
        logger.error("Device not in the channel list: %s", device_name)
        return None

    # Try to find the file
    device = pub.get_device(channel_name, device_name)

    full_images = sorted([image for image in device.list_images()
                          if image['type'] == "full"],
                         key=lambda image: image['version'])
    logger.debug("List of full images found %s", full_images)

    # No images
    if not full_images:
        logger.error("No images found for device: %s", device_name)
        return None

    # Found an image, so let's try to find a match
    for file_entry in full_images[-1]['files']:
        file_name = file_entry['path'].split("/")[-1]
        file_prefix = file_name.rsplit("-", 1)[0]
        if file_prefix == prefix:
            path = os.path.realpath("%s/%s" % (conf.publish_path,
                                               file_entry['path']))
            logger.debug("Path generated: %s", path)

            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    environment['version_detail'].append(
                        metadata['version_detail'])

            return path

    logger.error(
        "No match found for image '%s' for device '%s' in channel '%s'",
        prefix, device_name, channel_name)
    return None


def generate_file_version(conf, arguments, environment):
    """
        Generate a version tarball or return a pre-existing one.
    """

    # Don't generate version tarballs when nothing changed
    if len(environment['new_files']) == 0:
        logger.debug("Nothing has changed, no new files")
        return None

    path = os.path.realpath(os.path.join(environment['device'].path,
                            "version-%s.tar.xz" % environment['version']))
    logger.debug("Path generated: %s" % path)

    # Set the version_detail string
    environment['version_detail'].append("version=%s" % environment['version'])

    # Don't bother re-generating a file if it already exists
    if os.path.exists(path):
        logger.debug("Version file already exists")
        return path

    # Generate version_detail
    version_detail = ",".join(environment['version_detail'])

    # Create temporary directory
    tempdir = tempfile.mkdtemp()

    # Generate the tarball
    tools.generate_version_tarball(
        conf, environment['channel_name'], environment['device_name'],
        str(environment['version']),
        os.path.join(tempdir, "version"), version_detail=version_detail)

    # Create the pool if it doesn't exist
    if not os.path.exists(os.path.join(environment['device'].path)):
        os.makedirs(os.path.join(environment['device'].path))

    # Compress and sign it
    tools.xz_compress(os.path.join(tempdir, "version"), path)
    gpg.sign_file(conf, "image-signing", path)

    # Generate the metadata file
    tools.generate_version_metadata(
        conf,
        environment['version'],
        environment['channel_name'],
        environment['device_name'],
        path,
        version_detail)

    # Cleanup
    shutil.rmtree(tempdir)

    return path
