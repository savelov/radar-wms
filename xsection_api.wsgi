#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mod_wsgi entry point for the cross section API.

Thin on purpose: everything is in xsection_api.py, which also runs under
wsgiref for development.

This must be mounted in a daemon group of its own with threads=1 - see the
WSGIDaemonProcess block in xsection_apache.conf, and the reasons in
image_engine.py.  The engine is opened on the first request rather than here,
so a worker whose archive is briefly unreadable answers 503 and recovers
instead of failing to import for the life of the process.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Where the imagegcc checkout is.  image_engine.py already tries ~/image,
# ~/imagegcc and /opt/radar/image, which covers the development machine and a
# tidy deployment; set this when it is somewhere else.
#
# It goes here and not in the Apache config because mod_wsgi's SetEnv fills
# the WSGI environ, which is not os.environ, and the engine reads os.environ.
# Here it also means the development server and the deployed one read one file.
#
# os.environ.setdefault("IMAGE_HOME", "/home/eugene/image")

from xsection_api import application  # noqa: E402,F401
