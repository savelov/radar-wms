#!/usr/bin/env python
from configurator import read_config,config
import configparser
import os
from db_setup import drop

# read config
settings = read_config()
datasets = []
for section in config.sections():
    if "dataset" in section:
        datasets.append(config.get(section,"name"))

for d in datasets:
    wms_datadir = config.get("locations","wms_data_dir") + "/" + d
    try:
        for filename in os.listdir(wms_datadir):
            os.remove(os.path.join(wms_datadir,filename))
        os.rmdir(wms_datadir)
    except OSError:
        pass
print ("Deleted wms files.")
drop()
print ("Cleared DB")
