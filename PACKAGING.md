# Publishing on PyPi

alibuild is available from PyPi. Package page at:

<https://pypi.python.org/pypi/alibuild/>

In order to publish a new version:

- Test, test, test.
- Change the tag in setup.py
- Build the source distribution with:

      python setup.py build sdist

- Publish with:

      twine upload dist/*

