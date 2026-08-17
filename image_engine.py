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

import bisect
import datetime
import os
import sys
import threading

#: distinguishes "not looked yet" from "looked, and there is none"
_UNSET = object()

#: How often to look for new frames.
#:
#: Looking is cheap; reopening is not.  Reopening an Archive re-runs the C
#: directory scan, which walks one file per radar per frame - on the
#: production archive, 36 radars over 179000 frames, about eight seconds - and
#: throws away the mosaic in the C globals with it.
#:
#: A minute is affordable because the look is _newest_on_disk(): a directory
#: listing per radar, answering "is there a frame here we have not got".  It
#: used to be the mtimes, which answer "was anything written" - true almost
#: continuously on a live network, so it reopened every 74 seconds and found
#: nothing every time.
RESCAN_SECONDS = int(os.environ.get("XSECTION_RESCAN_SECONDS", "60"))

#: How long before the mtimes are allowed to force a reopen on their own.
#:
#: No new name appears when a radar joins a frame that already exists, and the
#: newest frame is often part written - so something has to notice, and the
#: mtimes are all there is.  They cannot be trusted at the interval above or
#: they would put the every-74-seconds behaviour straight back, so they get
#: their say on the slow clock instead.
REFILL_SECONDS = int(os.environ.get("XSECTION_REFILL_SECONDS", "600"))

#: Read only this many days back from the archive.  0 reads all of it.
#:
#: Thirty, because the archive is years deep and this API is asked about the
#: last day or two.  Thirty still covers "what happened last Tuesday", which
#: is the far end of what anyone cuts a section through, and it keeps the
#: frame list a few thousand entries rather than a hundred and eighty
#: thousand - which is a couple of seconds off every reopen and about 25 MB
#: off the worker.  Below a month it stops helping (see below), so there is
#: nothing to gain by going lower and history to lose.
#:
#: XSECTION_ARCHIVE_DAYS=0 restores the whole archive.  generate_image_archive
#: does not come through here and is unaffected: it reads the archive whole,
#: which is what backfilling old frames needs.
#:
#: read_dir() walks one file per radar per frame, and on an archive years deep
#: that is millions of names for a page that only ever asks about the last
#: day or two.  A cutoff halves it - the parse, the per radar sort and the
#: merge all shrink to what is kept.
#:
#: It does not halve it twice.  The other half is the readdir() of every entry
#: in the directory, wanted or not, and a directory cannot be asked for part
#: of itself; below about a month the cutoff stops helping because that floor
#: is all that is left.  The cure for the floor is fewer files - moving old
#: frames out of the archive directory rather than asking the engine to skip
#: them.
ARCHIVE_DAYS = int(os.environ.get("XSECTION_ARCHIVE_DAYS", "30"))

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
    """Something the caller can be told about without a traceback.

    `detail` carries whatever would help the caller act on it - the radar list
    behind a "no radar near that line", so the page can show how far away the
    nearest one is instead of blanking and leaving the reader to guess.
    """

    def __init__(self, message, detail=None):
        Exception.__init__(self, message)
        self.detail = detail or {}


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


def _rss_mb():
    """This worker's resident size, or None where /proc says nothing.

    Worth reporting because every mod_wsgi process is a full independent copy
    of all this - its own archive, its own grids - so `processes` in the
    daemon group multiplies whatever this says.  On a box that has swapped
    before, that is the number to watch before raising it.
    """
    try:
        with open("/proc/self/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


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

    def __init__(self, paths=None, rescan_seconds=RESCAN_SECONDS,
                 refill_seconds=REFILL_SECONDS):
        self._lock = threading.RLock()
        self._archive = None
        self._pyimage = None
        self._opened_at = None
        self._rescan = rescan_seconds
        self._refill = refill_seconds
        self._home = _find_image_home()
        self._paths = os.path.abspath(paths or os.path.join(self._home, "paths"))
        self._map = _UNSET      # the MAP directory, parsed once on first use
        self._stamp = None      # archive mtime fingerprint at the last open
        self._sorted = []       # frames, oldest first
        self._times = []        # their timestamps, for bisect
        #: (timestamp, product) of what the composite currently holds, so a
        #: second cut through one frame does not pay the load again.  This is
        #: the whole reason the engine is kept warm: the load is about a
        #: second and the cut that follows it is twenty milliseconds.
        self._loaded = None
        #: (timestamp, radars) from a read with every port open.  Deciding
        #: which radars a line needs requires knowing where they all are, and
        #: that costs a read - so it is remembered per frame rather than paid
        #: again on every cut of the same frame.
        self._radars = None

    # -- opening ----------------------------------------------------------

    def _import(self):
        if self._pyimage is None:
            home = self._home
            if home not in sys.path:
                sys.path.insert(0, home)
            import pyimage
            self._pyimage = pyimage
        return self._pyimage

    def _mapdir(self):
        """The archive directory, from the MAP line of the path file.

        Resolved against the checkout, the way the engine resolves it.  None
        when the file cannot be read or names no MAP - the caller then falls
        back to the timer alone.
        """
        if self._map is not _UNSET:
            return self._map
        self._map = None
        try:
            with open(self._paths, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    parts = line.split(None, 1)
                    if len(parts) == 2 and parts[0].upper() == "MAP":
                        self._map = os.path.join(self._home, parts[1].strip())
                        break
        except OSError:
            pass
        return self._map

    def _newest_on_disk(self):
        """The newest frame in the archive, from the file names alone.

        <map>/port<N>/YYMMDDHH.MMm, zero padded throughout, so the names sort
        chronologically and the largest one in a port directory is that
        radar's newest frame.  The largest of those is the archive's.

        This is the question the mtime test could not answer.  A mtime says a
        file was written, and with 36 radars delivering asynchronously that is
        true more or less continuously - it fired on every check and reopened
        every 74 seconds without the frame count ever changing.  A name says
        WHICH frame was written, so a reopen happens when there is something
        new to find and not merely something new on disk.

        Costs a directory listing per radar - milliseconds against the eight
        seconds a read_dir of the whole archive costs.  None when the layout
        is not what is expected, which the caller reads as "assume stale".
        """
        mapdir = self._mapdir()
        if not mapdir:
            return None
        newest = ""
        try:
            with os.scandir(mapdir) as ports:
                for port in ports:
                    if not port.is_dir():
                        continue
                    for name in os.listdir(port.path):
                        if name > newest and name.endswith("m"):
                            newest = name
        except OSError:
            return None
        if len(newest) < 12:
            return None
        try:
            return datetime.datetime(2000 + int(newest[0:2]), int(newest[2:4]),
                                     int(newest[4:6]), int(newest[6:8]),
                                     int(newest[9:11]))
        except ValueError:          # a stray name that is not a frame
            return None

    def _archive_stamp(self):
        """A cheap fingerprint of the archive's contents.

        The newest mtime of the archive directory and the port directories
        under it.  A frame arriving writes <map>/port<N>/<time>.wrk, and a new
        name in a directory moves that directory's mtime - so this changes
        exactly when there is something new to find, at the cost of one stat
        per radar instead of a walk over every file of every frame.

        None when it cannot be determined, which the caller reads as "assume
        stale" rather than "assume fresh".
        """
        mapdir = self._mapdir()
        if not mapdir:
            return None
        try:
            newest = os.stat(mapdir).st_mtime
            with os.scandir(mapdir) as entries:
                for entry in entries:
                    if entry.is_dir():
                        newest = max(newest, entry.stat().st_mtime)
        except OSError:
            return None
        return newest

    def _open(self):
        """Open the archive.  Caller holds the lock."""
        pyimage = self._import()
        if self._archive is not None:
            self._archive.close()
            self._archive = None
            self._loaded = None
        # A reopen is how a frame that was part written when it was first read
        # is noticed to have gained a radar since, so the remembered positions
        # go with it rather than outliving the read they came from.
        self._radars = None
        stamp = self._archive_stamp()          # before the scan, never after
        # recomputed on every open, so the window follows the clock
        since = (datetime.datetime.now() - datetime.timedelta(days=ARCHIVE_DAYS)
                 if ARCHIVE_DAYS > 0 else None)
        try:
            self._archive = pyimage.Archive(self._paths, workdir=self._home,
                                            since=since)
        except pyimage.ImageError as error:
            raise EngineError(str(error))
        self._opened_at = datetime.datetime.now()
        self._stamp = stamp

        # Sorted once here so that finding a frame is a bisect rather than a
        # walk.  min() over the frame list costs nothing at fifteen thousand
        # frames and about forty milliseconds at a hundred and eighty, on
        # every single request.
        self._sorted = sorted(self._archive.frames, key=lambda f: f.timestamp)
        self._times = [f.timestamp for f in self._sorted]
        return self._archive

    def _current(self):
        """The archive, re-read only when there is something new to find.

        Caller holds the lock.  read_dir() runs once per Archive, so reopening
        is the only way to notice new frames, and on a large archive it costs
        about eight seconds - too much to spend on a timer alone.

        Two questions, asked in order of how cheap they are:

          * has a frame arrived that we do not have?  The file names say so
            directly, at a directory listing per radar.  This is the one that
            matters, and it is what makes a short interval affordable.
          * failing that, has anything at all been written?  A radar can join
            a frame we already know about - the newest frame is often part
            written - and no new name appears when it does.  That is the
            mtimes, and because they are true almost continuously on a busy
            network they are only allowed to force a reopen occasionally.
        """
        if self._archive is None:
            return self._open()

        age = (datetime.datetime.now() - self._opened_at).total_seconds()
        if age < self._rescan:
            return self._archive

        # a frame we have not got is worth eight seconds straight away
        newest = self._newest_on_disk()
        if newest is None or (self._times and newest > self._times[-1]):
            return self._open()

        # no new frame.  A radar may still have joined one we have, which no
        # name reveals - so the mtimes get their say, but only every so often,
        # or they would put us back to reopening every minute for nothing.
        stamp = self._archive_stamp()
        if (stamp is None or stamp != self._stamp) and age >= self._refill:
            return self._open()

        self._opened_at = datetime.datetime.now()   # charge the timer only
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
            self._current()
            # Sorted once at open, so this takes the tail and reverses only
            # what was asked for.  Reversing the whole list first would copy a
            # hundred and eighty thousand timestamps to hand back two hundred.
            times = self._times[-limit:] if limit else list(self._times)
        times.reverse()
        return times

    def _frame_for(self, when):
        """The frame nearest `when`, or the newest.  Caller holds the lock."""
        self._current()
        if not self._sorted:
            raise EngineError("the archive is empty")
        if when is None:
            return self._sorted[-1]

        # bisect, then look at the two neighbours: the nearest frame is one of
        # them, and this is O(log n) where nearest() was O(n)
        i = bisect.bisect_left(self._times, when)
        if i == 0:
            return self._sorted[0]
        if i >= len(self._sorted):
            return self._sorted[-1]
        before, after = self._sorted[i - 1], self._sorted[i]
        return after if (after.timestamp - when) < (when - before.timestamp) \
            else before

    def _load(self, frame, product, only=None, passports=False, ports=None):
        """Mosaic `product` for `frame`, unless it is already up.  Locked.

        `only` narrows the read to one family, which is three times cheaper
        than reading all forty-four products - on the production archive that
        is about two seconds against seven.

        The cache is keyed on what was read, not just on which product was
        selected, and a request is a hit when what it needs is a SUBSET of
        what is loaded.  That is what stops narrowing from costing anything:
        a frame read whole still satisfies every family afterwards, and only
        a frame that was never read pays, and pays narrowly.
        """
        pyimage = self._pyimage
        want = self._archive.mask_for(product, only, passports)
        # None means every radar.  In the cache key that has to be a mask like
        # any other, or a cut restricted to two radars would satisfy the next
        # one that wanted all of them.
        pmask = (self._archive.PORT_ALL if ports is None
                 else self._archive.port_mask(ports))

        # Products and ports cache differently, and the difference is not a
        # detail.  Having MORE products loaded than asked for is harmless: the
        # extra ones sit in their own buffers and nothing reads them.  Having
        # more RADARS loaded is not - they are merged into one composite, so a
        # cut over a mosaic built from five radars is a different picture from
        # the same cut over three, which is the whole point of being able to
        # exclude one.  Subset for products, exact for ports.
        if (self._loaded and self._loaded[0] == frame.timestamp
                and not (want & ~self._loaded[1])
                and pmask == self._loaded[2]):
            # everything asked for is already in the composite; set_cur_map is
            # still needed, because "which product is current" is not the mask
            self._archive._lib.set_cur_map(pyimage.PRODUCTS[product])
            frame.product = product
            return frame

        try:
            frame.load(product, only=only, passports=passports, ports=ports)
        except pyimage.ImageError as error:
            self._loaded = None
            raise EngineError(str(error))
        self._loaded = (frame.timestamp, self._archive.loaded_mask, pmask)
        return frame

    def info(self, when=None, product="dbz1"):
        """Grid geometry, projection and the radars of one frame."""
        with self._lock:
            frame = self._frame_for(when)
            # Passports for everything but the one product this needs a grid
            # for.  The level counts and the geometry come out of the eight
            # header bytes of each product, so mosaicking all forty-four to
            # report them was paying ten times over for numbers that were
            # already in the headers.  The other products come back with empty
            # grids, which is exactly why _load() keys the cache on what was
            # mosaicked - a cut cannot mistake a passport for data.
            self._load(frame, product, passports=True)
            info = dict(frame.info)
            # `families` is what can be cut - two levels or more.  `levels`
            # counts every family, including the ones that cannot, so a caller
            # can say "velocity: no levels in this frame" instead of quietly
            # dropping the button.  The newest frame is often part written:
            # the pipeline lands dbz before vel, and a family that is missing
            # for one cycle and back the next reads as a bug when it is not.
            # present=True, because this read the passports and mosaicked one
            # product: every level is there and none but that one is cuttable.
            # The question the page asks is what the frame contains, and
            # answering it with "what could be cut out of the composite as it
            # stands" would report a frame full of levels as empty.
            info["levels"] = {fam: frame.levels(fam, present=True)
                              for fam in FAMILY_PRODUCT}
            info["families"] = [fam for fam in FAMILY_PRODUCT
                                if info["levels"][fam] >= 2]
            # this read had every port open, so it knows where the radars are
            self._radars = (frame.timestamp, info["radars"])
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
            self._load(frame, product, only=family)
            return frame.legend(family)

    def cross_section(self, lon1, lat1, lon2, lat2, family="dbz",
                      when=None, smooth=True, values=True, ports=None,
                      range_km=None):
        """Cut a section between two lon/lat points.

        Returns (CrossSection, info) with the frame's info alongside, because
        the caller needs the geometry that turned the coordinates into cells
        in order to describe what it is sending back.

        `ports` is the radars to build the mosaic from.  Left alone, it is
        every radar within RADAR_RANGE_KM of the line: one that cannot see any
        of it contributes nothing but the time taken to unzip it.  Given
        explicitly, it is also how to choose between two radars that overlap -
        Sochi and Ahun, Pulkovo and Voeykovo - where the merge would otherwise
        pick for you and the section would be of whichever it preferred.
        """
        product = FAMILY_PRODUCT.get(family)
        if product is None:
            raise EngineError("unknown family %r - one of %s"
                              % (family, ", ".join(sorted(FAMILY_PRODUCT))))

        with self._lock:
            frame = self._frame_for(when)

            # Which radars to open cannot be decided without knowing where
            # they all are, and that comes from header.wrk - one per port, and
            # only for the ports that were opened.  So it takes a read with
            # every port open, which is the opposite of what the cut wants.
            #
            # Doing that read on every cut made the two fight: the wide read
            # evicted the narrow one and the narrow one evicted the wide one,
            # so nothing was ever a cache hit and every cut paid twice.  The
            # positions are per frame and do not change within it, so they are
            # remembered instead, and the wide read happens once per frame.
            if self._radars and self._radars[0] == frame.timestamp:
                radars = self._radars[1]
            else:
                self._load(frame, product, passports=True)
                radars = frame.info["radars"]
                self._radars = (frame.timestamp, radars)

            near = radars_for_line({"proj4": frame.info["proj4"],
                                    "radars": radars},
                                   lon1, lat1, lon2, lat2, range_km)
            if ports is None:
                ports = [r["port"] for r in near if r["within"]]
            else:
                ports = [int(p) for p in ports]
            for radar in near:
                radar["used"] = radar["port"] in ports

            if not ports:
                # The radar list goes with the refusal.  A blank section and a
                # message that has scrolled away is how "no radar reaches
                # there" gets read as "the section is broken" - so the caller
                # gets the distances and can see for itself, or tick a distant
                # radar and find out what it looks like.
                raise EngineError(
                    "no radar within %.0f km of that line - the nearest is %s "
                    "at %.0f km"
                    % (range_km or RADAR_RANGE_KM,
                       near[0]["name"] if near else "none",
                       near[0]["distance_km"] if near else 0),
                    {"radars": near, "ports_used": []})

            # and now the real load, with only those radars opened
            self._load(frame, product, only=family, ports=ports)
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
            out["radars_near"] = near
            out["ports_used"] = ports
            return section, out

    def health(self):
        """Enough to tell a monitor whether this worker is any use.

        Deliberately does NOT re-read the archive.  A health check that can
        cost eight seconds is not a health check - whoever is asking wants to
        know what this worker is doing, and making them wait for a directory
        scan to find out is the opposite of that.  It opens the archive if
        nothing has yet, and otherwise reports what is already known, stale
        frame count and all.
        """
        with self._lock:
            try:
                archive = self._archive or self._open()
            except EngineError as error:
                return {"ok": False, "error": str(error), "pid": os.getpid(),
                        "rss_mb": _rss_mb()}
            return {
                "ok": True,
                "pid": os.getpid(),
                "image_home": self._home,
                "paths": self._paths,
                # sorted at open, so these are the ends of a list rather than
                # a max() and a min() over every frame on every health check
                "frames": len(self._times),
                "newest": self._times[-1].isoformat() + "Z" if self._times else None,
                "oldest": self._times[0].isoformat() + "Z" if self._times else None,
                "loaded": ("%s (%d products, %s radars)"
                           % (self._loaded[0].isoformat(),
                              bin(self._loaded[1]).count("1"),
                              "all" if self._loaded[2] == self._archive.PORT_ALL
                              else bin(self._loaded[2]).count("1"))
                           if self._loaded else None),
                # what the slow path is doing, because that is the question
                # anyone looking at this endpoint is actually asking
                "rss_mb": _rss_mb(),
                "opened_at": self._opened_at.isoformat() if self._opened_at else None,
                "rescan_seconds": self._rescan,
                # "all" when no window was asked for; "N (ignored: nothing
                # that recent)" when one was and the archive had nothing in
                # it - which is how a stalled pipeline shows up here instead
                # of as an unexplained slow open.
                "archive_days": (
                    "all" if not ARCHIVE_DAYS
                    else ARCHIVE_DAYS if getattr(archive, "windowed", True)
                    else "%d (ignored: no frames that recent)" % ARCHIVE_DAYS),
                "archive_dir": self._mapdir(),
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


#: How far a radar is taken to see, in km.  The .wrk grids do not record their
#: own range, and 250 km is what the DMRL network is quoted at; a radar further
#: than this from the line contributes nothing to a section along it.
RADAR_RANGE_KM = float(os.environ.get("XSECTION_RADAR_RANGE_KM", "250"))


def _point_to_segment_km(px, py, x1, y1, x2, y2):
    """Distance from a point to a LINE SEGMENT, in the units given.

    The segment, not the infinite line through it: a radar off the end of a
    short line is as far away as it is, and measuring to the line would drag
    in radars hundreds of kilometres past where anyone drew.
    """
    dx, dy = x2 - x1, y2 - y1
    span = dx * dx + dy * dy
    if span == 0:
        t = 0.0
    else:
        t = ((px - x1) * dx + (py - y1) * dy) / span
        t = max(0.0, min(1.0, t))          # clamp onto the segment
    nx, ny = x1 + t * dx, y1 + t * dy
    return ((px - nx) ** 2 + (py - ny) ** 2) ** 0.5


def radars_for_line(info, lon1, lat1, lon2, lat2, range_km=None):
    """Which radars in the frame can see any part of the line.

    Returns every radar with its distance to the line, nearest first, and a
    `within` flag - the caller wants the whole list to show, not just the
    survivors, because choosing between two overlapping radars is half the
    reason for having it.
    """
    if range_km is None:
        range_km = RADAR_RANGE_KM
    to_grid = _transformer(info["proj4"])
    x1, y1 = to_grid.transform(lon1, lat1)
    x2, y2 = to_grid.transform(lon2, lat2)

    out = []
    for radar in info["radars"]:
        rx, ry = to_grid.transform(radar["lon"], radar["lat"])
        km = _point_to_segment_km(rx, ry, x1, y1, x2, y2) / 1000.0
        out.append({"port": radar["port"],
                    "name": (radar["name"] or "").strip(),
                    "lon": radar["lon"], "lat": radar["lat"],
                    "distance_km": round(km, 1),
                    "within": km <= range_km})
    out.sort(key=lambda r: r["distance_km"])
    return out


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
