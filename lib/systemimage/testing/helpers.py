# Copyright (C) 2015 Canonical Ltd.
# Author: Barry Warsaw <barry@ubuntu.com>

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

__all__ = [
    "HAS_TEST_KEYS",
    "MISSING_KEYS_WARNING",
    "system_image_root",
    ]


import os
from contextlib import contextmanager

HAS_TEST_KEYS = os.path.exists(os.path.join("tools", "keys", "generated"))
MISSING_KEYS_WARNING = 'No GPG testing keys present.  Run tools/generate-keys'


@contextmanager
def system_image_root(path):
    """Temporarily set the $SYSTEM_IMAGE_ROOT environment variable."""
    old_envar = os.environ.get("SYSTEM_IMAGE_ROOT")
    try:
        os.environ['SYSTEM_IMAGE_ROOT'] = path
        yield
    finally:
        if old_envar is None:
            del os.environ['SYSTEM_IMAGE_ROOT']
        else:
            os.environ['SYSTEM_IMAGE_ROOT'] = old_envar
