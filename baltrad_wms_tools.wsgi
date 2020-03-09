#!/usr/bin/env python
# read config
import cgi
import os
import sys
from wsgiref.simple_server import make_server

sys.path.append(os.path.dirname(__file__))

import configparser
from configurator import read_config,config
from baltrad_wms import get_query_layer
settings = read_config(tools=True)
online_resource = settings["online_resource"]
tmpdir = settings["tmpdir"]

from db_setup import *

import io
from urllib.request import urlopen
from xml.etree import ElementTree
import zipfile
import tempfile
from pyproj import Proj, transform

kmz_image_width = 2000
kml_namespace = "http://www.opengis.net/kml/2.2"

#            else:
#                bbox_lonlat = None

def download_geotiff(timestamp,layer_name):
    time_object = datetime.strptime(timestamp,"%Y-%m-%dT%H:%M:00Z")
    radar_dataset = session.query(RadarDataset)\
            .filter(RadarDataset.name==get_query_layer(layer_name))\
            .filter(RadarDataset.timestamp==time_object).one()
    tiff_path = radar_dataset.geotiff_path
    filename = os.path.basename(tiff_path)
    content = open(tiff_path,"rb").read()
    return content, filename

def time_series(req,start_time,end_time,layer_name):
    # read time values as objects
    start = datetime.strptime(start_time,"%Y-%m-%dT%H:%M:00Z")
    end = datetime.strptime(end_time,"%Y-%m-%dT%H:%M:00Z")
    radar_datasets = session.query(RadarDataset)\
            .filter(RadarDataset.name==get_query_layer(layer_name))\
            .filter(RadarDataset.timestamp>=start)\
            .filter(RadarDataset.timestamp<=end)
    timestamps = []
    bboxes = []
    for r in radar_datasets.all():
        timestamps.append( r.timestamp.strftime("%Y-%m-%dT%H:%M:00Z") )
        if "epsg" in r.projdef.lower():
            radar_proj = Proj(init=r.projdef)
        else:
            radar_proj = Proj(str(r.projdef))
        lonlat_proj = Proj(init="epsg:4326")
        b = r.bbox_original.split(",")
        lonmin, __ = transform(radar_proj,
                                   lonlat_proj,
                                   float(b[0]),
                                   (float(b[1])+float(b[3]))/2)
        __, latmin = transform(radar_proj,
                                   lonlat_proj,
                                   (float(b[0])+float(b[2]))/2,
                                   float(b[1]))
        lonmax, __  = transform(radar_proj,
                                   lonlat_proj,
                                   float(b[2]),
                                   (float(b[1])+float(b[3]))/2)
        __, latmax = transform(radar_proj,
                                   lonlat_proj,
                                   (float(b[0])+float(b[2]))/2,
                                   float(b[3]))

        bbox_lonlat = [lonmin, latmin, lonmax, latmax]
        bbox_lonlat = map(str,bbox_lonlat)
        bbox_lonlat = ",".join( bbox_lonlat )
        bboxes.append( bbox_lonlat )
    if req=="kmz":
        # read bboxes from config
        # calculate image dimensions
        bbox_0 = list (map( float, bboxes[0].split(",")))
        kmz_image_height = int ( kmz_image_width * (bbox_0[3]-bbox_0[1]) / (bbox_0[2]-bbox_0[0]) ) 
        request_string = online_resource + "?LAYERS=" + layer_name
        # basic WMS parameters
        request_string += "&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&STYLES="
        # image properties
        request_string += "&TRANSPARENT=true&FORMAT=image%2Fpng"
        request_string += "&WIDTH=%i&HEIGHT=%i&" % (kmz_image_width, kmz_image_height)
        request_string += "SRS=epsg:4326"
        kmz_files = {}
        kmz_output = io.BytesIO()
        kml_object =  ElementTree.parse( os.path.dirname(os.path.realpath(__file__))+'/baltrad_singlelayer.kml')
        root_object = kml_object.find('.//{%s}Folder' % kml_namespace)
        folder = root_object.find('.//{%s}Folder' % kml_namespace)
        folder_name = folder.find('.//{%s}name' % kml_namespace)
        folder_name.text = "BALTRAD+ data from %s to %s" % (timestamps[0],timestamps[-1])
        screen_overlay = folder.find('.//{%s}ScreenOverlay' % kml_namespace)
        description = screen_overlay.find('.//{%s}description' % kml_namespace)
        description.text = "Legend for BALTRAD+ data"
        for i in range(len(timestamps)):
            time_value = timestamps[i]
            bbox_value = bboxes[i]
            data_bbox = list(map(float, bbox_value.split(",") ))
            ground_overlay = ElementTree.SubElement(folder,"GroundOverlay")
            ground_overlay_name = ElementTree.SubElement(ground_overlay, "name")
            ground_overlay_name.text = "Radar data" 
            ground_overlay_desc = ElementTree.SubElement(ground_overlay, "description")
            ground_overlay_desc.text = "Overlay shows BALTRAD+ data." 
            geo_coords = {"north": data_bbox[3], "south": data_bbox[1], "east": data_bbox[2], "west": data_bbox[0], "rotation":0}
            timespan =  ElementTree.SubElement(ground_overlay, "TimeSpan")
            begin = ElementTree.SubElement(timespan, "begin")
            begin.text = str( timestamps[i] )
            end = ElementTree.SubElement(timespan, "end")
            try:
                end.text = str(timestamps[i+1])
            except IndexError:
                end.text = str(timestamps[i])
            #timestamp =  ElementTree.SubElement(ground_overlay, "TimeStamp")
            #when = ElementTree.SubElement(timestamp, "when")
            #when.text = str( timestamps[i] )
            wms_request = request_string + "&BBOX=%f,%f,%f,%f" % (data_bbox[0], data_bbox[1], data_bbox[2],data_bbox[3])
            latlonbox = ElementTree.SubElement(ground_overlay, "LatLonBox")
            for item in geo_coords.keys():
                element = ElementTree.SubElement(latlonbox, item)
                element.text = str( geo_coords[item] )
            icon = ElementTree.SubElement(ground_overlay, "Icon")
            icon_href = ElementTree.SubElement(icon, "href")
            icon_href.text = "image%i.png" % i
            kmz_files["image%i_path" % i] = tempfile.mkstemp(prefix='overlay_', suffix='.png', dir=tmpdir)[1]
            image_file = open(kmz_files["image%i_path" % i], "wb")
            image_file.write(urlopen(wms_request + "&TIME=" + timestamps[i]).read())
            image_file.close()
        legend_request = online_resource + "?LAYER=" + layer_name
        legend_request += "&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetLegendGraphic&STYLES=default&format=image%2Fpng"
        kmz_files["legend_path"] = tempfile.mkstemp(prefix='overlay_legend_', suffix='.png', dir=tmpdir)[1]
        legend_file = open(kmz_files["legend_path"], "wb")
        legend_file.write(urlopen(legend_request).read())
        legend_file.close()
        kmz_files["data_path"] = tempfile.mkstemp(prefix='result_', suffix='.kml', dir=tmpdir)[1]
        ElementTree.ElementTree(kml_object.getroot()).write ( kmz_files["data_path"], "utf-8")
        #kml_file = open(kmz_files["data_path"],"w")
        #kml_file.write(kmldata)
        #kml_file.close()
        content = kmz_output
        kmz_file = zipfile.ZipFile(kmz_output,"w")
        for filename in kmz_files.keys():
            kmz_file.write( kmz_files[filename], filename.replace("_path", "." + kmz_files[filename].split(".")[-1]), zipfile.ZIP_DEFLATED)
            os.remove(kmz_files[filename])
        kmz_file.close()
        content = kmz_output.getvalue()
        filename = "BALTRAD_DATA_from_%s_to_%s.kmz" % (timestamps[0],timestamps[-1])
        return content, filename
    else:
        return content, "debug.txt"


def application (environ, start_response):

    pars = cgi.FieldStorage(fp=environ['wsgi.input'],environ=environ)

    action = pars["ACTION"].value
    if action=="download_geotiff":
        content_type = "image/tiff"
        content, filename = download_geotiff(pars["TIME"].value,pars["LAYER"].value)
    elif action=="export_to_kmz":
        start_time = pars["START_TIME"].value
        end_time =  pars["END_TIME"].value
        layer_name = pars["LAYER"].value
        content_type = "application/vnd.google-earth.kmz"
        content, filename = time_series("kmz",start_time,end_time,layer_name)
    else:
        content_type = "text/plain"
        filename = "error.txt"
        content = "unknown action"

    session.close()

    attachment_name = "attachment; filename=" + filename

    status = '200 OK'
    response_headers = [
        ('Content-Type', content_type),
        ('Content-Length', str(len(content))),
        ('Content-Disposition', attachment_name)
    ]

    start_response(status, response_headers)

    return [content]

if __name__ == '__main__':

    httpd = make_server('localhost', 8051, application)

    # Now it is serve_forever() in instead of handle_request()
    httpd.serve_forever()
