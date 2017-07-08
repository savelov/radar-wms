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
        metadata.drop_all()
    except:
        pass

def create():
    metadata.create_all()


if __name__ == '__main__':
    # fresh start
    answer = raw_input("Erase all? (y/[n]) ")
    if answer=="y":
        drop()
    answer = raw_input("Create new database? (y/[n]) ")
    if answer=="y":
        create()

