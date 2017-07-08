#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import sys


date= datetime.datetime.utcnow()-datetime.timedelta(hours=3)
date= date-datetime.timedelta(minutes=10)
date_start =  date - datetime.timedelta(minutes=date.minute % 10,
                             seconds=date.second, microseconds=date.microsecond)
date_to=date_start+datetime.timedelta(hours=3)

date=date_start

#TODO  convert to native json? remove comma at the end of file?
file=open("demo/viz/tiles.json",'wt')
file.write ("{");

while date<date_to :

    if date!=date_start:
	file.write(',')
    filename_tif="mytiles/bufr_dbz1_%4d%02d%02d_%02d%02d.png" % (date.year, date.month, date.day, date.hour, date.minute)
    date_string="%4d-%02d-%02dT%02d:%02dZ" % (date.year, date.month, date.day, date.hour, date.minute)
    file.write('"%s":"%s"' %( date_string, filename_tif) )
    date+=datetime.timedelta(minutes=10)

file.write ("}");
file.close()
