#!/usr/bin/env python
from baltrad_wms import read_config
try: # TODO: fix
    from h5togeotiff import h5togeotiff
    from update_baltrad_wms import read_datasets
except ImportError:
    pass

import cgi
import os
import StringIO
from urllib import urlopen
from xml.etree import ElementTree
import zipfile
import tempfile

kmz_image_width = 600
kml_namespace = "http://www.opengis.net/kml/2.2"

def download_geotiff():
    timestamp = pars["TIME"].value
    layer_name = pars["LAYER"].value
    tiff_path = datasets.get(timestamp,layer_name)
    filename = os.path.basename(tiff_path)
    content = open(tiff_path).read()
    return content, filename

def time_series(req):
    start_time = pars["START_TIME"].value
    end_time =  pars["END_TIME"].value
    layer_name = pars["LAYER"].value
    for i in range (len(sections)):
        if sections[i]==start_time: # Start found
            start_index = i
        if sections[i]==end_time: # end found
            end_index = i
            break
    timestamps = sections[start_index:end_index+1]
    if req=="kmz":
        # read bboxes from config
        bboxes = []
        for t in timestamps:
            bboxes.append(datasets.get(t,"bbox"))
        # calculate image dimensions
        bbox_0 = map( float, bboxes[0].split(","))
        kmz_image_height = int ( kmz_image_width * (bbox_0[3]-bbox_0[1]) / (bbox_0[2]-bbox_0[0]) ) 
        request_string = online_resource + "?LAYERS=" + layer_name
        # basic WMS parameters
        request_string += "&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&STYLES="
        # image properties
        request_string += "&TRANSPARENT=true&FORMAT=image%2Fpng"
        request_string += "&WIDTH=%i&HEIGHT=%i&" % (kmz_image_width, kmz_image_height)
        request_string += "SRS=epsg:4326"
        kmz_files = {}
        kmz_output = StringIO.StringIO()
        kml_object =  ElementTree.fromstring( open( 'baltrad_singlelayer.kml', 'r').read() )
        root_object = kml_object.find('.//{%s}Folder' % kml_namespace)
        folder = root_object.find('.//{%s}Folder' % kml_namespace)
        folder_name = folder.find('.//{%s}name' % kml_namespace)
        folder_name.text = "BALTRAD+ data from %s to %s" % (timestamps[0],timestamps[-1])
        screen_overlay = folder.find('.//{%s}ScreenOverlay' % kml_namespace)
        description = screen_overlay.find('.//{%s}description' % kml_namespace)
        description.name = "Legend for BALTRAD+ data"
        for i in range(len(timestamps)):
            time_value = timestamps[i]
            bbox_value = bboxes[i]
            data_bbox = map(float, bbox_value.split(",") )
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
            wms_request = request_string + "&BBOX=%f,%f,%f,%f&" % (data_bbox[0], data_bbox[1], data_bbox[2],data_bbox[3])
            kmz_image_height = int ( kmz_image_width * (data_bbox[3]-data_bbox[1]) / (data_bbox[2]-data_bbox[0]) ) 
            wms_request += "WIDTH=%i&HEIGHT=%i&" % (kmz_image_width, kmz_image_height)
            wms_request += "SRS=epsg:4326"
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
        ElementTree.ElementTree(kml_object).write ( kmz_files["data_path"], "utf-8")
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
    elif req=="accumulated_rain":
        files = []
        for t in timestamps:
            files.append(datasets.get(t,layer_name))
        # generate tiff
        for d in read_datasets:
            if d["name"]==layer_name:
                hdf_dataset = d["hdf_dataset"]
        # TODO: implement
        tiff_path = "/tmp/testi.tif"
        geotiff = h5togeotiff( files, tiff_path, hdf_dataset )
        # create temporary mapfile
        # request string?
        content = ",".join(files)
    return content, "debug,txt"

sections, datasets, tmpdir, online_resource = read_config(True)
pars = cgi.FieldStorage()

action = pars["ACTION"].value
if action=="download_geotiff":
    content_type = "image/tiff"
    content, filename = download_geotiff()
elif action=="export_to_kmz":
    content_type = "application/vnd.google-earth.kmz"
    content, filename = time_series(req="kmz")
else:
    content_type = "text/plain"
    filename = "error.txt"
    content = "unknown action"

print "Content-Type: %s" % content_type
print "Content-Disposition: attachment; filename=%s" % filename
print
print content

