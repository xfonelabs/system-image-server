=====================
 System Image Server
=====================

system-image-server is the server-side component of Image-Based Upgrades of Ubuntu Touch. When used with `the system-image client <https://github.com/ubports/system-image>`_, it provides a way for an operating system to be distributed through immutable system images. See `ImageBasedUpgrades on the Ubuntu Wiki <https://wiki.ubuntu.com/ImageBasedUpgrades/>`_ to learn more.


Run time dependencies
=====================

``apt-get install`` these:

- xz-utils
- python3, python3-gpg
- e2fsprogs
- android-sdk-libsparse-utils
- abootimg
- fakeroot


Running the test suite
======================

Some additional dependencies are required for the test suite:

- tox
- python3-nose2
- python3-mock
- python3-coverage
- pep8
- pyflakes3 (Ubuntu 16.04 and later)
- xz-utils (for 100% coverage)
- cpio
- python3-six

A final set of dependencies is needed to have full HTML coverage reports with
``python3-coverage html``:

- libjs-jquery-hotkeys
- libjs-jquery-isonscreen
- libjs-jquery-tablesorter
- libjs-jquery-throttle-debounce

The full test suite require you to pre-generate some GPG keys.  Actually, you
can run the test suite without this, but many tests will be skipped.  To
generate the keys, run this command once, but be aware that this can take a
long time::

    $ ./tools/generate-keys

Some tests can take a while.  To run the full test suite, including the fast
tests and code coverage tests, run this::

    $ tox

If you want to just run a subset of the tests, you can provide some options to
the `tox` command.  E.g. to avoid running the slow tests, do this::

    $ tox -e fast-py38

To skip running the fast tests when you are going to run the slow tests
anyway, do this::

    $ tox -e py38

To run just the coverage collecting version of the tests::

    $ tox -e coverage-py38

Once you have run the coverage tests at least once, you can create a coverage
report. The following command will place an HTML coverage report in the
``htmlcov/`` folder::

    python3-coverage html --rcfile=coverage-py38.ini

Of course, you can run any combination of tests.  To see the full list of
available tests::

    $ tox -l

You can also run just a subset of tests, e.g. if you want to debug why a
single test is failing.  To do this, make sure you've run `tox` at least once
for the environment you want to explore, or run something like::

    $ tox --notest -r -e py38

which generates the *py38* environment you'll use below.

Now you can run a subset of tests.  Say for example, you want to run the
`test_keyring` test from `test_gpg.py`.  Do this::

    $ .tox/py38/bin/python -m nose2 -v -P test_keyring

The `-P` option takes a *pattern*, where the pattern can be any test method,
test class, or test module, and in fact can be a Python regular expression.
Multiple `-P` options can be given.  So, to run all the GPG tests, you could
do (to run all the tests in the module)::

    $ .tox/py38/bin/python -m nose2 -v -P test_gpg

or (to run all tests in the class)::

    $ .tox/py38/bin/python -m nose2 -v -P GPGTests

See also
========

For more information on setting up a server see:

    https://wiki.ubuntu.com/ImageBasedUpgrades/ServerSetup

For more information on operating a server see:

    https://wiki.ubuntu.com/ImageBasedUpgrades/ServerOperation
