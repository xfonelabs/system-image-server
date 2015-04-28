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

from setuptools import find_packages, setup

setup(
    name="system-image",
    description="Ubuntu System Image Server",
    author="Barry Warsaw",
    author_email="barry@ubuntu.com",
    license="GNU GPLv3",
    packages=find_packages("lib"),
    package_dir={"": "lib"},
    include_package_data=True,
    )
