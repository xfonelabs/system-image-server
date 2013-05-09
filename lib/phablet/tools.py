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

import subprocess


def mount(source, destination, options=("default",)):
    if subprocess.call(['mount',
                        '-o', ",".join(options),
                        source, destination]) != 0:
        raise Exception("Failed to mount '%s' on '%s' (options=%s)" %
                        (source, destination, ",".join(options)))


def umount(path):
    if subprocess.call(['umount', path]) != 0:
        raise Exception("Failed to umount '%s'" % path)
