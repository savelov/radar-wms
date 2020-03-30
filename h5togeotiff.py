#!/usr/bin/env python
#
# h5togeotiff.py 
#
# Copyright 2011-2012
# Tuomas Peltonen, STUK - Radiation and Nuclear Safety Authority, Finland
# email: {first.last}@stuk.fi
#
# Requirements:
# * h5py
# * numpy
# * pyproj
# * python-gdal

import h5py
try:
    from pyproj import Proj, transform
except ImportError: # not required
    pass

import numpy
from datetime import datetime
import os
try: # Linux
    from osgeo import gdal
    from osgeo import gdal_array
    from osgeo import osr
    from osgeo.gdalconst import GDT_Float32
    from osgeo.gdalconst import GDT_Int16
    from osgeo.gdalconst import GDT_Byte

except ImportError: # Windows
    import gdal
    import osr
    from gdalconst import GDT_Float32
    from gdalconst import GDT_Int16
    import gdalnumeric as gdal_array

class H5ConversionSkip(Exception):
    "Conversion skipper exception handler"
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return self.message

def h5togeotiff(hdf_files,geotiff_target,dataset_name ="dataset1/data1",data_type="float",expiration_time=None):
    """
    Converts BALTRAD hdf5 file to Mapserver compliant GeoTiff file. 
    Reprojection of data is included.

    Parameters:
    * hdf5_source: Source HDF5 file path, if list then sum results
    * geotiff_target: Target GeoTIFF file path
    * target_projection: EPSG code string or set to None for no projection
    * dataset_name: change this if other information is wanted 
    * data_type: data type for target file: float or int
    * expiration_time: if defined (datetype.datetype) skip conversion if necessary
    """
    if not isinstance(hdf_files, (list, tuple)):
        hdf_files = [hdf_files]
    first_iteration = True
    for hdf5_source in hdf_files:
        # read h5 file
        f = h5py.File(hdf5_source,'r') # read only
        where = f["where"] # coordinate variables
        what = f["what"] # data

        # read time from h5 file
        date_string = what.attrs["date"][0:8].decode('utf-8')
        time_string = what.attrs["time"][0:4].decode('utf-8') # ignore seconds
        starttime = datetime.strptime(date_string+"T"+time_string, "%Y%m%dT%H%M")
        if expiration_time:
            if starttime<expiration_time:
                raise H5ConversionSkip("Conversion of expired dataset (%s) skipped" % str(starttime))

        dataset = f[dataset_name.split("/")[0]] 
        data_1 = dataset[dataset_name.split("/")[1]]
        data = data_1["data"]

        data_what = data_1["what"]

        # read coornidates
        lon_min = where.attrs["LL_lon"]
        lon_max = where.attrs["UR_lon"]
        lat_min = where.attrs["LL_lat"]
        lat_max = where.attrs["UR_lat"]

        # non-rectangle datasets not supported (are they ever produced?)
#        if ( where.attrs["LL_lon"]!=where.attrs["UL_lon"] or \
#                where.attrs["LL_lat"]!=where.attrs["LR_lat"] or \
#                where.attrs["LR_lon"]!=where.attrs["UR_lon"] or \
#                where.attrs["UL_lat"]!=where.attrs["UR_lat"] ):
#            raise Exception("non-rectangle datasets not supported")

        proj_text = where.attrs["projdef"].decode('utf-8')
        h5_proj = Proj(proj_text)
        lonlat_proj = Proj(init="epsg:4326")
        # transfrom bounding box from lonlat -> laea
        xmin, ymin = transform(lonlat_proj,h5_proj,lon_min,lat_min)
        xmax, ymax = transform(lonlat_proj,h5_proj,lon_max,lat_max)

        # shape
        x_size = data.shape[1]
        y_size = data.shape[0]

        # generate axes
        x_axis = numpy.arange( xmin,xmax,(xmax-xmin)/x_size )
        #y_help_axis = numpy.arange( ymin,ymax,(ymax-ymin)/x_size )

        y_axis = numpy.arange( ymax,ymin,(ymin-ymax)/y_size )  # reversed
        #x_help_axis = numpy.arange( xmax,xmin,(xmin-xmax)/y_size ) # reverse this also

        missing_value = data_what.attrs["nodata"]
        missing_echo = data_what.attrs["undetect"]

        if data_type=="int":
            geotiff_data = numpy.uint8(data); 
            geotiff_data[numpy.where(geotiff_data==(missing_echo))]=1
            geotiff_data[numpy.where(geotiff_data==(missing_value))]=0
        else:
            offset = float(data_what.attrs["offset"])
            if first_iteration:
                geotiff_data = numpy.float32(data[:]) + numpy.float32(data_what.attrs["offset"])
                first_iteration = False
            else:
                geotiff_data = geotiff_data + numpy.float32(data[:]) + numpy.float32(data_what.attrs["offset"])
    # begin tiff file generation 
    driver = gdal.GetDriverByName('GTiff')
    if data_type=="int":
        gdt_data_type = GDT_Byte
    else:
        gdt_data_type = GDT_Float32
    # geotiff mask array?
    out = driver.Create(geotiff_target, geotiff_data.shape[1], geotiff_data.shape[0], 1, gdt_data_type)
#    out.SetMetadataItem("TIFFTAG_GDAL_NODATA",str(missing_value))
    out.SetMetadataItem("TIFFTAG_DATETIME",starttime.strftime("%Y-%m-%dT%H:%MZ"))
    #timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")


    #geotiff_data[numpy.where(geotiff_data==(missing_value+offset))]=255

    out.SetGeoTransform([xmin, # grid must be regular!
                         (xmax - xmin)/geotiff_data.shape[1], # grid size, get lon index!
                         0,  
                         ymax,
                         0,
                         (ymin - ymax)/geotiff_data.shape[0]])
    srs = osr.SpatialReference()
    srs.ImportFromProj4( proj_text )
    out.SetProjection( srs.ExportToWkt() )
    # export to geotiff
    #gdal_array.BandWriteArray(out.GetRasterBand(1), geotiff_data)
    out.GetRasterBand(1).WriteArray( geotiff_data )
    
    # delete geotiff object to free memory
    del out

    f.close()
    return {"timestamp":starttime.strftime("%Y-%m-%dT%H:%MZ"),
            "projection": proj_text,
            "bbox_lonlat": "%f,%f,%f,%f" % (lon_min,lat_min,lon_max,lat_max),
            "bbox_original": "%f,%f,%f,%f" % (xmin,ymin,xmax,ymax)
            }

if __name__ == '__main__':
    # command line use
    import sys
    try:
        hdf5_source = sys.argv[1]
        geotiff_target = sys.argv[2]
        h5togeotiff(hdf5_source, geotiff_target, "dataset1/data1","int")
    except IndexError:
        print ("""\
Usage
-----
Convert single HDF5 to GeoTIFF:
 python h5togeotiff.py [HDF5 source file] [GeoTIFF target fi]
              """
)