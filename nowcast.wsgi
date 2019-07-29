#!/usr/bin/env python

from wsgiref.simple_server import make_server
from cgi import parse_qs, escape
import json
import os,sys
from datetime import datetime
import netCDF4 as cdf
import datetime as dt
import pyproj
from glob import glob
from collections import OrderedDict

ncf_time_format = "%Y-%m-%d %H:%M:%S"

def open_netcdf(filename, mode, format = "NETCDF4"):
    ncf = cdf.Dataset(filename, mode, format)
    return ncf

def get_data(ncf, timeformat = ncf_time_format):
    data_var = "precip_probability"
    time_var = "time"
    #time_format = "%Y-%m-%d %H:%M:%S"
    startdate = dt.datetime.strptime(ncf.datetime, ncf_time_format)
    data = OrderedDict()
    for i in range(ncf[data_var].shape[0]):
        min_passed = int(ncf.variables[time_var][i])
        datetime = startdate + dt.timedelta(minutes = min_passed)
        data[dt.datetime.strftime(datetime, timeformat)] = ncf[data_var][i]
    return data

def _get_prob(ncf, datetime_str, x, y):

    data = get_data(ncf)
    datetime = dt.datetime.strptime(datetime_str,"%Y%m%d%H%M")
    p = data[str(datetime)][y][x]
    return p

def get_cords(ncf, lat, lon):
    pr = pyproj.Proj(ncf.projection)
    X, Y = pr(lon, lat)
    step = ncf.variables["xc"][1]- ncf.variables["xc"][0]
    x = (X - ncf.variables["xc"][0]) / step
    y = (Y - ncf.variables["yc"][0]) / step
    return int(x), int(y)


def get_prob(ncf, datetime_str, lat, lon):
    x,y = get_cords(ncf, lat, lon)
    return _get_prob(ncf, datetime_str, x, y)

def get_prob_arr(ncf, starttime_str, endtime_str, lat, lon):
    start = dt.datetime.strptime(starttime_str,"%Y%m%d%H%M")
    end = dt.datetime.strptime(endtime_str,"%Y%m%d%H%M")

    data = get_data(ncf)

    timelist = list(map(lambda x: dt.datetime.strptime(x, ncf_time_format), [i for i in data]))
    timelist = list(map(str, filter(lambda x: start <= x and x <= end, timelist)))

    x, y = get_cords(ncf, lat, lon)

    P = [data[time][y][x] for time in timelist]
    return P

def get_prob_dict(out_dir, lat, lon):
    filename = sorted(glob(out_dir + "/probab_ensemble_nwc_*.ncf"))[-1]
    if (os.path.getsize (filename) ==0) : return {}
    timeformat = "%Y-%m-%dT%H:%M:%SZ"
    ncf = open_netcdf(filename, 'r')
    data = get_data(ncf, timeformat=timeformat)
    timelist = list(map(lambda x: dt.datetime.strptime(x, timeformat), [i for i in data]))

    datetime_now = dt.datetime.utcnow()
    timelist = list(filter(lambda x: datetime_now <= x and x <= datetime_now + dt.timedelta(hours=2), timelist))

    x,y = get_cords(ncf, lat, lon)
    P = OrderedDict()
    for time in timelist:
        time_str = dt.datetime.strftime(time, timeformat)
        P[time_str] = data[time_str][y][x]
    return P

def application (environ, start_response):

  # Returns a dictionary in which the values are lists
    d = parse_qs(environ['QUERY_STRING'])

    # As there can be more than one value for a variable then
    # a list is provided as a default value.
    lon  = d.get('lon', [''])[0] # Returns longitude
    lat  = d.get('lat', [''])[0] # Returns lattitude

    # Always escape user input to avoid script injection
    lon = escape(lon)
    lat = escape(lat)

    a = get_prob_dict("/home/ubuntu/pysteps-data/out", float(lat), float(lon))

    response_body=json.dumps([{'timestamp':k, 'probability': str(v)} for k,v in a.items()])

    status = '200 OK'
    response_headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(response_body)))
    ]
    start_response(status, response_headers)

    return [response_body]


if __name__ == '__main__':

    httpd = make_server('127.0.0.1', 8051, application)

    # Now it is serve_forever() in instead of handle_request()
    httpd.serve_forever()



