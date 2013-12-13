#!/usr/bin/env python
# MODIFY THIS
config_path = "/home/user/baltrad-wms/baltrad_wms.cfg"
#


import ConfigParser
config = ConfigParser.ConfigParser()
config.read( config_path )

import logging
import sys

def read_config(tools=False):
    # read config
    settings = {}
    settings["mapfile_path"] = config.get("locations","mapfile")
    settings["db_uri"] = config.get("locations","db_uri")
    settings["enable_contour_maps"] = eval(config.get("settings",\
            "enable_countour_maps").capitalize())
    if tools:
        settings["tmpdir"] = config.get("locations","tmpdir")
        settings["online_resource"] = config.get("locations","online_resource")
    return settings 

def get_sections_from_config():
    config_dataset_names = []
    config_sections = []
    for section in config.sections():
        if "dataset" in section:
            config_dataset_names.append(config.get(section,"name"))
            config_sections.append(section)
    return config_dataset_names,config_sections

def set_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel ( eval("logging." + config.get("logging","level").upper() ) )
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel ( eval("logging." + config.get("logging","level").upper() ) )
    frmt =  logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ch.setFormatter ( frmt )
    logger.addHandler ( ch )
    return logger
