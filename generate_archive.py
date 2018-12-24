#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from tendo import singleton
from glob import glob
import os
import datetime
from shutil import copyfile
from update_gimet_wms import update,clear

me = singleton.SingleInstance() # will sys.exit(-1) if other instance is running

mapsize=700
russia_proj_str = '+proj=sterea +lat_0=60 +lon_0=31 +ellps=bessel'
bbox=(-mapsize*1000, -mapsize*1000, mapsize*1000, mapsize*1000)

mapsize_bufr=1400
russia_proj_str_bufr = '+proj=stere +lat_0=54 +lon_0=42 +ellps=bessel'
bbox_bufr=(-mapsize_bufr*1000, -mapsize_bufr*1000, mapsize_bufr*1000, mapsize_bufr*1000)

russia_proj_str_lnv = '+proj=sterea +lat_0=55.5 +lon_0=37.5 +ellps=bessel'


incoming_dir='/home/dmrl_ftp/in'
outgoing_dir='../pysteps-data/radar/gimet'
outgoing_dir_1km='../pysteps-data/radar/gimet-1km'
outgoing_dir_wms='../baltrad_wms_data'

if len(glob(incoming_dir+"/*.tiff"))>0 :
    for filename in glob(incoming_dir+"/*.tiff"):
        product_name=os.path.basename(filename)[0:-19]
        date=datetime.datetime.strptime(filename[-18:-5],'%Y%m%d_%H%M')
        print (product_name, date)
        date_str=filename[-18:-10]
        if (product_name[0:4]=="bufr") :
            if not os.path.exists(outgoing_dir_wms+"/"+product_name):
                os.makedirs(outgoing_dir_wms+"/"+product_name)
            copyfile(filename,outgoing_dir_wms+"/"+product_name+"/"+os.path.basename(filename))
            if (product_name[0:6]=="bufr_v") :
                update(date,russia_proj_str_lnv,bbox_bufr,product_name)
            else:
                update(date,russia_proj_str_bufr,bbox_bufr,product_name)

            if not os.path.exists(outgoing_dir+"/"+date_str):
                os.makedirs(outgoing_dir+"/"+date_str)
            try:
                copyfile(filename,outgoing_dir+"/"+date_str+"/"+os.path.basename(filename))
                os.remove(filename)
            except PermissionError: 
                print ("Permission error:",filename)
        if (product_name[0:5]=="gimet") :
            if not os.path.exists(outgoing_dir_1km+"/"+date_str):
                os.makedirs(outgoing_dir_1km+"/"+date_str)
            try:
                copyfile(filename,outgoing_dir_1km+"/"+date_str+"/"+os.path.basename(filename))
                os.remove(filename)
            except PermissionError: 
                print ("Permission error:",filename)

