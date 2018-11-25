#!/usr/bin/env python
import mapscript
from cgi import parse_qs, escape

# needed to import baltrad_wms.py
import os,sys
sys.path.append(os.path.dirname(__file__))

from baltrad_wms import read_config,wms_request

def application(environ,start_response):
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
        return ['Error']
    response = mapscript.msIO_getStdoutBufferBytes()
    status = '200 OK'
    response_headers = [('Content-type', content_type)]
    start_response(status, response_headers)
    return [response]

if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    srv = make_server('localhost', 8081, application)
    srv.serve_forever()
