#!/usr/bin/env python

config_path = "/home/tvp/baltrad/baltrad_wms/baltrad_wms.cfg"

#
# do not edit anything below
#

import os
import ConfigParser
from datetime import datetime

from h5togeotiff import h5togeotiff

# read config
config = ConfigParser.ConfigParser()
config.read( config_path )
datasets = ConfigParser.ConfigParser()
datasets.read( config.get("locations","datasets") )

h5_dir = config.get("locations","baltrad_data_dir")
tiff_dir_base = config.get("locations","wms_data_dir")

def read_datasets():
    hdf_datasets = []
    for i in (1,2):
        try:
            hdf_datasets.append({"hdf_dataset" : config.get("dataset_%i" % i,"hdf_dataset"),
                                 "name":  config.get("dataset_%i" % i,"name"),
                                 "unit": config.get("dataset_%i" % i,"unit")})
        except ConfigParser.NoSectionError:
            pass
    return hdf_datasets

def update():
    for d in read_datasets():
        tiff_dir = "%s/%s" % (tiff_dir_base,d["name"])
        if not os.path.exists(tiff_dir):
            os.makedirs(tiff_dir)
        h5_files = os.listdir( h5_dir )
        tiff_files = os.listdir( tiff_dir )
        # search for new datasets
        for h5_file in h5_files:
            basename = os.path.splitext( h5_file )[0]
            tiff_path = os.path.join( tiff_dir, basename+".tif")
            if not os.path.isfile( tiff_path ):
                try:
                    if d["unit"]=="dBZ":
                        data_type = "int"
                    else:
                        data_type = "float"
                    geotiff = h5togeotiff( os.path.join( h5_dir, h5_file ), tiff_path, d["hdf_dataset"], data_type)
                except KeyError:
                    continue
                dataset_name = geotiff["timestamp"]
                try: # if already exists, add only new parameter
                    datasets.set(dataset_name,d["name"],tiff_path)
                except ConfigParser.NoSectionError: # create new
                    datasets.add_section(dataset_name)
                    datasets.set(dataset_name,"projdef",geotiff["projection"])
                    datasets.set(dataset_name,d["name"],tiff_path)
                    datasets.set(dataset_name,"bbox",geotiff["bbox"])
                datasets.write(  open(config.get("locations","datasets"),"w") )

        # deprecate old datasets
        for tiff_file in tiff_files:
            basename = os.path.splitext( tiff_file )[0]
            h5_path = os.path.join( h5_dir, basename+".h5" )
            if not os.path.isfile( h5_path ):
                tiff_path = os.path.join( tiff_dir, tiff_file )
                os.remove( tiff_path )
                for timestamp in datasets.sections():
                    if datasets.get(timestamp,d["name"])==tiff_path:
                        datasets.remove_section(timestamp)
                        break
                datasets.write( open(config.get("locations","datasets"),"w") )

if __name__ == '__main__':
    update()

