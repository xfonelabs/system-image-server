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

import configparser
import os
import logging


logger = logging.getLogger(__name__)


def parse_config(path):
    config = {}

    configp = configparser.ConfigParser(interpolation=None)
    configp.optionxform = str
    try:
        configp.read(path)
    except configparser.Error as e:
        logger.exception(e)
        logger.error(
            "Failed to parse configuration file, using empty configuration."
            )
        return config

    for section in configp.sections():
        config_section = {}
        for option in configp.options(section):
            value = configp.get(section, option)
            if ", " in value:
                value = [entry.strip("\"").strip()
                         for entry in value.split(", ")]
            else:
                value = value.strip("\"").strip()
            config_section[option] = value
        config[section] = config_section

    return config


class Config:
    def __init__(self, path=None):
        if not path:
            path = "%s/etc/config" % os.environ.get("SYSTEM_IMAGE_ROOT",
                                                    os.getcwd())
            if not os.path.exists(path):
                path = os.path.realpath(os.path.join(os.path.dirname(__file__),
                                                     "../../etc/config"))

        self.load_config(path)

    def load_config(self, path):
        if not os.path.exists(path):
            raise Exception("Configuration file doesn't exist: %s" % path)

        # Read the config
        config = parse_config(path)

        if 'global' not in config:
            config['global'] = {}

        # Set defaults
        self.base_path = config['global'].get(
            "base_path", os.environ.get("SYSTEM_IMAGE_ROOT", os.getcwd()))

        self.gpg_key_path = config['global'].get(
            "gpg_key_path", os.path.join(self.base_path,
                                         "secret", "gpg", "keys"))
        if not self.gpg_key_path.startswith("/"):
            self.gpg_key_path = os.path.join(self.base_path, self.gpg_key_path)

        self.gpg_keyring_path = config['global'].get(
            "gpg_keyring_path", os.path.join(self.base_path,
                                             "secret", "gpg", "keyrings"))
        if not self.gpg_keyring_path.startswith("/"):
            self.gpg_keyring_path = os.path.join(self.base_path,
                                                 self.gpg_keyring_path)

        self.publish_path = config['global'].get(
            "publish_path", os.path.join(self.base_path, "www"))
        if not self.publish_path.startswith("/"):
            self.publish_path = os.path.join(self.base_path, self.publish_path)

        self.state_path = config['global'].get(
            "state_path", os.path.join(self.base_path, "state"))
        if not self.state_path.startswith("/"):
            self.state_path = os.path.join(self.base_path, self.state_path)

        # Export some more keys as-is
        for key in ("public_fqdn", "public_http_port", "public_https_port"):
            if key not in config['global']:
                continue

            setattr(self, key, config['global'][key])

        # Parse the mirror configuration
        self.mirrors = {}
        if "mirrors" in config['global']:
            if not isinstance(config['global']['mirrors'], list):
                config['global']['mirrors'] = [config['global']['mirrors']]

            if len(config['global']['mirrors']) != 0:
                if "mirror_default" not in config:
                    raise KeyError("Missing mirror_default section.")

                for key in ("ssh_user", "ssh_key", "ssh_port", "ssh_command"):
                    if key not in config['mirror_default']:
                        raise KeyError("Missing key in mirror_default: %s" %
                                       key)

                for entry in config['global']['mirrors']:
                    dict_entry = "mirror_%s" % entry
                    if dict_entry not in config:
                        raise KeyError("Missing mirror section: %s" %
                                       dict_entry)

                    mirror = type("Mirror", (object,), {})

                    if "ssh_host" not in config[dict_entry]:
                        raise KeyError("Missing key in %s: ssh_host" %
                                       dict_entry)
                    else:
                        mirror.ssh_host = config[dict_entry]['ssh_host']

                    mirror.ssh_user = config[dict_entry].get(
                        "ssh_user", config['mirror_default']['ssh_user'])
                    mirror.ssh_key = config[dict_entry].get(
                        "ssh_key", config['mirror_default']['ssh_key'])
                    if not mirror.ssh_key.startswith("/"):
                        mirror.ssh_key = os.path.join(self.base_path,
                                                      mirror.ssh_key)
                    mirror.ssh_port = int(config[dict_entry].get(
                        "ssh_port", config['mirror_default']['ssh_port']))
                    mirror.ssh_command = config[dict_entry].get(
                        "ssh_command", config['mirror_default']['ssh_command'])

                    self.mirrors[entry] = mirror

        # Parse the channel configuration
        self.channels = {}
        if "channels" in config['global']:
            if not isinstance(config['global']['channels'], list):
                config['global']['channels'] = \
                    [config['global']['channels']]

            if len(config['global']['channels']) != 0:
                for entry in config['global']['channels']:
                    dict_entry = "channel_%s" % entry
                    if dict_entry not in config:
                        raise KeyError("Missing channel section: %s" %
                                       dict_entry)

                    channel = type("Channel", (object,), {})

                    channel.versionbase = int(config[dict_entry].get(
                        'versionbase', 1))

                    channel.type = config[dict_entry].get(
                        "type", "manual")

                    channel.fullcount = int(config[dict_entry].get(
                        "fullcount", 0))

                    channel.deltabase = [entry]
                    if "deltabase" in config[dict_entry]:
                        if isinstance(config[dict_entry]['deltabase'],
                                      list):
                            channel.deltabase = \
                                config[dict_entry]['deltabase']
                        else:
                            channel.deltabase = \
                                [config[dict_entry]['deltabase']]

                    # Parse the file list
                    files = config[dict_entry].get("files", [])
                    if isinstance(files, str):
                        files = [files]

                    channel.files = []
                    for file_entry in files:
                        if "file_%s" % file_entry not in config[dict_entry]:
                            raise KeyError("Missing file entry: %s" %
                                           "file_%s" % file_entry)

                        fields = (config[dict_entry]
                                  ['file_%s' % file_entry].split(";"))

                        file_dict = {}
                        file_dict['name'] = file_entry
                        file_dict['generator'] = fields[0]
                        file_dict['arguments'] = []
                        if len(fields) > 1:
                            file_dict['arguments'] = fields[1:]

                        channel.files.append(file_dict)

                    self.channels[entry] = channel
