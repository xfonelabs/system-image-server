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

import copy
import json
import logging
import os
import shutil
import time
from contextlib import contextmanager
from hashlib import sha256

from systemimage import gpg, tools

logger = logging.getLogger(__name__)


# Context managers
@contextmanager
def channels_json(config, path, commit=False):
    """
        Context function (to be used with "with") that will open a
        channels.json file, parse it, validate it and return the
        decoded version.

        If commit is True, the file will then be updated (or created) on
        exit.
    """

    # If the file doesn't exist, just yield an empty dict
    json_content = {}
    if os.path.exists(path):
        with open(path, "r") as fd:
            content = fd.read()
            if content:
                json_content = json.loads(content)

    # Validation
    if not isinstance(json_content, dict):
        raise TypeError("Invalid channels.json, not a dict.")

    if commit:
        orig_json_content = copy.deepcopy(json_content)

    # Yield the decoded value and save on exit
    try:
        yield json_content
    finally:
        if commit and (orig_json_content != json_content or
                       not os.path.exists(path)):
            new_path = "%s.new" % path
            with open(new_path, "w+") as fd:
                fd.write("%s\n" % json.dumps(json_content, sort_keys=True,
                                             indent=4, separators=(",", ": ")))

            # Move the signature
            gpg.sign_file(config, "image-signing", new_path)
            if os.path.exists("%s.asc" % path):
                os.remove("%s.asc" % path)
            os.rename("%s.asc" % new_path, "%s.asc" % path)

            # Move the index
            if os.path.exists(path):
                os.remove(path)
            os.rename(new_path, path)


@contextmanager
def index_json(config, path, commit=False):
    """
        Context function (to be used with "with") that will open an
        index.json file, parse it, validate it and return the
        decoded version.

        If commit is True, the file will then be updated (or created) on
        exit.
    """

    # If the file doesn't exist, just yield an empty dict
    json_content = {}
    json_content['global'] = {}
    json_content['images'] = []

    if os.path.exists(path):
        with open(path, "r") as fd:
            content = fd.read()
            if content:
                json_content = json.loads(content)

    # Validation
    if not isinstance(json_content, dict):
        raise TypeError("Invalid index.json, not a dict.")

    if commit:
        orig_json_content = copy.deepcopy(json_content)

    # Yield the decoded value and save on exit
    try:
        yield json_content
    finally:
        # Remove any invalid attribute
        versions = sorted({image['version']
                           for image in json_content['images']})
        if versions:
            last_version = versions[-1]

            # Remove phased-percentage from any old image
            for image in json_content['images']:
                if image['version'] != last_version and \
                        "phased-percentage" in image:
                    image.pop("phased-percentage")

        # Save to disk
        if commit and (orig_json_content != json_content or
                       not os.path.exists(path)):
            json_content['global']['generated_at'] = time.strftime(
                "%a %b %d %H:%M:%S UTC %Y", time.gmtime())

            new_path = "%s.new" % path
            with open(new_path, "w+") as fd:
                fd.write("%s\n" % json.dumps(json_content, sort_keys=True,
                                             indent=4, separators=(",", ": ")))

            # Move the signature
            gpg.sign_file(config, "image-signing", new_path)
            if os.path.exists("%s.asc" % path):
                os.remove("%s.asc" % path)
            os.rename("%s.asc" % new_path, "%s.asc" % path)

            # Move the index
            if os.path.exists(path):
                os.remove(path)
            os.rename(new_path, path)


class Tree:
    def __init__(self, config, path=None):
        if not path:
            path = config.publish_path

        if not os.path.isdir(path):
            raise Exception("Invalid path: %s" % path)

        self.config = config
        self.path = path
        self.indexpath = os.path.join(path, "channels.json")

    def __list_existing(self):
        """
            Returns a set of all files present in the tree and a set of
            empty directories that can be removed.
        """

        existing_files = set()
        empty_dirs = set()

        for dirpath, dirnames, filenames in os.walk(self.path):
            if dirpath == os.path.join(self.path, "gpg"):
                continue

            if not filenames and not dirnames:
                empty_dirs.add(dirpath)

            for entry in filenames:
                existing_files.add(os.path.join(dirpath, entry))

        return (existing_files, empty_dirs)

    def __list_referenced(self):
        """
            Returns a set of all files that are referenced by the
            various indexes and should be present in the tree.
        """

        listed_files = set()
        listed_files.add(os.path.join(self.path, "channels.json"))
        listed_files.add(os.path.join(self.path, "channels.json.asc"))

        for channel, metadata in self.list_channels().items():
            devices = metadata['devices']
            for device in devices:
                if 'keyring' in devices[device]:
                    listed_files.add(os.path.join(
                        self.path, devices[device]['keyring']['path'][1:]))
                    listed_files.add(os.path.join(
                        self.path,
                        devices[device]['keyring']['signature'][1:]))

                device_entry = self.get_device(channel, device)

                listed_files.add(os.path.join(device_entry.path, "index.json"))
                listed_files.add(os.path.join(device_entry.path,
                                              "index.json.asc"))

                for image in device_entry.list_images():
                    for entry in image['files']:
                        listed_files.add(os.path.join(self.path,
                                                      entry['path'][1:]))
                        listed_files.add(os.path.join(self.path,
                                                      entry['signature'][1:]))

        return listed_files

    def change_channel_alias(self, channel_name, target_name):
        """
            Change the target of an alias.
        """

        with channels_json(self.config, self.indexpath) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if "redirect" in channels[channel_name]:
                raise KeyError("Channel is a redirect: %s" % channel_name)

            if "alias" not in channels[channel_name] or \
                    channels[channel_name]['alias'] == channel_name:
                raise KeyError("Channel isn't an alias: %s" % channel_name)

            if target_name not in channels:
                raise KeyError("Couldn't find target channel: %s" %
                               target_name)

        self.remove_channel(channel_name)
        self.create_channel_alias(channel_name, target_name)

        return True

    def cleanup_tree(self):
        """
            Remove any orphaned file from the tree.
        """

        orphaned_files = self.list_orphaned_files()
        for entry in orphaned_files:

            if os.path.isdir(entry):
                os.rmdir(entry)
            else:
                os.remove(entry)

        return True

    def create_channel(self, channel_name):
        """
            Creates a new channel entry in the tree.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name in channels:
                raise KeyError("Channel already exists: %s" % channel_name)

            channels[channel_name] = {'devices': {}}

        return True

    def create_channel_alias(self, channel_name, target_name):
        """
            Creates a new channel as an alias for an existing one.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name in channels:
                raise KeyError("Channel already exists: %s" % channel_name)

            if target_name not in channels:
                raise KeyError("Couldn't find target channel: %s" %
                               target_name)

            channels[channel_name] = {'devices': {},
                                      'alias': target_name}

        return self.sync_alias(channel_name)

    def create_channel_redirect(self, channel_name, target_name):
        """
            Creates a new channel redirect.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name in channels:
                raise KeyError("Channel already exists: %s" % channel_name)

            if target_name not in channels:
                raise KeyError("Couldn't find target channel: %s" %
                               target_name)

            channels[channel_name] = dict(channels[target_name])
            channels[channel_name]['redirect'] = target_name

        self.hide_channel(channel_name)

        return True

    def create_per_device_channel_redirect(self, device_name, channel_name,
                                           target_name):
        """
            Creates a device-specific channel redirect, redirecting that device
            to point to a different channel.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name in channels[channel_name]['devices']:
                raise KeyError("Device already exists: %s" % device_name)

            if target_name not in channels:
                raise KeyError("Couldn't find target channel: %s" %
                               target_name)

            if device_name not in channels[target_name]['devices']:
                raise KeyError("Couldn't find device on target channel: "
                               "%s, %s" %
                               (target_name, device_name))

            channels[channel_name]['devices'][device_name] = \
                dict(channels[target_name]['devices'][device_name])

            channels[channel_name]['devices'][device_name]['redirect'] = \
                target_name

        return True

    def create_device(self, channel_name, device_name, keyring_path=None):
        """
            Creates a new device entry in the tree.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name in channels[channel_name]['devices']:
                raise KeyError("Device already exists: %s" % device_name)

            device_path = os.path.join(self.path, channel_name, device_name)
            if not os.path.exists(device_path):
                os.makedirs(device_path)

            # Create an empty index if it doesn't exist, if it does,
            # just validate it
            with index_json(self.config, os.path.join(device_path,
                                                      "index.json"), True):
                pass

            device = {}
            device['index'] = "/%s/%s/index.json" % (channel_name, device_name)

            channels[channel_name]['devices'][device_name] = device

        if keyring_path:
            self.set_device_keyring(channel_name, device_name, keyring_path)

        self.sync_aliases(channel_name)
        self.sync_redirects(channel_name)

        return True

    def generate_index(self, magic=False):
        """
            Re-generate the channels.json file based on the current content of
            the tree.

            This function is only present for emergency purposes and will
            completely rebuild the tree based on what's on the filesystem,
            looking into some well known locations to guess things like device
            keyring paths.

            Call this function with confirm="I know what I'm doing" to actually
            trigger it.
        """

        if magic != "I know what I'm doing":
            raise Exception("Invalid magic value, please read the help.")

        if os.path.exists(self.indexpath):
            os.remove(self.indexpath)

        for channel_name in [entry for entry in os.listdir(self.path)
                             if os.path.isdir(os.path.join(self.path,
                                                           entry))
                             and entry not in ("gpg",)]:
            self.create_channel(channel_name)

            for device_name in os.listdir(os.path.join(self.path,
                                                       channel_name)):

                path = os.path.join(self.path, channel_name, device_name)
                if not os.path.exists(os.path.join(path, "index.json")):
                    continue

                keyring_path = os.path.join(path, "device.tar.xz")
                if (os.path.exists(keyring_path)
                        and os.path.exists("%s.asc" % keyring_path)):
                    self.create_device(channel_name, device_name, keyring_path)
                else:
                    self.create_device(channel_name, device_name)

        return True

    def get_device(self, channel_name, device_name):
        """
            Returns a Device instance.
        """

        with channels_json(self.config, self.indexpath) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name not in channels[channel_name]['devices']:
                raise KeyError("Couldn't find device: %s" % device_name)

            device_path = os.path.dirname(channels[channel_name]['devices']
                                          [device_name]['index'])

            return Device(self.config, os.path.normpath("%s/%s" % (self.path,
                          device_path)))

    def hide_channel(self, channel_name):
        """
            Hide a channel from the client's list.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            channels[channel_name]['hidden'] = True

        return True

    def list_channels(self):
        """
            Returns a dict of all existing channels and devices for each of
            those.
            This is simply a decoded version of channels.json
        """

        with channels_json(self.config, self.indexpath) as channels:
            return channels

    def list_devices(self, channel_name):
        """
            Returns the list of device names for the channel.
        """

        with channels_json(self.config, self.indexpath) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            return list(channels[channel_name]['devices'].keys())

    def list_missing_files(self):
        """
            Returns a list of absolute paths that should exist but aren't
            present on the filesystem.
        """

        all_files, empty_dirs = self.__list_existing()
        referenced_files = self.__list_referenced()

        return sorted(referenced_files - all_files)

    def list_orphaned_files(self):
        """
            Returns a list of absolute paths to files that are present in the
            tree but aren't referenced anywhere.
        """

        orphaned_files = set()

        all_files, empty_dirs = self.__list_existing()
        referenced_files = self.__list_referenced()

        orphaned_files.update(all_files - referenced_files)
        orphaned_files.update(empty_dirs)

        for entry in list(orphaned_files):
            if entry.endswith(".json"):
                tarname = entry.replace(".json", ".tar.xz")
                if tarname in referenced_files:
                    orphaned_files.remove(entry)

            if entry.endswith(".json.asc"):
                tarname = entry.replace(".json.asc", ".tar.xz")
                if tarname in referenced_files:
                    orphaned_files.remove(entry)

        logger.debug("Orphaned files: %s" % orphaned_files)
        return sorted(orphaned_files)

    def publish_keyring(self, keyring_name):
        """
            Publish the keyring under gpg/
        """

        gpg_path = os.path.join(self.config.publish_path, "gpg")

        if not os.path.exists(gpg_path):
            os.mkdir(gpg_path)

        keyring_path = os.path.join(self.config.gpg_keyring_path, keyring_name)

        if not os.path.exists("%s.tar.xz" % keyring_path):
            raise Exception("Missing keyring: %s.tar.xz" % keyring_path)

        if not os.path.exists("%s.tar.xz.asc" % keyring_path):
            raise Exception("Missing keyring signature: %s.tar.xz.asc" %
                            keyring_path)

        shutil.copy("%s.tar.xz" % keyring_path, gpg_path)
        shutil.copy("%s.tar.xz.asc" % keyring_path, gpg_path)

        return True

    def remove_channel(self, channel_name):
        """
            Remove a channel and everything it contains.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            channel_path = os.path.join(self.path, channel_name)
            if os.path.exists(channel_path) and \
               "alias" not in channels[channel_name] and \
               "redirect" not in channels[channel_name]:
                shutil.rmtree(channel_path)
            channels.pop(channel_name)

        # Remove all redirect device channels pointing at this channel
        self.cleanup_device_redirects(channel_name)

        return True

    def remove_device(self, channel_name, device_name):
        """
            Remove a device and everything it contains.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name not in channels[channel_name]['devices']:
                raise KeyError("Couldn't find device: %s" % device_name)

            # Do not remove the device files for per-device redirects
            device = channels[channel_name]['devices'][device_name]
            if "redirect" not in device:
                device_path = os.path.join(
                    self.path, channel_name, device_name)
                if os.path.exists(device_path):
                    shutil.rmtree(device_path)
            channels[channel_name]['devices'].pop(device_name)

        self.sync_aliases(channel_name)
        self.sync_redirects(channel_name)

        # Remove all redirect channels pointing at this device
        self.cleanup_device_redirects(channel_name, device_name)

        return True

    def rename_channel(self, old_name, new_name):
        """
            Rename a channel.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if old_name not in channels:
                raise KeyError("Couldn't find channel: %s" % old_name)

            if new_name in channels:
                raise KeyError("Channel already exists: %s" % new_name)

            old_channel_path = os.path.join(self.path, old_name)
            new_channel_path = os.path.join(self.path, new_name)
            if "redirect" not in channels[old_name]:
                if os.path.exists(new_channel_path):
                    raise Exception("Channel path already exists: %s" %
                                    new_channel_path)

                if not os.path.exists(os.path.dirname(new_channel_path)):
                    os.makedirs(os.path.dirname(new_channel_path))
                if os.path.exists(old_channel_path):
                    os.rename(old_channel_path, new_channel_path)

            channels[new_name] = dict(channels[old_name])

            if "redirect" not in channels[new_name]:
                for device_name in channels[new_name]['devices']:
                    index_path = "/%s/%s/index.json" % (new_name, device_name)
                    channels[new_name]['devices'][device_name]['index'] = \
                        index_path

                    with index_json(self.config, "%s/%s" %
                                    (self.path, index_path), True) as index:
                        for image in index['images']:
                            for entry in image['files']:
                                entry['path'] = entry['path'] \
                                    .replace("/%s/" % old_name,
                                             "/%s/" % new_name)
                                entry['signature'] = entry['signature'] \
                                    .replace("/%s/" % old_name,
                                             "/%s/" % new_name)

            # Handle any device-specific channel redirects
            for channel_name, channel in channels.items():
                for device_name, device in channel['devices'].items():
                    if "redirect" in device and device['redirect'] == old_name:
                        index_path = "/%s/%s/index.json" % (new_name,
                                                            device_name)
                        device['redirect'] = new_name
                        device['index'] = index_path

            channels.pop(old_name)

        return True

    def show_channel(self, channel_name):
        """
            Show a channel from the client's list.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if "hidden" in channels[channel_name]:
                channels[channel_name].pop("hidden")

        return True

    def set_device_keyring(self, channel_name, device_name, path):
        """
            Update the keyring entry for the given channel and device.
            Passing None as the path will unset any existing value.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name not in channels[channel_name]['devices']:
                raise KeyError("Couldn't find device: %s" % device_name)

            abspath, relpath = tools.expand_path(path, self.path)

            if not os.path.exists(abspath):
                raise Exception("Specified GPG keyring doesn't exists: %s" %
                                abspath)

            if not os.path.exists("%s.asc" % abspath):
                raise Exception("The GPG keyring signature doesn't exists: "
                                "%s.asc" % abspath)

            keyring = {}
            keyring['path'] = "/%s" % "/".join(relpath.split(os.sep))
            keyring['signature'] = "/%s.asc" % "/".join(relpath.split(os.sep))

            channels[channel_name]['devices'][device_name]['keyring'] = keyring

        return True

    def sync_alias(self, channel_name):
        """
            Update a channel with data from its parent.
        """

        with channels_json(self.config, self.indexpath) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if "alias" not in channels[channel_name] or \
                    channels[channel_name]['alias'] == channel_name:
                raise TypeError("Not a channel alias")

            target_name = channels[channel_name]['alias']

            if target_name not in channels:
                raise KeyError("Couldn't find target channel: %s" %
                               target_name)

            # Start by looking for added/removed devices
            devices = set(channels[channel_name]['devices'].keys())
            target_devices = set(channels[target_name]['devices'].keys())

            # # Remove any removed device
            for device in devices - target_devices:
                self.remove_device(channel_name, device)

            # # Add any missing device
            for device in target_devices - devices:
                self.create_device(channel_name, device)

            # Iterate through all the devices to import builds
            for device_name in target_devices:
                device = self.get_device(channel_name, device_name)
                target_device = self.get_device(target_name, device_name)

                # Extract all the current builds
                device_images = {(image['version'], image.get("base", -1),
                                  image['type'])
                                 for image in device.list_images()}

                target_images = {(image['version'], image.get("base", -1),
                                  image['type'])
                                 for image in target_device.list_images()}

                # Remove any removed image
                for image in device_images - target_images:
                    device.remove_image(image[2], image[0], base=image[1])

                # Create the path if it doesn't exist
                if not os.path.exists(device.path):
                    os.makedirs(device.path)

                # Add any missing image
                with index_json(self.config, device.indexpath, True) as index:
                    for image in sorted(target_images - device_images):
                        orig = [entry for entry in target_device.list_images()
                                if entry['type'] == image[2] and
                                entry['version'] == image[0] and
                                entry.get("base", -1) == image[1]]

                        entry = copy.deepcopy(orig[0])

                        # Remove the current version tarball
                        version_detail = None
                        version_index = len(entry['files'])
                        for fentry in entry['files']:
                            if fentry['path'].endswith("version-%s.tar.xz" %
                                                       entry['version']):

                                version_path = "%s/%s" % (
                                    self.config.publish_path, fentry['path'])

                                if os.path.exists(
                                        version_path.replace(".tar.xz",
                                                             ".json")):
                                    with open(
                                            version_path.replace(
                                                ".tar.xz", ".json")) as fd:
                                        metadata = json.loads(fd.read())
                                        if "channel.ini" in metadata:
                                            version_detail = \
                                                metadata['channel.ini'].get(
                                                    "version_detail", None)

                                version_index = fentry['order']
                                entry['files'].remove(fentry)
                                break

                        # Generate a new one
                        path = os.path.join(device.path,
                                            "version-%s.tar.xz" %
                                            entry['version'])
                        abspath, relpath = tools.expand_path(path,
                                                             device.pub_path)
                        if not os.path.exists(abspath):
                            tools.generate_version_tarball(
                                self.config, channel_name, device_name,
                                str(entry['version']),
                                abspath.replace(".xz", ""),
                                version_detail=version_detail,
                                channel_target=target_name)
                            tools.xz_compress(abspath.replace(".xz", ""))
                            os.remove(abspath.replace(".xz", ""))
                            gpg.sign_file(self.config, "image-signing",
                                          abspath)

                        with open(abspath, "rb") as fd:
                            checksum = sha256(fd.read()).hexdigest()

                        # Generate the new file entry
                        version = {}
                        version['order'] = version_index
                        version['path'] = "/%s" % "/".join(
                            relpath.split(os.sep))
                        version['signature'] = "/%s.asc" % "/".join(
                            relpath.split(os.sep))
                        version['checksum'] = checksum
                        version['size'] = int(os.stat(abspath).st_size)

                        # And add it
                        entry['files'].append(version)
                        index['images'].append(entry)

                # Sync phased-percentage
                versions = sorted({entry[0] for entry in target_images})
                if versions:
                    device.set_phased_percentage(
                        versions[-1],
                        target_device.get_phased_percentage(versions[-1]))

        return True

    def sync_aliases(self, channel_name):
        """
            Update any channel that's an alias of the current one.
        """

        with channels_json(self.config, self.indexpath) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

        alias_channels = [name
                          for name, channel
                          in self.list_channels().items()
                          if channel.get("alias", None) == channel_name
                          and channel.get("redirect", None) is None
                          and name != channel_name]

        for alias_name in alias_channels:
            self.sync_alias(alias_name)

        return True

    def sync_redirects(self, channel_name):
        """
            Update any channel that's a direct of the current one.
        """

        with channels_json(self.config, self.indexpath) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

        redirect_channels = [name
                             for name, channel
                             in self.list_channels().items()
                             if channel.get("redirect", None) == channel_name]

        for redirect_name in redirect_channels:
            self.remove_channel(redirect_name)
            self.create_channel_redirect(redirect_name, channel_name)

        return True

    def cleanup_device_redirects(self, channel_name,
                                 redirect_device_name=None):
        """
            Cleanup any dangling device-specific channel redirects.
        """

        with channels_json(self.config, self.indexpath, True) as channels:
            for target_name, channel in channels.items():
                devices = dict(channel['devices'])
                for device_name, device in devices.items():
                    if ("redirect" in device and
                        device['redirect'] == channel_name and
                        (not redirect_device_name or
                         redirect_device_name == device_name)):
                        channels[target_name]['devices'].pop(device_name)

        return True


class Device:
    def __init__(self, config, path):
        self.config = config
        self.pub_path = self.config.publish_path
        self.path = path
        self.indexpath = os.path.join(path, "index.json")

    def create_image(self, entry_type, version, description, paths,
                     base=None, bootme=False, minversion=None,
                     version_detail=None):
        """
            Add a new image to the index.
        """

        if len(paths) == 0:
            raise Exception("No file passed for this image.")

        files = []
        count = 0

        with index_json(self.config, self.indexpath, True) as index:
            for path in paths:
                abspath, relpath = tools.expand_path(path, self.pub_path)

                if not os.path.exists(abspath):
                    raise Exception("Specified file doesn't exists: %s"
                                    % abspath)

                if not os.path.exists("%s.asc" % abspath):
                    raise Exception("The GPG file signature doesn't exists: "
                                    "%s.asc" % abspath)

                with open(abspath, "rb") as fd:
                    checksum = sha256(fd.read()).hexdigest()

                files.append({'order': count,
                              'path': "/%s" % "/".join(relpath.split(os.sep)),
                              'checksum': checksum,
                              'signature': "/%s.asc" % "/".join(
                                  relpath.split(os.sep)),
                              'size': int(os.stat(abspath).st_size)})

                count += 1

            image = {}

            if entry_type == "delta":
                if not base:
                    raise KeyError("Missing base version for delta image.")
                image['base'] = int(base)
            elif base:
                raise KeyError("Base version set for full image.")

            if bootme:
                image['bootme'] = bootme

            if minversion:
                if entry_type == "delta":
                    raise KeyError("Minimum version set for delta image.")
                image['minversion'] = minversion

            if version_detail:
                image['version_detail'] = version_detail

            image['description'] = description
            image['files'] = files
            image['type'] = entry_type
            image['version'] = version
            index['images'].append(image)

        return True

    def expire_images(self, max_images):
        """
            Expire images keeping the last <max_images> full images and
            their deltas. Also remove any delta that has an expired image
            as its base.
        """

        full_images = sorted([image for image in self.list_images()
                              if image['type'] == "full"],
                             key=lambda image: image['version'])

        to_remove = len(full_images) - max_images
        if to_remove <= 0:
            return True

        full_remove = full_images[:to_remove]
        remove_version = [image['version'] for image in full_remove]

        for image in self.list_images():
            if image['type'] == "full":
                if image['version'] in remove_version:
                    self.remove_image(image['type'], image['version'])
            else:
                if (image['version'] in remove_version
                        or image['base'] in remove_version):
                    self.remove_image(image['type'], image['version'],
                                      image['base'])

        return True

    def get_image(self, entry_type, version, base=None):
        """
            Look for an image and return a dict representation of it.
        """

        if entry_type not in ("full", "delta"):
            raise ValueError("Invalid image type: %s" % entry_type)

        if entry_type == "delta" and not base:
            raise ValueError("Missing base version for delta image.")

        with index_json(self.config, self.indexpath) as index:
            match = []
            for image in index['images']:
                if (image['type'] == entry_type
                        and image['version'] == version
                        and (image['type'] == "full"
                             or image['base'] == base)):
                    match.append(image)

            if len(match) != 1:
                raise IndexError("Couldn't find a match.")

            return match[0]

    def get_phased_percentage(self, version):
        """
            Returns the phasing percentage for a given version.
        """

        for entry in self.list_images():
            if entry['version'] == version:
                if "phased-percentage" in entry:
                    return entry['phased-percentage']
                else:
                    return 100
        else:
            raise IndexError("Invalid version number: %s" % version)

    def list_images(self):
        """
            Returns a list of all existing images, each image is a dict.
            This is simply a decoded version of the image array in index.json
        """

        with index_json(self.config, self.indexpath) as index:
            return index['images']

    def remove_image(self, entry_type, version, base=None):
        """
            Remove an image.
        """

        image = self.get_image(entry_type, version, base)
        with index_json(self.config, self.indexpath, True) as index:
            index['images'].remove(image)

        return True

    def set_description(self, entry_type, version, description,
                        translations={}, base=None):
        """
            Set or update an image description.
        """

        if translations and not isinstance(translations, dict):
            raise TypeError("translations must be a dict.")

        image = self.get_image(entry_type, version, base)

        with index_json(self.config, self.indexpath, True) as index:
            for entry in index['images']:
                if entry != image:
                    continue

                entry['description'] = description
                for langid, value in translations.items():
                    entry['description_%s' % langid] = value

                break

        return True

    def set_phased_percentage(self, version, percentage):
        """
            Set the phasing percentage on an image version.
        """

        if not isinstance(percentage, int):
            raise TypeError("percentage must be an integer.")

        if percentage < 0 or percentage > 100:
            raise ValueError("percentage must be >= 0 and <= 100.")

        with index_json(self.config, self.indexpath, True) as index:
            versions = sorted({entry['version'] for entry in index['images']})

            last_version = None
            if versions:
                last_version = versions[-1]

            if version not in versions:
                raise IndexError("Version doesn't exist: %s" % version)

            if version != last_version:
                raise Exception("Phased percentage can only be set on the "
                                "latest image")

            for entry in index['images']:
                if entry['version'] == version:
                    if percentage == 100 and "phased-percentage" in entry:
                        entry.pop("phased-percentage")
                    elif percentage != 100:
                        entry['phased-percentage'] = percentage

        return True
