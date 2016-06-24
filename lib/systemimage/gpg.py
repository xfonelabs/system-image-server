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
import gpgme
import logging
import os
import tarfile

from io import BytesIO

logger = logging.getLogger(__name__)


def generate_signing_key(keyring_path, key_name, key_email, key_expiry):
    """
        Generate a new 2048bit RSA signing key.
    """

    if not os.path.isdir(keyring_path):
        raise Exception("Keyring path doesn't exist: %s" % keyring_path)

    key_params = """<GnupgKeyParms format="internal">
Key-Type: RSA
Key-Length: 2048
Key-Usage: sign
Name-Real: %s
Name-Email: %s
Expire-Date: %s
</GnupgKeyParms>
""" % (key_name, key_email, key_expiry)

    os.environ['GNUPGHOME'] = keyring_path

    ctx = gpgme.Context()
    result = ctx.genkey(key_params)
    key = ctx.get_key(result.fpr, True)
    [uid] = key.uids

    return uid


def sign_file(config, key, path, destination=None, detach=True, armor=True):
    """
        Sign a file and publish the signature.
        The key parameter must be a valid key under config.gpg_key_path.
        The path must be that of a valid file.
        The destination defaults to <path>.gpg (non-armored) or
        <path>.asc (armored).
        The detach and armor parameters respectively control the use of
        detached signatures and base64 armoring.
    """

    key_path = "%s/%s" % (config.gpg_key_path, key)

    if not os.path.isdir(key_path):
        raise IndexError("Invalid GPG key name '%s'." % key)

    if not os.path.isfile(path):
        raise Exception("Invalid path '%s'." % path)

    if not destination:
        if armor:
            destination = "%s.asc" % path
        elif detach:
            destination = "%s.sig" % path
        else:
            destination = "%s.gpg" % path

    if os.path.exists(destination):
        raise Exception("Destination already exists: %s" % destination)

    os.environ['GNUPGHOME'] = key_path

    # Create a GPG context, assuming no passphrase
    ctx = gpgme.Context()
    ctx.armor = armor
    # XXX: This is a temporary workaround until the key situation is explained
    key = [gpg_key for gpg_key in ctx.keylist()][0]
    ctx.signers = [key]

    logger.debug("Signing file: %s" % destination)

    with open(path, "rb") as fd_in, open(destination, "wb+") as fd_out:
        if detach:
            retval = ctx.sign(fd_in, fd_out, gpgme.SIG_MODE_DETACH)
        else:
            retval = ctx.sign(fd_in, fd_out, gpgme.SIG_MODE_NORMAL)

    return retval


class Keyring:
    """
        Represents a keyring, let's you list/add/remove keys and change
        some of the keyring properties (type, expiration, target hardware)
    """

    keyring_name = None
    keyring_type = None
    keyring_expiry = None
    keyring_model = None
    keyring_path = None

    def __init__(self, config, keyring_name):
        keyring_path = "%s/%s" % (config.gpg_keyring_path, keyring_name)

        if not os.path.isdir(keyring_path):
            os.makedirs(keyring_path)

        self.keyring_name = keyring_name
        self.keyring_path = keyring_path

        if os.path.exists("%s/keyring.json" % keyring_path):
            with open("%s/keyring.json" % keyring_path, "r") as fd:
                keyring_json = json.loads(fd.read())

            self.keyring_type = keyring_json.get("type", None)
            self.keyring_expiry = keyring_json.get("expiry", None)
            self.keyring_model = keyring_json.get("model", None)
        else:
            open("%s/pubring.gpg" % keyring_path, "w+").close()

    def generate_tarball(self, destination=None):
        """
            Generate a tarball of the keyring and its json metadata.
            Returns the path to the tarball.
        """

        if not destination:
            destination = "%s.tar" % self.keyring_path

        if os.path.isfile(destination):
            os.remove(destination)

        tarball = tarfile.open(destination, "w:")
        tarball.add("%s/keyring.json" % self.keyring_path,
                    arcname="keyring.json")
        tarball.add("%s/pubring.gpg" % self.keyring_path,
                    arcname="keyring.gpg")
        tarball.close()

        return destination

    def set_metadata(self, keyring_type, keyring_expiry=None,
                     keyring_model=None):
        """
            Generate a new keyring.json file.
        """

        keyring_json = {}
        if keyring_type:
            self.keyring_type = keyring_type
            keyring_json['type'] = keyring_type

        if keyring_expiry:
            self.keyring_expiry = keyring_expiry
            keyring_json['expiry'] = keyring_expiry

        if keyring_model:
            self.keyring_model = keyring_model
            keyring_json['model'] = keyring_model

        with open("%s/keyring.json" % self.keyring_path, "w+") as fd:
            fd.write("%s\n" % json.dumps(keyring_json, sort_keys=True,
                                         indent=4, separators=(",", ": ")))

    def list_keys(self):
        os.environ['GNUPGHOME'] = self.keyring_path

        keys = []

        ctx = gpgme.Context()
        for key in ctx.keylist():
            keys.append((key.subkeys[0].keyid, key.subkeys[0].length,
                        [uid.uid for uid in key.uids]))

        return keys

    def export_key(self, path, key, armor=True):
        os.environ['GNUPGHOME'] = self.keyring_path

        ctx = gpgme.Context()
        ctx.armor = armor

        gpg_key = ctx.get_key(key)

        with open(path, "wb+") as fd:
            for subkey in gpg_key.subkeys:
                ctx.export(str(subkey.keyid), fd)

    def import_key(self, path, armor=True):
        os.environ['GNUPGHOME'] = self.keyring_path

        ctx = gpgme.Context()
        ctx.armor = armor

        with open(path, "rb") as fd:
            ctx.import_(fd)

    def import_keys(self, path):
        """
            Import all the keys from the specified keyring.
        """

        os.environ['GNUPGHOME'] = path

        ctx = gpgme.Context()

        keys = []
        for key in list(ctx.keylist()):
            for subkey in key.subkeys:
                content = BytesIO()
                ctx.export(str(subkey.keyid), content)
                keys.append(content)

        os.environ['GNUPGHOME'] = self.keyring_path
        ctx = gpgme.Context()

        for key in keys:
            key.seek(0)
            ctx.import_(key)

    def del_key(self, key):
        os.environ['GNUPGHOME'] = self.keyring_path

        ctx = gpgme.Context()

        gpg_key = ctx.get_key(key)

        ctx.delete(gpg_key)
