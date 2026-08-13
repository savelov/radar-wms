#!/usr/bin/env python
# -*- coding: utf-8 -*-
import mapscript
from urllib.parse import parse_qs, unquote
from html import escape

# needed to import baltrad_wms.py
import os,sys
sys.path.append(os.path.dirname(__file__))

from baltrad_wms import read_config,wms_request,read_session
from token_utils import generate_token, validate_token

def application(environ, start_response):
    # SCRIPT_NAME is wherever Apache mounted this, which is not one spelling:
    # /wms on the CAPPI site, /baltrad_wsgi on the older one.  Naming a single
    # mount here and guarding only that left every other one falling off the
    # end of the function and returning None, which mod_wsgi turns into a 500
    # with nothing in the log to say why.  The token endpoint is the one
    # special case; everything else is the WMS, and everything else is guarded.
    path = environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", "")

    client_ip = environ.get("REMOTE_ADDR", "")

    # 🔑 Token endpoint
    if path.rstrip("/").endswith("get_token"):
        token = generate_token(client_ip)

        start_response("200 OK", [
            ("Content-Type", "application/json"),
            ("Cache-Control", "no-store")
        ])
        return [f'{{"token":"{token}"}}'.encode()]

    # 🌍 WMS protection
    query = environ.get("QUERY_STRING", "")
    pairs = [p for p in query.split("&") if p]

    token = None
    for p in pairs:
        if p.startswith("token="):
            token = unquote(p[len("token="):])
            break

    if not token or not validate_token(token, client_ip):
        start_response("403 Forbidden", [("Content-Type", "text/plain")])
        return [b"Forbidden"]

    # Drop the token before MapServer sees the request, keeping every other
    # pair exactly as it arrived.  Rebuilding the string from a parsed dict
    # re-encodes it, and a WMS query carries values that do not survive the
    # round trip unchanged - the commas in BBOX, the colons in TIME.
    environ["QUERY_STRING"] = "&".join(p for p in pairs
                                       if not p.startswith("token="))

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
