#!/usr/bin/env python
# read config
import ConfigParser
from configurator import *
settings = read_config()

from db_setup import *
import mapscript

def get_query_layer(layer_name):
    if "_contour" in layer_name:
        layer_name = layer_name.replace("_contour","")
    return layer_name

def wms_request(req,settings):
    map_object = mapscript.mapObj( settings["mapfile_path"] )
    request_type = req.getValueByName("REQUEST")
    if request_type==None:
        raise Exception ( "WMS parameter request is missing!" )
    time_value = req.getValueByName("TIME")
    opacity = req.getValueByName("OPACITY")
    layers = {}
    contour = settings["enable_contour_maps"]
    if req.getValueByName("LAYERS")!=None:
        layers_list = req.getValueByName("LAYERS").split(",")
    elif req.getValueByName("LAYER")!=None: #legend
        layers_list = [req.getValueByName("LAYER")]
    else:
        layers_list = None
    # create layers
    config_dataset_names,config_sections = get_sections_from_config()
    for dataset_name in config_sections:
        new_layer_name = config.get(dataset_name, "name")
        new_layer_title = config.get(dataset_name, "title")
        # do not write styles for layers that are not queried
        if layers_list:
            if (not new_layer_name in layers_list and\
                not new_layer_name+"_contour" in layers_list):
                continue
        if contour:
            layer_names = (new_layer_name,new_layer_name+"_contour")
        else:
            layer_names = (new_layer_name,)
        for l_name in layer_names:
            processing = []
            layers[l_name] = mapscript.layerObj(map_object)
            layers[l_name].name = l_name
            if "_contour" in l_name:
                layers[l_name].type = mapscript.MS_LAYER_LINE
                layers[l_name].connectiontype = mapscript.MS_CONTOUR
                new_layer_title += " contour"
                layers[l_name].addProcessing( "CONTOUR_INTERVAL=0" )
                layers[l_name].addProcessing( "CONTOUR_ITEM=pixel" )
                layers[l_name].setGeomTransform( "smoothsia([shape], 5)" )
            else:
                layers[l_name].type = mapscript.MS_LAYER_RASTER
                layers[l_name].classitem = "[pixel]"
            layers[l_name].status = mapscript.MS_ON
            if str(opacity).isdigit():
                layers[l_name].setOpacity(int(opacity))
            else:
                layers[l_name].setOpacity(70) # default opacity
            try: # old mapserver
                layers[l_name].metadata.set("wms_title", new_layer_title)
                layers[l_name].metadata.set("wms_timeitem", "TIFFTAG_DATETIME")
            except AttributeError: # new mapserver
                layers[l_name].setMetaData("wms_title", new_layer_title)
                layers[l_name].setMetaData("wms_timeitem", "TIFFTAG_DATETIME")
            layers[l_name].template = "featureinfo.html"
            # set style class
            class_name_config = config.get(dataset_name, "style")
            config_items = config.items ( class_name_config )
            config_items.sort()
            for class_values in config_items:
                item = class_values[1].split (",")
                c =  mapscript.classObj( layers[l_name] )
                style = mapscript.styleObj(c)
                c.setExpression( "([pixel] > %s AND [pixel] <= %s)" % (item[1],item[2]) )
                if "_contour" in l_name:
                    processing.append(item[1])
                    style.width = 2     
                    style.color.setRGB( 0,0,0 )
                else:
                    c.name = class_values[0]
                    c.title = item[0]
                    colors = map(int,item[3:6])
                    style.color.setRGB( *colors )
            if "_contour" in l_name:
                processing.reverse()
                layers[l_name].type = mapscript.MS_LAYER_LINE
                layers[l_name].addProcessing( "CONTOUR_LEVELS=%s" % ",".join(processing) )
    if "capabilities" in request_type.lower():
        # set online resource
        try: # old mapserver
            map_object.web.metadata.set("wms_onlineresource", \
                    config.get("locations","online_resource") )
        except AttributeError: # new mapserver
            map_object.setMetaData("wms_onlineresource", \
                    config.get("locations","online_resource") )
        # write timestamps
        for layer_name in layers.keys():
            if contour:
                layer_types = ("","_contour")
            else:
                layer_types = ("",)
            for layer_type in layer_types:
                radar_datasets = session.query(RadarDataset)\
                        .filter(RadarDataset.name==layer_name)\
                        .order_by(RadarDataset.timestamp.desc()).all()
                radar_timestamps = []
                for r in radar_datasets:
                    radar_timestamps.append(r.timestamp.strftime("%Y-%m-%dT%H:%M:00Z"))
                if len(radar_timestamps)==0:
                    continue
                try: # old mapserver
                    layers[layer_name+layer_type].metadata.set("wms_timeextent", ",".join(radar_timestamps))
                    layers[layer_name+layer_type].metadata.set("wms_timedefault", radar_timestamps[0])
                except AttributeError: # new mapserver
                    layers[layer_name+layer_type].setMetaData("wms_timeextent", ",".join(radar_timestamps))
                    layers[layer_name+layer_type].setMetaData("wms_timedefault", radar_timestamps[0])
                # setup projection definition
                projdef = radar_datasets[0].projdef
                if not "epsg" in projdef:
                    projdef = "epsg:3785" # quite near default settings, affects only bounding boxes
                layers[layer_name+layer_type].setProjection( projdef )
                layers[layer_name+layer_type].data = radar_datasets[0].geotiff_path
                bbox = radar_datasets[0].bbox_original
                bbox = map(float, bbox.split(","))
                layers[layer_name+layer_type].setExtent( *bbox )
    elif time_value not in (None,"-1",""):
        # dataset is a combination of timetamp and layer name
        time_object = datetime.strptime(time_value,"%Y-%m-%dT%H:%M:00Z")
        for layer_name in layers_list:
            radar_dataset = session.query(RadarDataset)\
                    .filter(RadarDataset.name==get_query_layer(layer_name))\
                    .filter(RadarDataset.timestamp==time_object).one()
            layers[layer_name].data = radar_dataset.geotiff_path
            layers[layer_name].setProjection( radar_dataset.projdef )
            # lon/lat bbox
            bbox =  map(float,radar_dataset.bbox_original.split(",") )
            layers[layer_name].setExtent( *bbox )
    else:
        for layer_name in layers_list:
            # get newest result if timestamp is missing
            radar_dataset = session.query(RadarDataset)\
                    .filter(RadarDataset.name==get_query_layer(layer_name))\
                    .order_by(RadarDataset.timestamp.desc()).all()
	    if len(radar_dataset)==0 : 
		continue
            layers[layer_name].data = radar_dataset[0].geotiff_path
            layers[layer_name].setProjection( radar_dataset[0].projdef )
            bbox =  map(float,radar_dataset[0].bbox_original.split(",") )
            layers[layer_name].setExtent( *bbox )
    session.close()
#    map_object.save("mymapfile.map")
    return map_object

if __name__ == '__main__': # CGI
    settings = read_config()
    req = mapscript.OWSRequest()
    req.loadParams()
    map_object = wms_request(req,settings)
    # dispatch
    map_object.OWSDispatch( req )
