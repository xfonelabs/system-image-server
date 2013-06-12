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
import os
import re
import shutil
import time

from contextlib import contextmanager
from systemimage import gpg


@contextmanager
def channels_json(path, commit=False):
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
                                             indent=4, separators=(',', ': ')))

            # Move the signature
            gpg.sign_file("signing", new_path)
            if os.path.exists("%s.asc" % path):
                os.remove("%s.asc" % path)
            os.rename("%s.asc" % new_path, "%s.asc" % path)

            # Move the index
            if os.path.exists(path):
                os.remove(path)
            os.rename(new_path, path)


@contextmanager
def index_json(path, commit=False):
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
        if commit and (orig_json_content != json_content or
                       not os.path.exists(path)):
            json_content['global']['generated_at'] = time.strftime(
                "%a %b %d %H:%M:%S UTC %Y", time.gmtime())

            new_path = "%s.new" % path
            with open(new_path, "w+") as fd:
                fd.write("%s\n" % json.dumps(json_content, sort_keys=True,
                                             indent=4, separators=(',', ': ')))

            # Move the signature
            gpg.sign_file("signing", new_path)
            if os.path.exists("%s.asc" % path):
                os.remove("%s.asc" % path)
            os.rename("%s.asc" % new_path, "%s.asc" % path)

            # Move the index
            if os.path.exists(path):
                os.remove(path)
            os.rename(new_path, path)


class Tree:
    def __init__(self, path):
        if not os.path.isdir(path):
            raise Exception("Invalid path: %s" % path)

        self.path = path
        self.indexpath = os.path.join(path, "channels.json")

    def create_channel(self, channel_name):
        """
            Creates a new channel entry in the tree.
        """

        with channels_json(self.indexpath, True) as channels:
            if channel_name in channels:
                raise KeyError("Channel already exists: %s" % channel_name)

            channel_path = os.path.join(self.path, channel_name)
            if not os.path.exists(channel_path):
                os.mkdir(channel_path)
            channels[channel_name] = {}

    def create_device(self, channel_name, device_name, keyring_path=None):
        """
            Creates a new device entry in the tree.
        """

        with channels_json(self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name in channels[channel_name]:
                raise KeyError("Device already exists: %s" % device_name)

            device_path = os.path.join(self.path, channel_name, device_name)
            if not os.path.exists(device_path):
                os.mkdir(device_path)

            # Create an empty index if it doesn't exist, if it does,
            # just validate it
            with index_json(os.path.join(device_path, "index.json"), True):
                pass

            device = {}
            device['index'] = "/%s/%s/index.json" % (channel_name, device_name)

            channels[channel_name][device_name] = device

        if keyring_path:
            self.set_device_keyring(channel_name, device_name, keyring_path)

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
                             and entry not in ('gpg',)]:
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

    def get_device(self, channel_name, device_name):
        """
            Returns a Device instance.
        """

        with channels_json(self.indexpath) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name not in channels[channel_name]:
                raise KeyError("Couldn't find device: %s" % device_name)

            return Device(os.path.join(self.path, channel_name))

    def list_channels(self):
        """
            Returns a dict of all existing channels and devices for each of
            those.
            This is simply a decoded version of channels.json
        """

        with channels_json(self.indexpath) as channels:
            return channels

    def remove_channel(self, channel_name):
        """
            Remove a channel and everything it contains.
        """

        with channels_json(self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            channel_path = os.path.join(self.path, channel_name)
            if os.path.exists(channel_path):
                shutil.rmtree(channel_path)
            channels.pop(channel_name)

    def remove_device(self, channel_name, device_name):
        """
            Remove a device and everything it contains.
        """

        with channels_json(self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name not in channels[channel_name]:
                raise KeyError("Couldn't find device: %s" % device_name)

            device_path = os.path.join(self.path, channel_name, device_name)
            if os.path.exists(device_path):
                shutil.rmtree(device_path)
            channels[channel_name].pop(device_name)

    def set_device_keyring(self, channel_name, device_name, path):
        """
            Update the keyring entry for the given channel and device.
            Passing None as the path will unset any existing value.
        """

        with channels_json(self.indexpath, True) as channels:
            if channel_name not in channels:
                raise KeyError("Couldn't find channel: %s" % channel_name)

            if device_name not in channels[channel_name]:
                raise KeyError("Couldn't find device: %s" % device_name)

            if path.startswith(self.path):
                path = re.sub('^%s' % re.escape(self.path), "", path)

            if path.startswith(os.sep):
                relpath = path[1:]
            else:
                relpath = path

            abspath = os.path.join(self.path, relpath)

            if not os.path.exists(abspath):
                raise Exception("Specified GPG keyring doesn't exists: %s" %
                                abspath)

            if not os.path.exists("%s.asc" % abspath):
                raise Exception("The GPG keyring signature doesn't exists: "
                                "%s.asc" % abspath)

            keyring = {}
            keyring['path'] = "/%s" % "/".join(relpath.split(os.sep))
            keyring['signature'] = "/%s.asc" % "/".join(relpath.split(os.sep))

            channels[channel_name][device_name]['keyring'] = keyring


class Device:
    def __init__(self, path):
        self.path = path

    def publish_image(self, entry_type, version, description,
                      base=None, bootme=False, minversion=None,
                      *paths):
        pass