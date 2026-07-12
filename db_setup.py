#!/usr/bin/env python3
# read config
from configurator import read_config
settings = read_config()

from sqlalchemy import *
from sqlalchemy import event
from sqlalchemy.orm import *
from sqlalchemy.ext.declarative import declarative_base

from datetime import datetime
from contextlib import contextmanager
import fcntl

# filesystem path of the sqlite database (used for the writer lock and
# for cache invalidation on the WMS side)
db_path = settings["db_uri"].split("///")[-1]

def make_engine(readonly=False):
    """Create a WAL-mode engine.

    WAL lets N readers run concurrently with 1 writer: readers never block
    the writer and vice versa. The default QueuePool gives every WSGI thread
    its own connection (the old StaticPool serialized all threads on one).
    Read-only engines additionally get query_only so a WMS request can never
    accidentally write.
    """
    engine = create_engine(settings["db_uri"], echo=False,
                        pool_pre_ping=True,
                        connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_con, _):
        cur = dbapi_con.cursor()
        if readonly:
            # journal_mode is a persistent property of the DB file and
            # switching it writes to the header — only the writer sets it
            cur.execute("PRAGMA query_only=ON")
        else:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return engine

# writer engine/session: default, used by the updater scripts
# (update_gimet_wms.py, update_baltrad_wms.py, fmi_open.py, cleaner.py, ...)
engine = make_engine()
session = scoped_session(sessionmaker(bind=engine))

# reader engine/session: used by the WMS request handlers
# (baltrad_wms.py, baltrad_wms_tools). Call read_session.remove() at the end
# of every request — a leaked read transaction pins the WAL file and blocks
# checkpointing.
read_engine = make_engine(readonly=True)
read_session = scoped_session(sessionmaker(bind=read_engine))

@contextmanager
def write_lock():
    """Serialize the DB-writing phase across pipeline processes.

    WAL allows many readers plus one writer, not concurrent writers; hold
    this lock around the query-check + insert/delete + commit phase of any
    script that writes.
    """
    lock_file = open(db_path + ".lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()

try:
    metadata = MetaData(engine) # SQLAlchemy 1.x
except Exception:
    metadata = MetaData()       # SQLAlchemy 2.x dropped bound metadata
Base = declarative_base(metadata=metadata)

class RadarDataset(Base):
    __tablename__ = "radar_dataset"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), index=True)
    title = Column(String(300), nullable=False)
    timestamp = Column(DateTime,index=True)
    geotiff_path = Column(String(500),nullable=False)
    hdf_path = Column(String(500))
    projdef = Column(String(150))
    bbox_original = Column(String(150))
    unit = Column(String(100),nullable=False)
    dataset_type = Column(String(10))
    style = Column(String(50))

def drop():
    "use with care"
    try:
        metadata.drop_all(engine)
    except:
        pass

def create():
    metadata.create_all(engine)

def insert_stations_to_db(values=None):
    "stations db must be dropped"
    if not values:
        values = get_values()
    records = []
    for station_id in values.keys():
        point = "POINT(%s %s)" % (values[station_id]["lon"],values[station_id]["lat"])
        geom = WKTSpatialElement(point,4326)
        records.append(Station(id=int(station_id),geom=geom,name=values[station_id]["name"]))
    session.add_all(records)
    session.commit()

if __name__ == '__main__':
    # fresh start
    #answer = raw_input("Erase all? (y/[n]) ")
    #if answer=="y":
    #    drop()
    answer = input("Create new database? (y/[n]) ")
    if answer=="y":
        create()
