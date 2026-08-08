#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drive the IMAGE C compositor instead of pycao.

Does what generate_bufr_archive_test.py does - walk a window of observation
times, store each radar's feature motion vector, write a GeoTIFF per product
and register it with the WMS - but through the C engine, which already reads
the .wrk archive and mosaics it.  Nothing is spawned: pyimage drives
libimage.so in process.

    ./generate_image_archive.py                       the last full 10 minutes
    ./generate_image_archive.py --from 2026-07-28T00:00 --to 2026-07-28T01:00
    ./generate_image_archive.py --dry-run             touch no database

THE PROJECTION
--------------
This is the one thing that has to be right, or the WMS places the raster in
the wrong part of the world.

update_gimet_wms.update() stores whatever `projection` it is given as the
dataset's projdef, next to bbox_original, and the WMS reprojects from those.
So they must describe the GeoTIFF as it actually is - not the frame some
other pipeline happens to use.

generate_bufr_archive_test.py passes russia_proj_str, correct there because
pycao *renders into* that projection.  The C engine does not: it mosaics in
the equidistant conic its config defines, centred on CenterX/CenterY in
config/image.cfg, and writes the grid untouched.  So the projdef here comes
from the engine itself, frame.info["proj4"], and never from a constant in
this file.  The bbox comes from the same place and is in that projection's
metres.

If a consumer needs the pycao frame, reproject the file rather than lying
about it in the database:

    gdalwarp -t_srs '+proj=sterea +lat_0=50 +lon_0=100' -r near in.tif out.tif

-r near because the band holds palette indices, not intensities.
"""

import argparse
import datetime
import os
import sys

# Where the viewer lives, and so pyimage and libimage.so with it.  $IMAGE_HOME
# wins; otherwise try the usual checkout names.  Once pyimage is imported the
# question is settled - IMAGE_HOME below is taken from the module that was
# actually found, so there is one answer and not two to keep in step.
for _candidate in filter(None, [os.environ.get("IMAGE_HOME"),
                                os.path.expanduser("~/imagegcc"),
                                os.path.expanduser("~/image")]):
    if os.path.isfile(os.path.join(_candidate, "pyimage.py")):
        sys.path.insert(0, _candidate)
        break

try:
    import pyimage                                          # noqa: E402
except ImportError:
    sys.exit("cannot find pyimage.py - set IMAGE_HOME to the imagegcc checkout")

IMAGE_HOME = os.path.dirname(os.path.abspath(pyimage.__file__))

# Imported lazily: they pull in the database and the production config, which
# a --dry-run has no business needing.  Checking that the projection and the
# extent come out right should not require a database to be reachable.
_db = {}


def db():
    if not _db:
        from update_gimet_wms import update, tiff_dir_base
        import update_vector
        _db["update"] = update
        _db["tiff_dir_base"] = tiff_dir_base
        _db["update_vector"] = update_vector
    return _db


#: WMS dataset name -> the product pyimage should mosaic.  The names on the
#: left are what the WMS serves; the ones on the right are pyimage.PRODUCTS.
PRODUCTS = {
    "bufr_dbz1": "dbz1",
}

#: update_vector keys a vector on radarcode, and the existing pipeline passes
#: the bulletin letters (locator.dmrl_letters).  header.wrk carries the display
#: name instead, so map the ones that differ or the rows will not line up with
#: what generate_bufr_archive_test.py wrote.
RADAR_CODE = {
    "СмоленскДМРЛ": "RUSM",
    "Валдай": "RUVD",
}


def frame_path(name, when, tiff_dir_base):
    """Where update() will look for the GeoTIFF.

    It builds this path itself from wms_data_dir and does not take one, so the
    file has to be written exactly here or the row points at nothing.
    """
    return os.path.join(tiff_dir_base, name,
                        "%s_%04d%02d%02d_%02d%02d.tiff"
                        % (name, when.year, when.month, when.day,
                           when.hour, when.minute))


def store_vectors(frame, dry_run):
    stored = 0
    for radar in frame.radars:
        if not radar.moving:            # speed 0 with azimuth 511 = none given
            continue
        code = RADAR_CODE.get(radar.name, radar.name)
        print("    vector %-8s %.2fE %.2fN  %.0f km/h bearing %d"
              % (code, radar.lon, radar.lat, radar.speed_kmh, radar.azimuth_deg))
        if not dry_run:
            db()["update_vector"].update(frame.timestamp, code,
                                         radar.speed_kmh / 3.6,
                                         radar.azimuth_deg,
                                         radar.lat, radar.lon)
        stored += 1
    return stored


def store_product(frame, name, product, dry_run, tiff_dir):
    try:
        frame.load(product)
    except pyimage.ImageError as error:
        print("    %-12s skipped: %s" % (name, error))
        return False

    path = frame_path(name, frame.timestamp, tiff_dir)
    if not dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    info = frame.geotiff(path) if not dry_run else frame.info

    # The projection and extent of the file just written, from the engine.
    # bbox must be a tuple: update() stores str(bbox).strip('()'), which only
    # gives the "x1, y1, x2, y2" the WMS parses if it is not a list.
    bbox = tuple(info["bbox"])
    print("    %-12s %s  %s" % (name, os.path.basename(path), info["proj4"]))
    print("                 bbox %s" % (bbox,))
    if not dry_run:
        db()["update"](frame.timestamp, info["proj4"], bbox, name)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paths", default=os.path.join(IMAGE_HOME, "paths"),
                    help="the viewer's path file (default: %(default)s)")
    ap.add_argument("--from", dest="start", help="YYYY-MM-DDTHH:MM (UTC)")
    ap.add_argument("--to", dest="end", help="YYYY-MM-DDTHH:MM (UTC)")
    ap.add_argument("--step", type=int, default=10, help="minutes between frames")
    ap.add_argument("--tiff-dir", help="override wms_data_dir (dry runs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written, touch nothing")
    args = ap.parse_args()

    if args.start:
        start = datetime.datetime.fromisoformat(args.start)
        end = (datetime.datetime.fromisoformat(args.end) if args.end
               else start + datetime.timedelta(minutes=args.step))
    else:
        now = (datetime.datetime.now(datetime.timezone.utc)
               .replace(tzinfo=None) - datetime.timedelta(minutes=args.step))
        start = now.replace(minute=now.minute - now.minute % args.step,
                            second=0, microsecond=0)
        end = start + datetime.timedelta(minutes=args.step)

    tiff_dir = args.tiff_dir or (db()["tiff_dir_base"] if not args.dry_run
                                 else "<wms_data_dir>")
    step = datetime.timedelta(minutes=args.step)
    print("%s .. %s every %d min%s"
          % (start, end, args.step, "  (dry run)" if args.dry_run else ""))

    written = vectors = 0
    with pyimage.Archive(args.paths) as archive:
        print("archive: %d frames, %s .. %s"
              % (len(archive.frames), archive.frames[0].timestamp,
                 archive.frames[-1].timestamp))
        when = start
        while when < end:
            frame = archive.nearest(when)
            # nearest() always returns something; refuse one from another hour
            # rather than filing it under a time it does not belong to
            if abs(frame.timestamp - when) > step:
                print("  %s: no frame within %d min (closest %s)"
                      % (when, args.step, frame.timestamp))
                when += step
                continue

            print("  %s -> frame %s (%d radars)"
                  % (when, frame.timestamp, len(frame.ports)))
            for name, product in sorted(PRODUCTS.items()):
                if store_product(frame, name, product, args.dry_run, tiff_dir):
                    written += 1
            vectors += store_vectors(frame, args.dry_run)
            when += step

    print("%d rasters, %d vectors%s"
          % (written, vectors, " (dry run, nothing stored)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
