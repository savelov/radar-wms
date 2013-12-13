from datetime import datetime
from datetime import timedelta
import os
from db_setup import *
from configurator import set_logger
# set logger
logger = set_logger( "cleaner" )

def read_expiration_time(expiration_time_hours):
    "return expiration time utc timestamp"
    if expiration_time_hours==-1:
        expiration_time = None
    else:
        now = datetime.utcnow()
        expiration_time = now - timedelta(hours=expiration_time_hours)
    return expiration_time

def clean_up(dataset_name,expiration_time_in_hours):
    "clean up old datasets"
    logger.debug( "Start clean-up procedure for dataset %s" % dataset_name )
    # read cleanup expiration time from config
    logger.debug ("Clean up results older than %i hours" % expiration_time_in_hours )
    expiration_time = read_expiration_time(expiration_time_in_hours)
    radar_datasets = session.query(RadarDataset)\
            .filter(RadarDataset.name==dataset_name)\
            .filter(RadarDataset.timestamp<expiration_time)
    for item in radar_datasets.all():
        # delete file if it exists
        try:
            os.remove(item.geotiff_path)
        except OSError:
            pass
    logger.info ( "Removed %i results from dataset %s " % \
            (radar_datasets.count(), dataset_name ) )
    radar_datasets.delete()
    session.commit()
    logger.debug( "Clean-up procedure for dataset %s finished" % dataset_name )
