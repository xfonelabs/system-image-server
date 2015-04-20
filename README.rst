=====================
 System Image Server
=====================

This code builds the system-image.ubuntu.com site.


Run time dependencies
=====================

`apt-get install` these:

 - pxz | xz-utils
 - python3, python3-gpgme | python, python-gpgme
 - e2fsprogs
 - android-tools-fsutils
 - abootimg


Running the test suite
======================

Some additional dependencies are required for the test suite:

 - python-tox
 - python-mock, python3-mock
 - python-coverage, python3-coverage
 - pep8
 - pyflakes3, pyflakes
 - both pxz and xz-utils (for 100% coverage)


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

    $ tox -e fast-py27,fast-py34

To skip running the fast tests when you are going to run the slow tests
anyway, do this::

    $ tox -e py27,py34

To run just the coverage collecting version of the tests::

    $ tox -e coverage-py27,coverage-py34

Of course, you can run any combination of tests.  To see the full list of
available tests::

    $ tox -l

You can also run just a subset of tests, e.g. if you want to debug why a
single test is failing.  To do this, make sure you've run `tox` at least once
for the environment you want to explore, or run something like::

    $ tox --notest -r -e py34

which generates the *py34* environment you'll use below.

Now you can run a subset of tests.  Say for example, you want to run the
`test_keyring` test from `test_gpg.py`.  Do this::

    $ .tox/py34/bin/python -m nose2 -v -P test_keyring

The `-P` option takes a *pattern*, where the pattern can be any test method,
test class, or test module, and in fact can be a Python regular expression.
Multiple `-P` options can be given.  So, to run all the GPG tests, you could
do (to run all the tests in the module)::

    $ .tox/py34/bin/python -m nose2 -v -P test_gpg

or (to run all tests in the class)::

    $ .tox/py34/bin/python -m nose2 -v -P GPGTests


Notes for Precise
=================

Neither `tox` nor `nose2` is available in Precise.  Here's how to run the test
suite on that distribution version::

    $ python -m unittest discover -s lib -v
    $ python3 -m unittest discover -s lib -v

Note however that the Python 3 test suite will have failures on Precise due to
other missing packages (e.g. `python3-gpgme`).  If it hurts, don't do it.
