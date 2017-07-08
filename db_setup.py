#!/usr/bin/env python
# read config
from configurator import read_config
settings = read_config()

from sqlalchemy import *
from sqlalchemy.orm import *
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import StaticPool

from datetime import datetime

engine = create_engine( settings["db_uri"], echo=False,
                    connect_args={'check_same_thread':False},
                    poolclass=StaticPool)
Session = sessionmaker(bind=engine)
session = Session()

metadata = MetaData(engine)
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
        metadata.drop_all()
    except:
        pass

def create():
    metadata.create_all()

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
    answer = raw_input("Create new database? (y/[n]) ")
    if answer=="y":
        create()

