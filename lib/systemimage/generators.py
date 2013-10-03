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

from hashlib import sha256
from systemimage import diff, gpg, tree, tools
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time

try:
    from urllib.request import urlopen, urlretrieve
except ImportError:
    from urllib import urlopen, urlretrieve

# Global
CACHE = {}


def unpack_arguments(arguments):
    """
        Takes a string representing comma separate key=value options and
        returns a dict.
    """
    arg_dict = {}

    for option in arguments.split(","):
        fields = option.split("=")
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

    # Now for everything else
    path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                         "%s.delta-%s.tar.xz" %
                                         (target_filename, source_filename)))

    # Return pre-existing entries
    if os.path.exists(path):
        return path

    # FIXME: The code was wrong for a while, so look for the wrong names too
    #        This code will be deprecated once the last affected image gets
    #        expired on the production server
    legacy = True
    if legacy:  # pragma: no cover
        wrong_path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                                   "%s.delta-%s.tar.xz" %
                                                   (source_filename,
                                                    target_filename)))

        # Return pre-existing entries
        if os.path.exists(wrong_path):
            return wrong_path

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
                                     indent=4, separators=(',', ': ')))
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
    elif generator == "cdimage-device":
        path = generate_file_cdimage_device(conf, arguments, environment)
    elif generator == "cdimage-ubuntu":
        path = generate_file_cdimage_ubuntu(conf, arguments, environment)
    elif generator == "http":
        path = generate_file_http(conf, arguments, environment)
    elif generator == "system-image":
        path = generate_file_system_image(conf, arguments, environment)
    else:
        raise Exception("Invalid generator: %s" % generator)

    if not path:
        return None

    return path


def generate_file_cdimage_device(conf, arguments, environment):
    """
        Scan a cdimage tree for new device files.
    """

    # We need at least a path and a series
    if len(arguments) < 2:
        return None

    # Read the arguments
    cdimage_path = arguments[0]
    series = arguments[1]

    options = {}
    if len(arguments) > 1:
        options = unpack_arguments(arguments[1])

    # Check that the directory exists
    if not os.path.exists(cdimage_path):
        return None

    versions = sorted([version for version in os.listdir(cdimage_path)
                       if version not in ("pending", "current")],
                      reverse=True)

    for version in versions:
        boot_path = os.path.join(cdimage_path, version,
                                 "%s-preinstalled-boot-armhf+%s.img" %
                                 (series, environment['device_name']))
        if not os.path.exists(boot_path):
            continue

        recovery_path = os.path.join(cdimage_path, version,
                                     "%s-preinstalled-recovery-armel+%s.img" %
                                     (series, environment['device_name']))
        if not os.path.exists(recovery_path):
            continue

        system_path = os.path.join(cdimage_path, version,
                                   "%s-preinstalled-system-armel+%s.img" %
                                   (series, environment['device_name']))
        if not os.path.exists(system_path):
            continue

        # Check if we should only import tested images
        if options.get("import", "any") == "good":
            if not os.path.exists(os.path.join(cdimage_path, version,
                                               ".marked_good")):
                continue

        # Set the version_detail string
        version_detail = "device=%s" % version

        # Extract the hashes
        boot_hash = None
        recovery_hash = None
        system_hash = None
        with open(os.path.join(cdimage_path, version,
                               "SHA256SUMS"), "r") as fd:
            for line in fd:
                line = line.strip()
                if line.endswith(boot_path.split("/")[-1]):
                    boot_hash = line.split()[0]
                elif line.endswith(recovery_path.split("/")[-1]):
                    recovery_hash = line.split()[0]
                elif line.endswith(system_path.split("/")[-1]):
                    system_hash = line.split()[0]

                if boot_hash and recovery_hash and system_hash:
                    break

        if not boot_hash or not recovery_hash or not system_hash:
            continue

        global_hash = sha256("%s/%s/%s" % (boot_hash, recovery_hash,
                                           system_hash)).hexdigest()

        # Generate the path
        path = os.path.join(conf.publish_path, "pool",
                            "device-%s.tar.xz" % global_hash)

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

        # Generate a new tarball
        target_tarball = tarfile.open(os.path.join(temp_dir, "target.tar"),
                                      "w:")

        def root_ownership(tarinfo):
            tarinfo.mode = 0o644
            tarinfo.mtime = int(time.strftime("%s", time.localtime()))
            tarinfo.uname = "root"
            tarinfo.gname = "root"
            return tarinfo

        # system image
        ## convert to raw image
        system_img = os.path.join(temp_dir, "system.img")
        with open(os.path.devnull, "w") as devnull:
            subprocess.call(["simg2img", system_path, system_img],
                            stdout=devnull)

        ## shrink to minimal size
        with open(os.path.devnull, "w") as devnull:
            subprocess.call(["resize2fs", "-M", system_img],
                            stdout=devnull, stderr=devnull)

        ## include in tarball
        target_tarball.add(system_img,
                           arcname="system/var/lib/lxc/android/system.img",
                           filter=root_ownership)

        # boot image
        target_tarball.add(boot_path, arcname="partitions/boot.img",
                           filter=root_ownership)

        # recovery image
        target_tarball.add(recovery_path,
                           arcname="partitions/recovery.img",
                           filter=root_ownership)

        target_tarball.close()

        # Create the pool if it doesn't exist
        if not os.path.exists(os.path.join(conf.publish_path, "pool")):
            os.makedirs(os.path.join(conf.publish_path, "pool"))

        # Compress the target tarball and sign it
        tools.xz_compress(os.path.join(temp_dir, "target.tar"), path)
        gpg.sign_file(conf, "image-signing", path)

        # Generate the metadata file
        metadata = {}
        metadata['generator'] = "cdimage-device"
        metadata['version'] = version
        metadata['version_detail'] = version_detail
        metadata['series'] = series
        metadata['device'] = environment['device_name']
        metadata['boot_path'] = boot_path
        metadata['boot_checksum'] = boot_hash
        metadata['recovery_path'] = recovery_path
        metadata['recovery_checksum'] = recovery_hash
        metadata['system_path'] = system_path
        metadata['system_checksum'] = system_hash

        with open(path.replace(".tar.xz", ".json"), "w+") as fd:
            fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                         indent=4, separators=(',', ': ')))
        gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

        # Cleanup
        shutil.rmtree(temp_dir)

        environment['version_detail'].append(version_detail)
        return path

    return None


def generate_file_cdimage_ubuntu(conf, arguments, environment):
    """
        Scan a cdimage tree for new ubuntu files.
    """

    # We need at least a path and a series
    if len(arguments) < 2:
        return None

    # Read the arguments
    cdimage_path = arguments[0]
    series = arguments[1]

    options = {}
    if len(arguments) > 1:
        options = unpack_arguments(arguments[1])

    # Check that the directory exists
    if not os.path.exists(cdimage_path):
        return None

    versions = sorted([version for version in os.listdir(cdimage_path)
                       if version not in ("pending", "current")],
                      reverse=True)

    for version in versions:
        rootfs_path = os.path.join(cdimage_path, version,
                                   "%s-preinstalled-touch-armhf.tar.gz" %
                                   series)
        if not os.path.exists(rootfs_path):
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
        tools.gzip_uncompress(rootfs_path, os.path.join(temp_dir,
                                                        "source.tar"))

        # Generate a new shifted tarball
        source_tarball = tarfile.open(os.path.join(temp_dir, "source.tar"),
                                      "r:")
        target_tarball = tarfile.open(os.path.join(temp_dir, "target.tar"),
                                      "w:")

        added = []
        for entry in source_tarball:
            # FIXME: Will need to be done on the real rootfs
            # Skip some files
            if entry.name in ("SWAP.swap", "etc/mtab"):
                continue

            fileptr = None
            if entry.isfile():
                try:
                    fileptr = source_tarball.extractfile(entry.name)
                except KeyError:
                    pass

            # Update hardlinks to point to the right target
            if entry.islnk():
                entry.linkname = "system/%s" % entry.linkname

            entry.name = "system/%s" % entry.name
            target_tarball.addfile(entry, fileobj=fileptr)
            added.append(entry.name)

        # FIXME: Will need to be done on the real rootfs
        # Add some symlinks and directories
        ## /android
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.DIRTYPE
        new_file.name = "system/android"
        new_file.mode = 0o755
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

        ## /userdata
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.DIRTYPE
        new_file.name = "system/userdata"
        new_file.mode = 0o755
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

        ## /etc/mtab
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.SYMTYPE
        new_file.name = "system/etc/mtab"
        new_file.linkname = "/proc/mounts"
        new_file.mode = 0o444
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

        ## Android partitions
        for android_path in ("cache", "data", "factory", "firmware", "persist",
                             "system"):
            new_file = tarfile.TarInfo()
            new_file.type = tarfile.SYMTYPE
            new_file.name = "system/%s" % android_path
            new_file.linkname = "/android/%s" % android_path
            new_file.mode = 0o755
            new_file.mtime = int(time.strftime("%s", time.localtime()))
            new_file.uname = "root"
            new_file.gname = "root"
            target_tarball.addfile(new_file)

        ## /vendor
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.SYMTYPE
        new_file.name = "system/vendor"
        new_file.linkname = "/android/system/vendor"
        new_file.mode = 0o755
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

        ## /lib/modules
        new_file = tarfile.TarInfo()
        new_file.type = tarfile.DIRTYPE
        new_file.name = "system/lib/modules"
        new_file.mode = 0o755
        new_file.mtime = int(time.strftime("%s", time.localtime()))
        new_file.uname = "root"
        new_file.gname = "root"
        target_tarball.addfile(new_file)

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
                                         indent=4, separators=(',', ': ')))
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
            # Grab the current version number
            version = urlopen(options['monitor']).read().strip()

            # Push the result in the cache
            CACHE['http_%s' % url] = version

        # Set version_detail
        version_detail = "%s=%s" % (options.get("name", "http"), version)

        # Build the path
        path = os.path.realpath(os.path.join(conf.publish_path, "pool",
                                             "%s-%s.tar.xz" %
                                             (options.get("name", "http"),
                                              version)))

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
    urlretrieve(url, os.path.join(tempdir, "download"))

    # Hash it if we don't have a version number
    if not version:
        # Hash the file
        with open(os.path.join(tempdir, "download"), "r") as fd:
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
                                     indent=4, separators=(',', ': ')))
    gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

    # Cleanup
    shutil.rmtree(tempdir)

    environment['version_detail'].append(version_detail)
    return path


def generate_file_system_image(conf, arguments, environment):
    """
        Copy a file from another channel.
    """

    # We need at least a channel name and a file prefix
    if len(arguments) < 2:
        return None

    # Read the arguments
    channel_name = arguments[0]
    prefix = arguments[1]

    # FIXME: temporary workaround, remove on the 24th
    prefixes = [prefix]
    if prefix == "device":
        prefixes += ["mako", "grouper", "manta", "maguro"]

    # Run some checks
    pub = tree.Tree(conf)
    if not channel_name in pub.list_channels():
        return None

    if (not environment['device_name'] in
            pub.list_channels()[channel_name]['devices']):
        return None

    # Try to find the file
    device = pub.get_device(channel_name, environment['device_name'])

    full_images = sorted([image for image in device.list_images()
                          if image['type'] == "full"],
                         key=lambda image: image['version'])

    # No images
    if not full_images:
        return None

    # Found an image, so let's try to find a match
    for file_entry in full_images[-1]['files']:
        file_name = file_entry['path'].split("/")[-1]
        file_prefix = file_name.rsplit("-", 1)[0]
        if file_prefix in prefixes:
            path = os.path.realpath("%s/%s" % (conf.publish_path,
                                               file_entry['path']))

            if os.path.exists(path.replace(".tar.xz", ".json")):
                with open(path.replace(".tar.xz", ".json"), "r") as fd:
                    metadata = json.loads(fd.read())

                if "version_detail" in metadata:
                    environment['version_detail'].append(
                        metadata['version_detail'])

            return path

    return None


def generate_file_version(conf, arguments, environment):
    """
        Generate a version tarball or return a pre-existing one.
    """

    # Don't generate version tarballs when nothing changed
    if len(environment['new_files']) == 0:
        return None

    path = os.path.realpath(os.path.join(environment['device'].path,
                            "version-%s.tar.xz" % environment['version']))

    # Set the version_detail string
    environment['version_detail'].append("version=%s" % environment['version'])

    # Don't bother re-generating a file if it already exists
    if os.path.exists(path):
        return path

    # Generate version_detail
    version_detail = ",".join(environment['version_detail'])

    # Create temporary directory
    tempdir = tempfile.mkdtemp()

    # Generate the tarball
    tools.generate_version_tarball(
        conf, environment['channel_name'], str(environment['version']),
        os.path.join(tempdir, "version"), version_detail=version_detail)

    # Create the pool if it doesn't exist
    if not os.path.exists(os.path.join(environment['device'].path)):
        os.makedirs(os.path.join(environment['device'].path))

    # Compress and sign it
    tools.xz_compress(os.path.join(tempdir, "version"), path)
    gpg.sign_file(conf, "image-signing", path)

    # Generate the metadata file
    metadata = {}
    metadata['generator'] = "version"
    metadata['version'] = environment['version']
    metadata['version_detail'] = "version=%s" % environment['version']
    metadata['channel.ini'] = {}
    metadata['channel.ini']['channel'] = environment['channel_name']
    metadata['channel.ini']['version'] = str(environment['version'])
    metadata['channel.ini']['version_detail'] = version_detail

    with open(path.replace(".tar.xz", ".json"), "w+") as fd:
        fd.write("%s\n" % json.dumps(metadata, sort_keys=True,
                                     indent=4, separators=(',', ': ')))
    gpg.sign_file(conf, "image-signing", path.replace(".tar.xz", ".json"))

    # Cleanup
    shutil.rmtree(tempdir)

    return path
