#!/usr/bin/env python

import os

from setuptools import setup

# under test we do not want the nose entry point
if "XTRACEBACK_NO_NOSE" in os.environ:
    entry_points = None
else:
    entry_points = {
        "nose.plugins": ("xtraceback=xtraceback.nosextraceback:NoseXTraceback",),
        }

README = open(os.path.join(os.path.dirname(__file__), "README.md"))

setup(name="xtraceback",
      version="0.4.0-dev",
      description="A verbose traceback formatter",
      long_description="\n".join(README.read().splitlines()[0:3]),
      license="MIT",
      keywords="traceback exception nose",
      author="Ischium",
      author_email="support@ischium.net",
      url="https://github.com/ischium/xtraceback",
      packages=("xtraceback",),
      install_requires=("stacked >= 0.1.1",),
      extras_require=dict(syntax=("pygments")),
      tests_require=("nose", "pygments", "yanc"),
      test_suite="nose.collector",
      entry_points=entry_points,
      )
