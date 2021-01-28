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
import tarfile
from io import BytesIO

import gpg

logger = logging.getLogger(__name__)


def generate_signing_key(keyring_path, key_name, key_email, key_validity,
                         algorithm="rsa2048"):
    """
        Generate a new RSA signing key.

        keyring_path is the GNUPGHOME of the target keyring.
        key_name is the name part of the UID for the new key.
        key_email is the email of the UID for the new key.
        key_validity is a datetime.timedelta value for the time the key
        will remain valid for.
        algorithm is the key generation algorithm to use. You probably
        shouldn't use less than rsa2048, but using rsa4096 will make
        signing operations slower.
    """

    if not os.path.isdir(keyring_path):
        raise Exception("Keyring path doesn't exist: %s" % keyring_path)

    user_id = "{} <{}>".format(key_name, key_email)

    if key_validity.total_seconds() > 0:
        expires = True
    else:
        expires = False

    with gpg.Context(home_dir=keyring_path) as ctx:
        result = ctx.create_key(user_id, algorithm=algorithm,
                                expires_in=int(key_validity.total_seconds()),
                                expires=expires, sign=True)
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

    with gpg.Context(armor=armor, home_dir=key_path) as ctx:
        key = [gpg_key for gpg_key in ctx.keylist()][0]
        ctx.signers = [key]

        logger.debug("Signing file: %s" % destination)

        with open(path, "rb") as fd_in, open(destination, "wb+") as fd_out:
            if detach:
                retval = ctx.sign(fd_in, fd_out, gpg.constants.sig.mode.DETACH)
            else:
                retval = ctx.sign(fd_in, fd_out, gpg.constants.sig.mode.NORMAL)

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
            os.makedirs(keyring_path, mode=0o700)

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

        tarball = tarfile.open(destination, "w:", format=tarfile.GNU_FORMAT)
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

        with gpg.Context(home_dir=self.keyring_path) as ctx:
            keys = []
            for key in ctx.keylist():
                keys.append((key.subkeys[0].keyid, key.subkeys[0].length,
                            [uid.uid for uid in key.uids]))

        return keys

    def export_key(self, path, key, armor=True):

        with gpg.Context(armor=armor, home_dir=self.keyring_path) as ctx:
            gpg_key = ctx.get_key(key)

            with open(path, "wb+") as fd:
                for subkey in gpg_key.subkeys:
                    fd.write(ctx.key_export(pattern=str(subkey.keyid)))

    def import_key(self, path, armor=True):

        with gpg.Context(armor=armor, home_dir=self.keyring_path) as ctx:
            with open(path, "rb") as fd:
                ctx.key_import(fd)

    def import_keys(self, path):
        """
            Import all the keys from the specified keyring.
        """

        with gpg.Context(home_dir=path) as ctx:

            keys = []
            for key in list(ctx.keylist()):
                for subkey in key.subkeys:
                    content = BytesIO()
                    content.write(ctx.key_export(pattern=str(subkey.keyid)))
                    keys.append(content)

        with gpg.Context(home_dir=self.keyring_path) as ctx:
            for key in keys:
                key.seek(0)
                ctx.key_import(key)

    def del_key(self, key):

        with gpg.Context(home_dir=self.keyring_path) as ctx:
            gpg_key = ctx.get_key(key)

            # DANGER! op_delete_ext is not officially part of the Python
            # bindings for gpgme. Because of this, it doesn't provide a
            # constant for the value of GPGME_DELETE_FORCE. As of gpgme
            # 1.13.1-7ubuntu2, GPGME_DELETE_FORCE == 2. That could change in
            # the future.
            ctx.op_delete_ext(gpg_key, 2)
