#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The IMAGE engine, held for the lifetime of one mod_wsgi worker.

image_xsection_api.py cuts vertical sections out of the C compositor through
pyimage, and pyimage drives libimage.so in process.  The engine keeps its
state in globals, so this module is what stands between it and Apache.

WHY A MODULE AND NOT JUST AN IMPORT
-----------------------------------
Three things about the engine decide the shape of everything here:

  * it holds one composite in C globals, so there is one Archive per process
    and only one thread may be inside it;
  * Archive chdirs the process to the checkout for its lifetime, so the
    process it lives in cannot be shared with anything that cares where it
    is - every path this module hands out or takes is absolute;
  * reading the archive directory happens once, at open.  New frames arrive
    every ten minutes and will not appear by themselves.

The first two say the engine wants a process to itself.  That is a daemon
group of its own in the Apache config, threads=1, serving nothing else - see
image_xsection_apache.conf, which is the other half of this file.  The lock
below is belt and braces for that: it is what makes the failure a queue
rather than a corrupted composite if the group is ever widened by mistake.

The third is why the Archive is reopened rather than opened once.

WHAT USED TO BE THE OTHER PROBLEM
---------------------------------
The engine answered a bad config by calling exit(), which in a worker is a
request that kills the process serving it.  On the per-request path that is
gone - get_ptr() returns NULL now and the radar is left out of the mosaic
instead (imagegcc, "The library answers the next request instead of
exiting").  What remains is start-up only, and open() is the only place this
module lets it happen: a worker that cannot open the archive fails to start,
which mod_wsgi retries, rather than dying mid-answer.
"""

import datetime
import os
import sys
import threading

#: seconds before the archive directory is read again.  New frames land every
#: ten minutes; a reopen costs about a third of a second and throws away the
#: loaded frame, so this trades a little staleness for not paying that on
#: requests that would not have seen a new frame anyway.
RESCAN_SECONDS = int(os.environ.get("XSECTION_RESCAN_SECONDS", "60"))

#: Hours to take off an archive timestamp to get UTC.
#:
#: The .wrk headers carry local time - Moscow, so +3 - and carry no zone with
#: it, which is why every timestamp out of pyimage is a naive datetime.  The
#: WMS is UTC, because that is what the GeoTIFF pipeline registers and what
#: the TIME dimension of a WMS means.  So a page showing a section and a radar
#: overlay of "the same moment" is reading two clocks, and something has to
#: convert.
#:
#: It converts here.  The alternative - subtracting three hours in the page -
#: puts the deployment's timezone in a file that is served to browsers and
#: copied between sites, and gets it wrong the first time this runs anywhere
#: that is not Moscow.
ARCHIVE_UTC_OFFSET_HOURS = float(
    os.environ.get("XSECTION_ARCHIVE_UTC_OFFSET", "3"))

#: the product each family is loaded through.  load() needs *a* product before
#: the levels of a family can be found, and which one does not matter - level 1
#: is the one every frame that carries the family carries.
FAMILY_PRODUCT = {"dbz": "dbz1", "zdr": "zdr1", "vel": "vel1"}

#: how the engine is found.  $IMAGE_HOME wins, then the usual checkout names -
#: the same order generate_image_archive.py uses, so both agree on which
#: checkout is in play when there is more than one.
#:
#: /opt/radar/image is on the end for the deployed case.  Under mod_wsgi this
#: runs as www-data, whose home is /var/www, so the two ~ entries resolve to
#: directories that do not exist and never will; without a third candidate
#: every deployment would have to set IMAGE_HOME by hand.
IMAGE_HOME_CANDIDATES = [os.environ.get("IMAGE_HOME"),
                         os.path.expanduser("~/image"),
                         os.path.expanduser("~/imagegcc"),
                         "/opt/radar/image"]


class EngineError(Exception):
    """Something the caller can be told about without a traceback."""


def to_utc(stamp):
    """An archive timestamp as UTC.  See ARCHIVE_UTC_OFFSET_HOURS."""
    return stamp - datetime.timedelta(hours=ARCHIVE_UTC_OFFSET_HOURS)


def utc_text(stamp):
    """An archive timestamp as the WMS wants to be given a TIME."""
    return to_utc(stamp).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_image_home():
    """The imagegcc checkout, or an error that says where it looked.

    Naming the candidates matters more here than anywhere else in this file.
    Under mod_wsgi the search runs as www-data, whose home is /var/www, so the
    two ~ entries expand to directories nobody has ever seen - and an error
    that only says "set IMAGE_HOME" leaves the reader guessing whether the
    checkout is missing, unreadable, or simply somewhere else.
    """
    tried = []
    for candidate in filter(None, IMAGE_HOME_CANDIDATES):
        marker = os.path.join(candidate, "pyimage.py")
        if os.path.isfile(marker):
            return os.path.abspath(candidate)
        if not os.path.isdir(candidate):
            tried.append("%s (no such directory)" % candidate)
        elif not os.access(candidate, os.R_OK | os.X_OK):
            tried.append("%s (not readable by %s)"
                         % (candidate, _whoami()))
        else:
            tried.append("%s (no pyimage.py in it)" % candidate)

    raise EngineError(
        "cannot find the imagegcc checkout. Looked in: %s. Set IMAGE_HOME in "
        "image_xsection_api.wsgi to the directory holding pyimage.py and "
        "libimage.so - and check %s can read it."
        % ("; ".join(tried) or "nowhere - IMAGE_HOME is unset and no default "
           "applies", _whoami()))


def _whoami():
    """The user the worker runs as, for a message about permissions."""
    try:
        import pwd
        return pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        return "this process"


class Engine(object):
    """One process's worth of IMAGE.

    Every method takes the lock and holds it for as long as the C engine is
    being touched, which for a cut is the load and the section together: the
    section reads the composite the load built, so another request loading a
    different frame in between would cut through the wrong one.
    """

    def __init__(self, paths=None, rescan_seconds=RESCAN_SECONDS):
        self._lock = threading.RLock()
        self._archive = None
        self._pyimage = None
        self._opened_at = None
        self._rescan = rescan_seconds
        self._home = _find_image_home()
        self._paths = os.path.abspath(paths or os.path.join(self._home, "paths"))
        #: (timestamp, product) of what the composite currently holds, so a
        #: second cut through one frame does not pay the load again.  This is
        #: the whole reason the engine is kept warm: the load is about a
        #: second and the cut that follows it is twenty milliseconds.
        self._loaded = None

    # -- opening ----------------------------------------------------------

    def _import(self):
        if self._pyimage is None:
            home = self._home
            if home not in sys.path:
                sys.path.insert(0, home)
            import pyimage
            self._pyimage = pyimage
        return self._pyimage

    def _open(self):
        """Open the archive.  Caller holds the lock."""
        pyimage = self._import()
        if self._archive is not None:
            self._archive.close()
            self._archive = None
            self._loaded = None
        try:
            self._archive = pyimage.Archive(self._paths, workdir=self._home)
        except pyimage.ImageError as error:
            raise EngineError(str(error))
        self._opened_at = datetime.datetime.now()
        return self._archive

    def _current(self):
        """The archive, reopened if the directory listing has gone stale.

        Caller holds the lock.  Reopening is how new frames are noticed:
        read_dir() runs once per Archive and the archive is written to every
        ten minutes by the pipeline.
        """
        if self._archive is None:
            return self._open()
        age = (datetime.datetime.now() - self._opened_at).total_seconds()
        if age >= self._rescan:
            return self._open()
        return self._archive

    def close(self):
        with self._lock:
            if self._archive is not None:
                self._archive.close()
                self._archive = None
                self._loaded = None

    # -- what the API asks for --------------------------------------------

    def frames(self, limit=None):
        """Archive timestamps, newest first."""
        with self._lock:
            archive = self._current()
            stamps = [f.timestamp for f in archive.frames]
        stamps.sort(reverse=True)
        return stamps[:limit] if limit else stamps

    def _frame_for(self, when):
        """The frame nearest `when`, or the newest.  Caller holds the lock."""
        archive = self._current()
        if not archive.frames:
            raise EngineError("the archive is empty")
        if when is None:
            return max(archive.frames, key=lambda f: f.timestamp)
        return archive.nearest(when)

    def _load(self, frame, product):
        """Mosaic `product` for `frame`, unless it is already up.  Locked."""
        pyimage = self._pyimage
        if self._loaded == (frame.timestamp, product):
            return frame
        try:
            frame.load(product)
        except pyimage.ImageError as error:
            self._loaded = None
            raise EngineError(str(error))
        self._loaded = (frame.timestamp, product)
        return frame

    def info(self, when=None, product="dbz1"):
        """Grid geometry, projection and the radars of one frame."""
        with self._lock:
            frame = self._frame_for(when)
            self._load(frame, product)
            info = dict(frame.info)
            info["families"] = frame.families()
            info["levels"] = {fam: frame.levels(fam)
                              for fam in info["families"]}
            info["frame_time"] = frame.timestamp
            return info

    def legend(self, family="dbz", when=None):
        """The colours and labels the map uses for a family.

        A frame still has to be loaded first - the palette is the loaded
        product's, and which product that is decides which palette file the
        engine reads.
        """
        product = FAMILY_PRODUCT.get(family)
        if product is None:
            raise EngineError("unknown family %r - one of %s"
                              % (family, ", ".join(sorted(FAMILY_PRODUCT))))
        with self._lock:
            frame = self._frame_for(when)
            self._load(frame, product)
            return frame.legend(family)

    def cross_section(self, lon1, lat1, lon2, lat2, family="dbz",
                      when=None, smooth=True, values=True):
        """Cut a section between two lon/lat points.

        Returns (CrossSection, info) with the frame's info alongside, because
        the caller needs the geometry that turned the coordinates into cells
        in order to describe what it is sending back.
        """
        product = FAMILY_PRODUCT.get(family)
        if product is None:
            raise EngineError("unknown family %r - one of %s"
                              % (family, ", ".join(sorted(FAMILY_PRODUCT))))

        with self._lock:
            frame = self._frame_for(when)
            self._load(frame, product)
            info = frame.info

            x1, y1 = lonlat_to_cell(info, lon1, lat1)
            x2, y2 = lonlat_to_cell(info, lon2, lat2)

            section = frame.cross_section(x1, y1, x2, y2, family=family,
                                          smooth=smooth, values=values)
            if section is None:
                raise EngineError(
                    "no %s section for %s: the frame carries %d level(s) of "
                    "it and a section needs two, or the line is too short"
                    % (family, frame.timestamp.strftime("%Y-%m-%d %H:%M"),
                       frame.levels(family)))

            out = dict(info)
            out["frame_time"] = frame.timestamp
            out["cells"] = (x1, y1, x2, y2)
            out["legend"] = frame.legend(family)
            out["family_levels"] = frame.levels(family)
            return section, out

    def health(self):
        """Enough to tell a monitor whether this worker is any use."""
        with self._lock:
            try:
                archive = self._current()
            except EngineError as error:
                return {"ok": False, "error": str(error), "pid": os.getpid()}
            stamps = [f.timestamp for f in archive.frames]
            return {
                "ok": True,
                "pid": os.getpid(),
                "image_home": self._home,
                "paths": self._paths,
                "frames": len(stamps),
                "newest": max(stamps).isoformat() + "Z" if stamps else None,
                "oldest": min(stamps).isoformat() + "Z" if stamps else None,
                "loaded": ("%s %s" % (self._loaded[0].isoformat(),
                                      self._loaded[1])
                           if self._loaded else None),
            }


# -- the grid --------------------------------------------------------------

_TRANSFORMERS = {}


def _transformer(proj4):
    """WGS84 lon/lat into the engine's projection.

    Cached because building one costs more than using it, and every request
    wants the same one: the projection comes from the config, not the frame.
    """
    if proj4 not in _TRANSFORMERS:
        from pyproj import Transformer
        _TRANSFORMERS[proj4] = Transformer.from_crs("EPSG:4326", proj4,
                                                    always_xy=True)
    return _TRANSFORMERS[proj4]


def lonlat_to_cell(info, lon, lat):
    """A longitude and a latitude as a cell of the product grid.

    The grid is what Frame.grid() is indexed by and what cross_section()
    takes: row 0 is the NORTH edge, so y counts down from the top of the
    bbox while the projected coordinate counts up.
    """
    x_m, y_m = _transformer(info["proj4"]).transform(lon, lat)
    minx, miny, maxx, maxy = info["bbox"]
    pixel = info["pixel_m"]
    return (int(round((x_m - minx) / pixel)),
            int(round((maxy - y_m) / pixel)))


def cell_to_lonlat(info, x, y):
    """The inverse, for reporting where a section actually got cut."""
    from pyproj import Transformer
    minx, miny, maxx, maxy = info["bbox"]
    pixel = info["pixel_m"]
    back = Transformer.from_crs(info["proj4"], "EPSG:4326", always_xy=True)
    return back.transform(minx + x * pixel, maxy - y * pixel)


# -- the one per process ---------------------------------------------------

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def engine():
    """The process's Engine, built on first use.

    Built lazily rather than at import so that a worker whose archive is
    briefly unreadable answers 503 and recovers, instead of failing to import
    and leaving mod_wsgi retrying the module for the life of the process.
    """
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = Engine()
        return _ENGINE
