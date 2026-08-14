#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vertical cross sections over HTTP, out of the IMAGE engine.

The viewer has cut vertical sections for as long as it has had a map: click
twice and it slices down through the constant altitude products.  This serves
the same cut to a browser.  crosssect.c does the work - the three dimensional
interpolation, in physical values rather than in palette bytes - and
image_engine.py holds the engine for the worker's lifetime; this file is the
HTTP shape of it and nothing more.

  GET  /health
        Whether this worker has an archive, and what is in it.

  GET  /frames?limit=200
        Archive timestamps, newest first, each with the UTC of the same
        instant.  The .wrk headers are Moscow time and the WMS is UTC, so
        every frame is reported on both clocks: `archive` is what this API
        takes back as ?time=, `utc` is what a WMS TIME wants.  See
        ARCHIVE_UTC_OFFSET_HOURS in image_engine.py.

  GET  /info[?time=...]
        Grid geometry, projection, the radars in the frame, and which
        families can be cut through it.

  GET  /legend?family=dbz
        The colours and labels the map uses for that family.

  GET  /xsection?lon1=&lat1=&lon2=&lat2=&family=dbz[&time=][&format=json|png]
  POST /xsection   {"lon1": .., "lat1": .., "lon2": .., "lat2": .., ...}
        The section between two points.  json is the numbers, png is the
        picture in the map's own colours.

Plain WSGI, in the house style - baltrad_wms.wsgi and vector_wms.wsgi are the
same shape.  Flask is not in the venv and this does not need it.

DEPLOYMENT
----------
This app must have a mod_wsgi daemon group to itself, threads=1.  That is not
tuning, it is the engine's terms: one composite in C globals, and a working
directory it takes over for the process.  image_xsection_apache.conf is the
config that does it.  Sharing the radar_wms group instead - four processes,
fifteen threads - would have fifteen threads in one composite.

NOT TO BE CONFUSED WITH THE POLAR VOLUME CROSS SECTION
------------------------------------------------------
There is a second cross section service in this deployment, mounted at /api,
which reads ODIM HDF5 polar volumes out of pvol_cache with h5py and does its
own interpolation.  That one cuts through a single radar's sweeps; this one
cuts through the mosaic the C engine builds from the .wrk archive.  They
share a subject and nothing else - not a file, not a dependency, not a
process.  The image_ prefix on everything here is what keeps them apart on
disk, and the two projects are not merged.
"""

import json
import os
import sys
import traceback
from urllib.parse import parse_qs

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from image_engine import (ARCHIVE_UTC_OFFSET_HOURS, EngineError,  # noqa: E402
                          cell_to_lonlat, engine, utc_text)

#: Cutting a line longer than this is a request to interpolate across most of
#: the map, which is slow and says very little.  The grid is 6000 km across.
MAX_LENGTH_KM = 3000.0


# -- replies ---------------------------------------------------------------

#: Sent on every reply, not only on the preflight.  The Apache config sets
#: these too and the duplicate is harmless; setting them here as well is what
#: lets the app be correct when it is run any other way - the development
#: server, or behind a proxy that was not told about it.
CORS = [("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type")]


def _json(start_response, payload, status="200 OK", cache=None):
    body = json.dumps(payload, ensure_ascii=False,
                      default=str).encode("utf-8")
    headers = [("Content-Type", "application/json; charset=utf-8"),
               ("Content-Length", str(len(body)))]
    headers.append(("Cache-Control", cache or "no-cache"))
    start_response(status, headers + CORS)
    return [body]


def _error(start_response, message, status="400 Bad Request"):
    return _json(start_response, {"error": message}, status)


def _png(start_response, blob, cache=None):
    headers = [("Content-Type", "image/png"),
               ("Content-Length", str(len(blob))),
               ("Cache-Control", cache or "no-cache")]
    start_response("200 OK", headers + CORS)
    return [blob]


# -- request parsing -------------------------------------------------------

def _params(environ):
    """Query string and, for a POST, the JSON body folded on top of it.

    The frontend posts JSON because that is what the endpoint it replaces
    took; curl and a browser address bar want a query string.  Both work, and
    the body wins where they disagree.
    """
    out = {}
    for key, values in parse_qs(environ.get("QUERY_STRING", "")).items():
        out[key] = values[-1]

    if environ.get("REQUEST_METHOD", "GET").upper() == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > 0:
            raw = environ["wsgi.input"].read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise EngineError("the request body is not JSON")
            if not isinstance(body, dict):
                raise EngineError("the request body must be a JSON object")
            out.update(body)
    return out


def _float(params, name):
    try:
        return float(params[name])
    except KeyError:
        raise EngineError("%s is required" % name)
    except (TypeError, ValueError):
        raise EngineError("%s must be a number, not %r" % (name, params[name]))


def _time(params):
    """The requested frame time, or None for the newest.

    Anything ISO-8601-ish, which is what a browser sends: the trailing Z that
    fromisoformat did not accept until 3.11 is trimmed rather than depended
    on, because the production venv is not the one this was written against.
    """
    raw = params.get("time")
    if raw in (None, "", "latest"):
        return None
    import datetime
    text = str(raw).strip().replace("Z", "").replace(" ", "T")
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        raise EngineError("cannot read %r as a time - want 2026-08-10T21:50"
                          % raw)


# -- the endpoints ---------------------------------------------------------

def health(environ, start_response, params):
    state = engine().health()
    return _json(start_response, state,
                 "200 OK" if state.get("ok") else "503 Service Unavailable")


def frames(environ, start_response, params):
    try:
        limit = int(params.get("limit", 500))
    except (TypeError, ValueError):
        raise EngineError("limit must be a number")
    stamps = engine().frames(limit=max(1, min(limit, 5000)))
    # Two clocks, named.  `archive` is what this API takes back as ?time= and
    # what the .wrk headers say; `utc` is the same instant for the WMS TIME
    # dimension, which is UTC.  They are three hours apart in Moscow and would
    # be silently interchangeable-looking if either were called "time".
    return _json(start_response, {
        "count": len(stamps),
        "utc_offset_hours": ARCHIVE_UTC_OFFSET_HOURS,
        "frames": [{"archive": s.isoformat(), "utc": utc_text(s)}
                   for s in stamps],
    })


def info(environ, start_response, params):
    state = engine().info(when=_time(params))
    return _json(start_response, {
        "frame_time": state["frame_time"].isoformat(),
        "frame_time_utc": utc_text(state["frame_time"]),
        "utc_offset_hours": ARCHIVE_UTC_OFFSET_HOURS,
        "proj4": state["proj4"],
        "bbox": state["bbox"],
        "size": state["size"],
        "pixel_m": state["pixel_m"],
        "nodata": state["nodata"],
        "families": state["families"],
        "levels": state["levels"],
        "radars": state["radars"],
    })


def legend(environ, start_response, params):
    family = str(params.get("family", "dbz")).lower()
    rows = engine().legend(family=family, when=_time(params))
    return _json(start_response, {"family": family,
                                  "rows": _legend_rows(rows)})


def _legend_rows(rows):
    return [{"label": label, "color": "#%02x%02x%02x" % rgb}
            for label, rgb in rows]


def xsection(environ, start_response, params):
    lon1, lat1 = _float(params, "lon1"), _float(params, "lat1")
    lon2, lat2 = _float(params, "lon2"), _float(params, "lat2")
    family = str(params.get("family", "dbz")).lower()
    fmt = str(params.get("format", "json")).lower()
    smooth = str(params.get("smooth", "1")).lower() not in ("0", "false", "no")
    when = _time(params)

    # Which radars build the mosaic.  Left out, the engine takes every radar
    # within range of the line; given, it is the page saying which of the ones
    # it was offered to keep - the way to choose between two that overlap.
    ports = params.get("ports")
    if isinstance(ports, str):
        ports = [p for p in ports.replace(",", " ").split() if p]
    if ports is not None:
        try:
            ports = [int(p) for p in ports]
        except (TypeError, ValueError):
            raise EngineError("ports must be a list of port numbers, not %r"
                              % params.get("ports"))

    if fmt not in ("json", "png"):
        raise EngineError("format must be json or png, not %r" % fmt)

    section, meta = engine().cross_section(lon1, lat1, lon2, lat2,
                                           family=family, when=when,
                                           smooth=smooth,
                                           values=(fmt == "json"),
                                           ports=ports)

    if section.length_km > MAX_LENGTH_KM:
        raise EngineError("that line is %.0f km; %.0f km is the most this "
                          "will cut" % (section.length_km, MAX_LENGTH_KM))

    if fmt == "png":
        import tempfile
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        try:
            section.png(path)
            with open(path, "rb") as png_file:
                blob = png_file.read()
        finally:
            os.unlink(path)
        return _png(start_response, blob)

    # The engine hands out row 0 at the top, which is how a picture is stored.
    # A plot wants its y axis ascending, so the rows are turned over here and
    # altitude_km counts up with them - the two must be flipped together or
    # the section comes out upside down with the labels still the right way up.
    rows = section.value_rows()[::-1]
    step = section.top_km / (section.height - 1) if section.height > 1 else 0
    x1, y1, x2, y2 = meta["cells"]

    return _json(start_response, {
        "family": family,
        "units": section.units,
        "title": section.title,
        "frame_time": meta["frame_time"].isoformat(),
        "frame_time_utc": utc_text(meta["frame_time"]),
        "requested_time": params.get("time") or "latest",
        "levels": meta["family_levels"],
        "width": section.width,
        "height": section.height,
        "length_km": round(section.length_km, 1),
        "base_km": round(section.base_km, 2),
        "top_km": round(section.top_km, 2),
        # x axis: distance along the line.  y axis: altitude, ascending.
        "distance_km": [round(section.length_km * i / max(section.width - 1, 1), 2)
                        for i in range(section.width)],
        "altitude_km": [round(i * step, 3) for i in range(section.height)],
        "values": rows,
        # the lowest altitude the beam reaches at each step: below it the
        # section is empty because nothing looked, not because nothing was there
        "floor_km": [round(v, 3) for v in section.floor_km],
        "legend": _legend_rows(meta["legend"]),
        # every radar in the frame with its distance to the line, nearest
        # first, and whether it went into this mosaic.  The page shows the lot
        # so that a radar just outside the range can still be switched on.
        "radars": meta["radars_near"],
        "ports_used": meta["ports_used"],
        "lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2,
        "cells": [x1, y1, x2, y2],
        # where the cut actually landed, which is the centre of a 4 km cell
        # and not the point that was clicked
        "cut_from": cell_to_lonlat(meta, x1, y1),
        "cut_to": cell_to_lonlat(meta, x2, y2),
    })


ROUTES = {
    "": health,
    "health": health,
    "frames": frames,
    "info": info,
    "legend": legend,
    "xsection": xsection,
}


# -- WSGI ------------------------------------------------------------------

def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if method == "OPTIONS":            # the CORS preflight for the POST
        start_response("204 No Content", CORS + [("Content-Length", "0")])
        return [b""]

    if method not in ("GET", "POST"):
        return _error(start_response, "%s is not allowed here" % method,
                      "405 Method Not Allowed")

    name = environ.get("PATH_INFO", "").strip("/").split("/")[0].lower()
    handler = ROUTES.get(name)
    if handler is None:
        return _error(start_response,
                      "no such endpoint %r - try %s"
                      % (name, ", ".join(sorted(k for k in ROUTES if k))),
                      "404 Not Found")

    try:
        return handler(environ, start_response, _params(environ))
    except EngineError as error:
        # the caller asked for something the archive cannot answer: a family
        # the frame has no levels of, a time outside it, a line of no length
        return _error(start_response, str(error))
    except Exception:
        # Everything else is this code's fault, and the traceback goes to the
        # Apache error log rather than to whoever is holding the request.
        traceback.print_exc(file=environ.get("wsgi.errors", sys.stderr))
        return _error(start_response, "the cross section failed - see the "
                      "server log", "500 Internal Server Error")


# -- running it without Apache, for development ----------------------------

if __name__ == "__main__":
    import argparse
    from wsgiref.simple_server import make_server

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8052)
    args = parser.parse_args()

    print("cross sections on http://%s:%d/  (one thread: the engine's terms)"
          % (args.host, args.port))
    make_server(args.host, args.port, application).serve_forever()
