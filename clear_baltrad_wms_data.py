#!/usr/bin/env python
from update_baltrad_wms import config_path, read_datasets
import ConfigParser
import os

# read config
config = ConfigParser.ConfigParser()
config.read( config_path )
datasets_file = config.get("locations","datasets")


for d in read_datasets():
    wms_datadir = config.get("locations","wms_data_dir") + "/" + d["name"]
    for filename in os.listdir(wms_datadir):
        os.remove(os.path.join(wms_datadir,filename))
    os.rmdir(wms_datadir)
print "Deleted wms files."

textfile = file(datasets_file,'wt')
textfile.close()
print "Cleared file %s." % (datasets_file)
