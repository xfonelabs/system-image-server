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

try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser


def parse_config(path):
    config = {}

    configp = ConfigParser()
    try:
        configp.read(path)
    except:
        return config

    for section in configp.sections():
        config_section = {}
        for option in configp.options(section):
            value = configp.get(section, option)
            if "," in value:
                value = [entry.strip('"').strip()
                         for entry in value.split(",")]
            else:
                value = value.strip('"').strip()
            config_section[option] = value
        config[section] = config_section

    return config


class Config:
    def __init__(self, path="etc/config"):
        self.load_config(path)

    def load_config(self, path):
        if not os.path.exists(path):
            raise Exception("Configuration file doesn't exist: %s" % path)

        # Read the config
        config = parse_config(path)

        if not 'global' in config:
            config['global'] = {}

        # Set defaults
        self.base_path = config['global'].get("base_path", os.getcwd())
        self.gpg_key_path = config['global'].get(
            "gpg_key_path", os.path.join(self.base_path,
                                         "secret", "gpg", "keys"))

        self.gpg_keyring_path = config['global'].get(
            "gpg_keyring_path", os.path.join(self.base_path,
                                             "secret", "gpg", "keyrings"))

        self.publish_path = config['global'].get(
            "publish_path", os.path.join(self.base_path, "www"))

        self.mirrors = []
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
                    mirror.ssh_port = int(config[dict_entry].get(
                        "ssh_port", config['mirror_default']['ssh_port']))
                    mirror.ssh_command = config[dict_entry].get(
                        "ssh_command", config['mirror_default']['ssh_command'])

                    self.mirrors.append(mirror)