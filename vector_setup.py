#!/usr/bin/env python
# read config
from configurator import read_config
settings = read_config()

from sqlalchemy import *
from sqlalchemy.orm import *
from sqlalchemy.ext.declarative import declarative_base

from datetime import datetime

# The vector tables live in the same sqlite file as the radar datasets,
# so share the WAL-mode engines, sessions and the writer lock from
# db_setup instead of opening another pool on the same file:
# `session` is the writer (update_vector*.py), `read_session` is the
# query_only reader for vector_wms.wsgi.
from db_setup import (engine, session, read_engine, read_session,
                      write_lock, db_path)

# own metadata so create()/drop() only touch the vector tables
try:
    metadata = MetaData(engine) # SQLAlchemy 1.x
except Exception:
    metadata = MetaData()       # SQLAlchemy 2.x dropped bound metadata
Base = declarative_base(metadata=metadata)

class VectorDataset(Base):
    __tablename__ = "vector_dataset"
    id = Column(Integer, primary_key=True)
    radarcode = Column(String(5), nullable=False)
    timestamp = Column(DateTime,index=True)
    latitude = Column(Numeric)
    longitude = Column(Numeric)
    distance = Column(Numeric)
    bearing = Column(Numeric)
    uix = UniqueConstraint(radarcode, timestamp)

def drop():
    "use with care"
    try:
        metadata.drop_all(engine)
    except:
        pass

def create():
    metadata.create_all(engine)


if __name__ == '__main__':
    # fresh start
    answer = input("Erase all? (y/[n]) ")
    if answer=="y":
        drop()
    answer = input("Create new database? (y/[n]) ")
    if answer=="y":
        create()
