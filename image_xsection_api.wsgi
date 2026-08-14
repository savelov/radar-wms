#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mod_wsgi entry point for the cross section API.

Thin on purpose: everything is in image_xsection_api.py, which also runs under
wsgiref for development.

This must be mounted in a daemon group of its own with threads=1 - see the
WSGIDaemonProcess block in image_xsection_apache.conf, and the reasons in
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

from image_xsection_api import application  # noqa: E402,F401

# Open the archive now, if this file is being imported at process start rather
# than by the first request.  Reading the directory of a large archive takes
# real time - fourteen seconds for 179000 frames over 38 radars - and it is
# much better spent while mod_wsgi is starting the worker than while somebody
# is waiting for a section.  Pair it with, in the Apache config:
#
#     WSGIImportScript /path/to/image_xsection_api.wsgi \
#         process-group=xsection application-group=%{GLOBAL}
#
# Failure is deliberately not fatal: the engine opens lazily too, so a worker
# whose archive is briefly unreadable still starts and answers 503 until it
# can, rather than failing to import for the life of the process.
try:
    from image_engine import engine

    engine().frames(limit=1)
except Exception as _error:                                   # noqa: BLE001
    sys.stderr.write("image_xsection: archive not ready at import (%s); "
                     "the first request will open it\n" % _error)
