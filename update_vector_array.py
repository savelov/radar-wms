#!/usr/bin/env python
import os
import sys
import configparser
from datetime import datetime,timedelta

from sqlalchemy import exc

from vector_setup import *

# read config
from configurator import *

# set logger

config_dataset_names,config_sections = get_sections_from_config()


def update(timestamp,vector_array):
        return_datasets=[]
        add_datasets=[]


        for i in vector_array: 
            add_datasets.append(
                    VectorDataset(
                        radarcode = i["radar"],
                        timestamp = timestamp,
                        distance = i["distance"],
                        bearing = i["bearing"],
                        latitude = i["latitude"],
                        longitude = i["longitude"]
                    )
                )
        # single-writer discipline: serialize with the other pipeline scripts;
        # the whole array goes in as one transaction / one commit
        with write_lock():
            session.add_all(add_datasets)
            try:
                session.commit()
            except exc.IntegrityError:
                session.rollback()
                print  (" Can not insert duplicate vector" )
            except:
                print ("Unexpected error:", sys.exc_info()[0])
                raise

        session.close()
