#!/usr/bin/env python

config_path = "/home/user/baltrad/baltrad_wms/baltrad_wms.cfg"

#
# do not edit anything below
#

import mapscript
import ConfigParser

config = ConfigParser.ConfigParser()
config.read( config_path )

def read_config(tools=False):
    # read config
    datasets = ConfigParser.ConfigParser()
    datasets.read( config.get("locations","datasets") )
    mapfile_path = config.get("locations","mapfile")
    sections = datasets.sections()
    sections.sort()
    if tools:
        tmpdir = config.get("locations","tmpdir")
        online_resource = config.get("locations","online_resource")
        return sections, datasets, tmpdir, online_resource
    else:
        return sections, datasets, mapfile_path

def wms_request(mapfile_path,req,sections,datasets):
    map_object = mapscript.mapObj( mapfile_path )
    request_type = req.getValueByName("REQUEST")
    time_value = req.getValueByName("TIME")
    # only one layer allowed
    if req.getValueByName("LAYERS")!=None:
        layer = map_object.getLayerByName(req.getValueByName("LAYERS"))
    else:
        layer = map_object.getLayerByName(config.get("dataset_1","name"))
        layer2 = map_object.getLayerByName(config.get("dataset_2","name"))

    if "capabilities" in request_type.lower():
        # set online resource
        map_object.web.metadata.set("wms_onlineresource", config.get("locations","online_resource") )
        projdef = datasets.get(sections[-1],"projdef")
        # write timestamps
        sections.reverse() # newest first
        layer.metadata.set("wms_timeextent", ",".join(sections))
        layer.metadata.set("wms_timedefault", sections[0])
        if layer2:
            layer2.metadata.set("wms_timeextent", ",".join(sections))
            layer2.metadata.set("wms_timedefault", sections[0])
            layer2.setProjection( projdef )
            layer2.data = datasets.get(sections[-1], layer2.name)
        # just a dummy dataset
        tiff_path = datasets.get(sections[-1], layer.name) # last one
    elif time_value not in (None,"-1",""):
        tiff_path = datasets.get(time_value,layer.name)
        projdef = datasets.get(time_value,"projdef")
    else:
        tiff_path = datasets.get(sections[-1], layer.name) # last one
        projdef = datasets.get(sections[-1],"projdef")
    layer.data = tiff_path
    layer.setProjection( projdef )
    opacity = req.getValueByName("OPACITY")
    if opacity:
        if opacity.isdigit():
            layer.opacity = int(opacity)
    # getfeatureinfo request
    if request_type=="GetFeatureInfo":
        layer.template = "featureinfo.html"
    return map_object

if __name__ == '__main__': # CGI
    sections, datasets, mapfile_path = read_config()
    req = mapscript.OWSRequest()
    req.loadParams()
    #text = ""
    #for i in range(req.NumParams):
    #    text += " %s=%s " % (req.getName(i),req.getValue(i))
    #raise NameError (text)
    map_object = wms_request(mapfile_path,req,sections,datasets)
    # dispatch
    map_object.OWSDispatch( req )
