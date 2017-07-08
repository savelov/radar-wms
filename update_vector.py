#!/usr/bin/env python
import os
import ConfigParser
from datetime import datetime,timedelta

from sqlalchemy import exc

from vector_setup import *

# read config
from configurator import *

# set logger

config_dataset_names,config_sections = get_sections_from_config()


def update(timestamp,radar,distance,bearing,latitude,longitude):
        return_datasets=[]


        add_datasets = [(
                    VectorDataset(
                        radarcode = radar,
                        timestamp = timestamp,
			distance = distance,
			bearing = bearing,
			latitude = latitude,
			longitude = longitude
                    )
                )]
        session.add_all(add_datasets)
	try: 
    	    session.commit()
	except exc.IntegrityError:
	    print  " Can not insert duplicate vector" 
	except: 
	    print "Unexpected error:", sys.exc_info()[0]
	    raise

	session.close()
