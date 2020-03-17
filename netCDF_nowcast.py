import netCDF4 as cdf
import datetime as dt
from glob import glob
from collections import OrderedDict
import pyproj
import rasterio
import numpy as np
import os

from update_gimet_wms import update,clear

ncf_time_format = "%Y-%m-%d %H:%M:%S"

def open_netcdf(filename, mode, format = "NETCDF4"):
    ncf = cdf.Dataset(filename, mode, format)
    return ncf

def get_data(ncf, timeformat = ncf_time_format, data_var='precip_probability'):
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
    timeformat = "%Y-%m-%dT%H:%M:%SZ"
    ncf = open_netcdf(filename, 'r')
    data = get_data(ncf, timeformat=timeformat)
    timelist = list(map(lambda x: dt.datetime.strptime(x, timeformat), [i for i in data]))

    datetime_now = timelist[0]#dt.datetime.utcnow()
    timelist = list(filter(lambda x: datetime_now <= x and x <= datetime_now + dt.timedelta(hours=2), timelist))

    x,y = get_cords(ncf, lat, lon)
    P = OrderedDict()
    for time in timelist:
        time_str = dt.datetime.strftime(time, timeformat)
        P[time_str] = data[time_str][y][x]
    return P


def convert_probability_to_byte(values):
    bytes = values * 100.
    bytes[values == -1] = 255
    return bytes.astype(np.uint8)


def convert_precipitation_to_byte(values):
    # values[(values >= 5.001)] = 210
    # values[(values > 0.001) & (values < 0.5)] = 10
    # values[(values > 0.5001) & (values < 1)] = 40
    # values[(values > 1.001) & (values < 1.5)] = 70
    # values[(values > 1.501) & (values < 2)] = 100
    # values[(values > 2.001) & (values < 3.5)] = 130
    # values[(values > 3.501) & (values < 4)] = 160
    # values[(values > 4.001) & (values < 4.5)] = 190
    # values[(values > 4.501) & (values < 5)] = 200
    values[values == -1] = 255
    # return values.astype(np.uint8)
    return values


def to_geotiff(ncf, out_folder):
    # startdate = dt.datetime.strptime(ncf.datetime, ncf_time_format)

    product = 'precip_probability' if 'precip_probability' in ncf.variables else 'precip_intensity'
    import os
    if product == 'precip_probability':
        out_folder = os.path.join(out_folder, 'nowcast')
    elif product == 'precip_intensity':
        out_folder = os.path.join(out_folder, 'prec_intensity')
        if not os.path.exists(out_folder):
            os.mkdir(out_folder)

    n,h,w = ncf.variables[product].shape

    Xmin = ncf.variables["xc"][0]
    Xmax = ncf.variables["xc"][-1]
    Ymin = ncf.variables["yc"][0]
    Ymax = ncf.variables["yc"][-1]

    affine = rasterio.Affine((Xmax - Xmin) / w, 0, Xmin,
                             0, (Ymin - Ymax) / h, Ymax)

    data = get_data(ncf, data_var=product)
    for key in data:
        data[key][:]=data[key][::-1,:]

        datetime = dt.datetime.strptime(key, ncf_time_format)
        if product == 'precip_intensity':
            pr = 'prec_intensity'
        else:
            pr = 'nowcast'
        filename = out_folder + "/{}_".format(pr) + dt.datetime.strftime(datetime, "%Y%m%d_%H%M") + ".tiff"
        import os
        filename = os.path.realpath(filename)
        if not os.path.exists(os.path.dirname(filename)):
            os.mkdir(os.path.dirname(filename))
        print(filename)
        img_data = convert_probability_to_byte(data[key]) if product == 'precip_probability' else convert_precipitation_to_byte(values=data[key].data)
        dtype = np.uint8 if product == 'precip_probability' else np.float32
        with rasterio.open(filename, 'w', driver='GTiff',
                               height=h, width=w, count=1, dtype=dtype,
                               crs=ncf.projection, nodata=255, transform=affine) as ncfile:
            ncfile.write_band(1, img_data)
        update(datetime,ncf.projection,(-w*2*1000, -h*2*1000, w*2*1000, h*2*1000),pr)


if __name__ == '__main__':
    filename = sorted(glob("/home/ubuntu/pysteps-data/out/probab_ensemble_nwc_*.ncf"))[-1]

    ncf = open_netcdf(filename, 'r')
    to_geotiff(ncf, "/home/ubuntu/baltrad_wms_data")
    # clear()
