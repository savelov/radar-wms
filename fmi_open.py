#!/usr/bin/env python
# script fetches FMI Open data and imports it to DB


from db_setup import *
from cleaner import *
import configparser
from configurator import *


tiff_dir_base = config.get("locations","wms_data_dir")
api_key = config.get( "settings","fmi_api_key")

# set logger
logger = set_logger( "fmi_open" )

from datetime import datetime,timedelta
import os
from urllib.request import urlopen,urlparse
from xml.etree import ElementTree
gml_namespace = "http://www.opengis.net/gml/3.2"

# sections in config file must match with layer names
wfs_layers = {
    'fmi_open_composite_dbz': 
    'http://opendata.fmi.fi/wfs?request=GetFeature&storedquery_id=fmi::radar::composite::dbz',
    'fmi_open_composite_rr1h':
    'http://opendata.fmi.fi/wfs?request=GetFeature&storedquery_id=fmi::radar::composite::rr1h',
    'fmi_open_composite_rr24h':
    'http://opendata.fmi.fi/wfs?request=GetFeature&storedquery_id=fmi::radar::composite::rr24h',
    'fmi_open_composite_rr':
    'http://opendata.fmi.fi/wfs?request=GetFeature&storedquery_id=fmi::radar::composite::rr'
}


config_dataset_names,config_sections = get_sections_from_config()

def update():
    add_datasets = []
    return_datasets = []
    logger.debug( "Start updating of DB" )
    for layer in wfs_layers:
        if not layer in config_dataset_names:
            continue
        else:
            logger.debug( "Found layer %s from config" % layer )
            section = config_sections[config_dataset_names.index(layer)]
        # check that tiff directory exists
        tiff_dir = "%s/%s" % (tiff_dir_base,layer)
        if not os.path.exists(tiff_dir):
            logger.debug( "GeoTIFF directory does not exist. Create it." )
            os.makedirs(tiff_dir)
        # get WFS to get WMS urls
        try:
            wfs_url = wfs_layers[layer].replace("{key}",api_key) 
            response = urlopen( wfs_url )
            logger.debug( "Data from url %s fetched" % wfs_url )
        # ignore network related problems
        except:
            logger.error( "Network error occurred while fetching url %s" % wfs_url )
            continue
        logger.debug( "Parse WFS response for layer %s" % layer )
        wfs_response = ElementTree.fromstring(response.read())
        file_references = wfs_response.findall('.//{%s}fileReference' % gml_namespace)
        for ref in file_references:
            url = ref.text
            query = urlparse(url).query
            query = query.split("&")
            for q in query:
                if q[0:4].lower()=="time":
                    time_value = q.split("=")[-1]
                elif q[0:3].lower()=="srs":
                    projdef = q.split("=")[-1]
                elif q[0:4].lower()=="bbox":
                    bbox = q.split("=")[-1]
            timestamp = datetime.strptime(time_value,\
                    "%Y-%m-%dT%H:%M:%SZ")
            if ( timestamp<read_expiration_time(int( config.get(section,"cleanup_time") )) ):
                # do not store old files
                logger.debug ( "Skip expired dataset %s:%s" % (layer,str(timestamp)))
                continue
            # search if dataset already exists
            radar_datasets = session.query(RadarDataset)\
                    .filter(RadarDataset.timestamp==timestamp)\
                    .filter(RadarDataset.name==layer)
            # skip file fetching if it already exists
            if radar_datasets.count()>0:
                logger.debug ( "Dataset %s:%s already in database" % (layer,str(timestamp) ) )
                continue
            output_filename = tiff_dir + "/" + time_value.replace(":","")\
                    .replace("-","") + ".tif"
            # save file to disk
            try:
                response = urlopen( url )
                logger.debug( "Fetched data from url %s" % url )
            # ignore network related problems
            except:
                logger.error( "Network error or invalid api-key occurred while fetching url %s" % url )
                continue
            f = open(output_filename,"wb")
            f.write( response.read() )
            f.close()
            # import dataset to db
            logger.info( "Add new dataset: %s:%s to DB." % (layer,str(timestamp)) )
            add_datasets.append(
                RadarDataset(
                    name = layer,
                    timestamp = timestamp,
                    geotiff_path = output_filename,
                    projdef = projdef,
                    bbox_original = bbox,
                    dataset_type = config.get(section,"dataset_type"),
                    unit = config.get(section,"unit"),
                    style = config.get(section,"style"),
                    title = config.get(section,"title")
                )
            )
            return_datasets.append({"name": layer, 
                                    "timestamp": timestamp })
    # finally add new datasets to DB
    if (len(add_datasets)>0):
        session.add_all(add_datasets)
        session.commit()
    logger.info ( "Added %i results." % len(add_datasets) )
    logger.debug( "Updating of DB finished" )
    session.close()
    return return_datasets

if __name__ == '__main__':
    update()
    # delete old
    for layer in wfs_layers:
        if not layer in config_dataset_names:
            continue
        else:
            section = config_sections[config_dataset_names.index(layer)]
            clean_up(config.get(section,"name"),
                     int( config.get(section,"cleanup_time") ))
