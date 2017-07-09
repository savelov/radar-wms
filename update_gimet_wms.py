#!/usr/bin/env python
import os
import ConfigParser
from datetime import datetime,timedelta

from db_setup import *
from cleaner import *

# read config
from configurator import *
tiff_dir_base = config.get("locations","wms_data_dir")

# set logger
logger = set_logger( "update_baltrad_wms" )

config_dataset_names,config_sections = get_sections_from_config()


def update(timestamp,projection,bbox,name):
        return_datasets=[]
	logger.debug( "Start updating of DB" )
#	name="gimet_dbz"
        # create dataset geotiff directory if it doesn't exist
        tiff_dir = "%s/%s" % (tiff_dir_base,name)
        if not os.path.exists(tiff_dir):
            logger.debug( "GeoTIFF directory does not exist. Create it." )
            os.makedirs(tiff_dir)

#        timestamp = datetime(2015,9,2,17,30)
        tiff_path = os.path.join( tiff_dir, name+"_%4d%02d%02d_%02d%02d.tiff" % (
	    timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute) )
	unit="dBZ"
	dataset_type="geotiff"
	style="Gimet_dbzh_style"
	title="GIMET reflectivity (dBZ)"

	radar_datasets = session.query(RadarDataset)\
                    .filter(RadarDataset.geotiff_path==tiff_path)\
                    .filter(RadarDataset.name==name)
            # continue with next file if result is already in DB
        if radar_datasets.count()>0:
                logger.debug ( "File %s already in database" % tiff_path )
		return None

        logger.info( "Add new dataset: %s:%s to DB." % (name,str(timestamp)) )
        add_datasets = [(
                    RadarDataset(
                        name = name,
                        timestamp = timestamp,
                        geotiff_path = tiff_path,
                        hdf_path = None,
                        projdef = projection,
                        bbox_original = str(bbox).strip('()'),
                        dataset_type = dataset_type,
                        unit = unit,
                        style = style,
                        title = title
                    )
                )]
        return_datasets.append({"name": name, 
                                        "timestamp": timestamp })
        session.add_all(add_datasets)
        session.commit()
	logger.info ( "Added %i results." % len(return_datasets) )
	logger.debug( "Updating of DB finished" )
	session.close()
	return return_datasets

def clear():
    for layer in ['gimet_phenomena','gimet_dbz','gimet_zdr','gimet_height','gimet_summ','gimet_precip','gimet_velocity', 
    'bufr_phenomena', 'bufr_height', 'bufr_dbz1','bufr_zdr1', 'bufr_summ12', 'bufr_vel1', 'bufr_vel2', 'bufr_vel3', 'bufr_vel4','bufr_precip',
    'bufr_vlad_phenomena', 'bufr_vlad_height', 'bufr_vlad_dbz1','bufr_vlad_zdr1', 'bufr_vlad_summ3','bufr_vlad_summ6','bufr_vlad_summ12', 'bufr_vlad_vel1', 'bufr_vlad_vel2', 'bufr_vlad_vel3', 'bufr_vlad_vel4','bufr_vlad_precip' ] :
        if not layer in config_dataset_names:
            continue
        else:
            section = config_sections[config_dataset_names.index(layer)]
            clean_up(config.get(section,"name"),
                     int( config.get(section,"cleanup_time") ))
