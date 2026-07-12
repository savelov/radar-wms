#!/usr/bin/env python

from wsgiref.simple_server import make_server
from urllib.parse import parse_qs
from html import escape
import json
import os,sys
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from  vector_setup import *

def application (environ, start_response):
    try:
        return handle_request(environ, start_response)
    finally:
        # release the read connection back to the pool after every request —
        # a leaked read transaction pins the WAL file
        read_session.remove()

def handle_request (environ, start_response):

  # Returns a dictionary in which the values are lists
    d = parse_qs(environ['QUERY_STRING'])

    # As there can be more than one value for a variable then
    # a list is provided as a default value.
    time  = d.get('time', [''])[0] # Returns the first age value
    title = d.get('title', []) # Returns a list of hobbies

    # Always escape user input to avoid script injection
    time = escape(time)

    if time in (None,"-1","") :
        vector_dataset = read_session.query(VectorDataset)\
            .order_by(VectorDataset.timestamp.desc()).first()
        timestamp=vector_dataset.timestamp
    else:
        timestamp = datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")

#    title = escape(title)

    # Sorting and stringifying the environment key, value pairs

    vector_datasets = read_session.query(VectorDataset)\
            .filter(VectorDataset.timestamp==timestamp).all()

    radar_vector = []
    for r in vector_datasets:
        if r.distance>0 and r.bearing!=511:
            radar_vector.append([float(round(r.latitude,4)),float(round(r.longitude,4)),float(round(r.distance,2)),float(round(r.bearing,2))])

    response_body=bytes(json.dumps(radar_vector),encoding='utf-8')

    status = '200 OK'
    response_headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(response_body)))
    ]
    start_response(status, response_headers)

    return [response_body]


if __name__ == '__main__':

    httpd = make_server('localhost', 8051, application)

    # Now it is serve_forever() in instead of handle_request()
    httpd.serve_forever()
