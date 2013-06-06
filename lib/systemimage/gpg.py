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

import gpgme
import os


def sign_file(key, path, destination=None, detach=True, armor=True):
    """
        Sign a file and publish the signature.
        The key parameter must be a valid key unders gpg/keys/.
        The path must be that of a valid file.
        The destination defaults to <path>.gpg (non-armored) or
        <path>.asc (armored).
        The detach and armor parameters respectively control the use of
        detached signatures and base64 armoring.
    """

    if not os.path.isdir("gpg/keys/%s" % key):
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
        raise Exception("destination already exists.")

    os.environ['GNUPGHOME'] = "gpg/keys/%s" % key

    # Create a GPG context, assuming no passphrase
    ctx = gpgme.Context()
    ctx.armor = armor
    [key] = ctx.keylist()
    ctx.signers = [key]

    with open(path, "rb") as fd_in, open(destination, "wb+") as fd_out:
        if detach:
            retval = ctx.sign(fd_in, fd_out, gpgme.SIG_MODE_DETACH)
        else:
            retval = ctx.sign(fd_in, fd_out, gpgme.SIG_MODE_NORMAL)

    return retval
