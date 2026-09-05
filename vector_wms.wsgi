#!/usr/bin/env python

from wsgiref.simple_server import make_server
from urllib.parse import parse_qs
from html import escape
import json
import os,sys
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from  vector_setup import *
from token_utils import validate_token

def application (environ, start_response):
    try:
        return handle_request(environ, start_response)
    finally:
        # release the read connection back to the pool after every request —
        # a leaked read transaction pins the WAL file
        read_session.remove()

def parse_time (text):
    """The requested time, or None for the newest.

    Anything ISO-8601-ish, which is what a browser sends: OpenLayers puts
    milliseconds on the Z form, so the trailing Z is trimmed and the
    sub-second part dropped rather than matched exactly - the datasets sit
    on whole minutes.
    """
    if text in (None,"-1","") :
        return None
    text = str(text).strip().replace("Z","").replace(" ","T")
    return datetime.fromisoformat(text).replace(microsecond=0)


def handle_request (environ, start_response):

  # Returns a dictionary in which the values are lists
    d = parse_qs(environ['QUERY_STRING'])

    # As there can be more than one value for a variable then
    # a list is provided as a default value.
    time  = d.get('time', [''])[0] # Returns the first age value
    title = d.get('title', []) # Returns a list of hobbies

    # Same gate as the WMS: this endpoint used to be open, which is how the
    # phenomena layer ended up being read by clients that never load a page
    # of ours.  The token is minted by /get_token on this same host.  A
    # missing one short-circuits the way it does in baltrad_wms.wsgi, so a
    # client that sends none does not write an error-log line per request.
    vector_token = d.get('token', [''])[0]
    if not vector_token or not validate_token(vector_token,
                                              environ.get("REMOTE_ADDR", "")):
        start_response('403 Forbidden', [('Content-Type', 'text/plain')])
        return [b"Forbidden"]

    # Always escape user input to avoid script injection
    time = escape(time)

    try:
        timestamp = parse_time(time)
    except ValueError:
        return error_response(start_response,
                              "cannot read %s as a time" % time)

    if timestamp is None:
        vector_dataset = read_session.query(VectorDataset)\
            .order_by(VectorDataset.timestamp.desc()).first()
        timestamp=vector_dataset.timestamp

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


def error_response (start_response, message):
    body = bytes(json.dumps({"error": message}),encoding='utf-8')
    start_response('400 Bad Request', [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(body)))
    ])
    return [body]


if __name__ == '__main__':

    httpd = make_server('localhost', 8051, application)

    # Now it is serve_forever() in instead of handle_request()
    httpd.serve_forever()
