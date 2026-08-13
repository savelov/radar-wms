#!/usr/bin/env python
# -*- coding: utf-8 -*-
import mapscript
from urllib.parse import parse_qs
from html import escape

# needed to import baltrad_wms.py
import os,sys
sys.path.append(os.path.dirname(__file__))

from baltrad_wms import read_config,wms_request,read_session
from token_utils import generate_token, validate_token

def application(environ, start_response):
    path = environ.get("SCRIPT_NAME", "")

    client_ip = environ.get("REMOTE_ADDR", "")

    # 🔑 Token endpoint
    if path == "/get_token":
        token = generate_token(client_ip)

        start_response("200 OK", [
            ("Content-Type", "application/json"),
            ("Cache-Control", "no-store")
        ])
        return [f'{{"token":"{token}"}}'.encode()]

    # 🌍 WMS protection
    if path == "/baltrad_wsgi":
        query = environ.get("QUERY_STRING", "")
        params = dict(
            p.split("=", 1) for p in query.split("&") if "=" in p
        )

        token = params.get("token")

        if not token or not validate_token(token, client_ip):
            start_response("403 Forbidden", [("Content-Type", "text/plain")])
            return [b"Forbidden"]

        # remove token before passing to MapServer (optional)
        if "token" in params:
            del params["token"]
            environ["QUERY_STRING"] = "&".join(
                f"{k}={v}" for k, v in params.items()
            )

        # 👉 continue existing logic
        try:
            return real_application(environ, start_response)
        finally:
            # return the connection to the pool and drop any open read
            # transaction — a leaked session pins the WAL file
            read_session.remove()


def real_application(environ,start_response):

    # read config
    req = mapscript.OWSRequest()
    req.type = mapscript.MS_GET_REQUEST
    settings = read_config()
    parameters = parse_qs(environ.get('QUERY_STRING', ''))
    for key in parameters.keys():
        req.setParameter(key,parameters[key][0])
    map_object = wms_request( req, settings )
    # output result
    mapscript.msIO_installStdoutToBuffer()
    map_success = map_object.OWSDispatch( req ) # output should be 0
    try:
        content_type = mapscript.msIO_stripStdoutBufferContentType()
    except :
        start_response('200 OK', [('Content-Type', 'text/html')])
        return [b'<!DOCTYPE html><meta charset="utf-8"/>no info']
    response = mapscript.msIO_getStdoutBufferBytes()
    status = '200 OK'
    response_headers = [('Content-type', content_type)]
    start_response(status, response_headers)
    return [response]

if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    srv = make_server('localhost', 8081, application)
    srv.serve_forever()
