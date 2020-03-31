#!/usr/bin/env python
import os
import configparser
from datetime import datetime,timedelta

from h5togeotiff import h5togeotiff,H5ConversionSkip
from db_setup import *
from cleaner import *

# read config
from configurator import *
h5_dir = config.get("locations","baltrad_data_dir")
tiff_dir_base = config.get("locations","wms_data_dir")

# set logger
logger = set_logger( "update_baltrad_wms" )

def read_hdf_datasets():
    config_datasets = []
    datasets = []
    logger.debug( "Read HDF5 datasets from DB" )
    for section in config.sections():
        if "dataset" in section:
            config_datasets.append(section)
    for dset in config_datasets:
        if config.get(dset,"dataset_type")!="hdf":
            continue
        dataset = {}
        for key in ("name","unit","dataset_type","hdf_dataset","style","title", "cleanup_time"):
            dataset[key] = config.get(dset,key).strip()
        datasets.append(dataset)
    logger.debug ( "Found %i HDF5 datasets from DB" % len(datasets) )
    return datasets

def update():
    # Only valid for BALTRAD HDF type datasets!
    logger.debug( "Start updating of DB" )
    return_datasets = []
    for d in read_hdf_datasets():
        # create dataset geotiff directory if it doesn't exist
        tiff_dir = "%s/%s" % (tiff_dir_base,d["name"])
        if not os.path.exists(tiff_dir):
            logger.debug( "GeoTIFF directory does not exist. Create it." )
            os.makedirs(tiff_dir)
        h5_files = os.listdir( h5_dir )
        tiff_files = os.listdir( tiff_dir )
        # search for new datasets
        for h5_file in h5_files:
            if d["dataset_type"]!="hdf":
                logger.warn( "%s is not HDF5 file. Skip it" % h5_file )
                continue
            # read cleanup time
            exp_time = read_expiration_time(int(d["cleanup_time"]))
            # search if hdf5 dataset already exists
            radar_datasets = session.query(RadarDataset)\
                    .filter(RadarDataset.hdf_path==h5_file)\
                    .filter(RadarDataset.name==d["name"])
            # continue with next file if result is already in DB
            if radar_datasets.count()>0:
                logger.debug ( "File %s already in database" % h5_file )
                continue
            basename = os.path.splitext( h5_file )[0]
            tiff_path = os.path.join( tiff_dir, basename+".tif")
            if not os.path.isfile( tiff_path ):
                if d["unit"]=="dBZ":
                    data_type = "int"
                else:
                    data_type = "float"
                try:
                    try:
                        logger.debug ( "Convert file %s from HDF5 to GeoTIFF" % h5_file )
                        geotiff = h5togeotiff( os.path.join( h5_dir, h5_file ), \
                                tiff_path, d["hdf_dataset"], data_type,exp_time)
                    except H5ConversionSkip as skipped:
                        logger.info ( skipped.message )
                        continue
                except IOError:
                    # ignore broken files 
                    logger.error ( "Broken file detected: %s" % tiff_path )
                    continue
                timestamp = datetime.strptime(geotiff["timestamp"],\
                        "%Y-%m-%dT%H:%MZ")
                logger.info( "Add new dataset: %s:%s to DB." % (d["name"],str(timestamp)) )
                add_datasets = [(
                    RadarDataset(
                        name = d["name"],
                        timestamp = timestamp,
                        geotiff_path = tiff_path,
                        hdf_path = os.path.join( h5_dir, h5_file ),
                        projdef = geotiff["projection"],
                        bbox_original = geotiff["bbox_original"],
                        dataset_type = d["dataset_type"],
                        unit = d["unit"],
                        style = d["style"],
                        title = d["title"]
                    )
                )]
                return_datasets.append({"name": d["name"], 
                                        "timestamp": timestamp })
                session.add_all(add_datasets)
                session.commit()
                os.remove(os.path.join( h5_dir, h5_file ))
            else:
                logger.debug ( "File %s already in database. Skip it" % h5_file )
    logger.info ( "Added %i results." % len(return_datasets) )
    logger.debug( "Updating of DB finished" )
    return return_datasets

if __name__ == '__main__':
    dsets = update()
    for d in read_hdf_datasets():
        clean_up(d["name"],int(d["cleanup_time"]))
    session.close()
