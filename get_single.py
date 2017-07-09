#!/usr/bin/env python
# script fetches FMI Open data and imports it to DB
from quicklock import singleton
singleton('get_single')

from db_setup import *
from cleaner import *
import ConfigParser
from configurator import *
import os.path


tiff_dir_base = config.get("locations","wms_data_dir")
api_key = config.get( "settings","fmi_api_key")

# set logger
logger = set_logger( "fmi_open" )

from datetime import datetime,timedelta
import os
import urllib2
from xml.etree import ElementTree
gml_namespace = "http://www.opengis.net/gml/3.2"

# sections in config file must match with layer names
wfs_layers = {
    'fmi_radar_single_dbz':
    'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=GetFeature&storedquery_id=fmi::radar::single::dbz',
    'fmi_radar_single_vrad':
    'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=GetFeature&storedquery_id=fmi::radar::single::vrad',
    'fmi_radar_single_etop_20':
    'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=GetFeature&storedquery_id=fmi::radar::single::etop_20',
    'fmi_radar_single_hclass':
    'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=GetFeature&storedquery_id=fmi::radar::single::hclass'

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
            response = urllib2.urlopen( wfs_url )
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
            query = urllib2.urlparse.urlparse(url).query
            query = query.split("&")
            for q in query:
                if q[0:4].lower()=="time":
                    time_value = q.split("=")[-1]
                elif q[0:3].lower()=="srs":
                    projdef = q.split("=")[-1]
                elif q[0:4].lower()=="bbox":
                    bbox = q.split("=")[-1]
                elif q[0:6].lower()=="layers":
                    radar_name = q.split("=")[-1]
                elif q[0:9].lower()=="elevation":
                    radar_elevation = q.split("=")[-1]
            timestamp = datetime.strptime(time_value,\
                    "%Y-%m-%dT%H:%M:%SZ")
            # search if dataset already exists
	    if (radar_name.split("_")[0] != "Radar:kesalahti") :
		continue
	    if (layer!='fmi_radar_single_etop_20' and float(radar_elevation) > 0.5) :
		continue
            output_filename = tiff_dir + "/" + radar_name.replace("Radar:","")+ time_value.replace(":","")\
                .replace("-","") + "_"+radar_elevation+ ".tif"
            # skip file fetching if it already exists
	    if os.path.isfile(output_filename):
		continue
            # save file to disk
            try:
                response = urllib2.urlopen( url )
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
