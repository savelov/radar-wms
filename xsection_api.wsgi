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

# Where the imagegcc checkout is, if it is not ~/image or ~/imagegcc.  Set it
# here rather than in the Apache config so that the development server and the
# deployed one read the same file.
# os.environ.setdefault("IMAGE_HOME", "/opt/radar/image")

from xsection_api import application  # noqa: E402,F401
