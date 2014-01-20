var wms_url = "/baltrad/baltrad_wms.py";
// var wms_url = "/baltrad_wsgi";
var wms_tools_url = "/baltrad/baltrad_wms_tools.py";

/* do not edit anything below this */
var map;
var layer;
var layer_name;
var first_update = true;
var time_value; // current time
// update every 5 minutes
var updater = setInterval(update_times_and_refresh,300000);

function update_times_and_refresh () {
    update_meta (); 
    document.getElementsByTagName("select")[1].selectedIndex = 0;
    update_layer_params()
}

function init() {
    map = new OpenLayers.Map({
        div: "map",
        projection: new OpenLayers.Projection("EPSG:3857"),
        units: "m",
        maxResolution: 156543.0339,
        maxExtent: new OpenLayers.Bounds(
            -20037508, -20037508, 20037508, 20037508.34
        )
    });
    
    var osm = new OpenLayers.Layer.OSM();            
    var gmap = new OpenLayers.Layer.Google("Google Streets");
    
    map.addLayers([osm, gmap]);

    map.addControl(new OpenLayers.Control.LayerSwitcher());

    map.setCenter(
        new OpenLayers.LonLat(20, 65).transform(
            new OpenLayers.Projection("EPSG:4326"),
            map.getProjectionObject()
        ), 
        4
    );

    layer_name = document.getElementsByTagName("select")[0].value;

    layer = new OpenLayers.Layer.WMS(
        "Radar",
        wms_url,
        {layers: layer_name, transparent: 'true', format: 'image/png', time: "-1"},
        {isBaseLayer: false,singleTile: true, buffer: 0} );
    map.addLayer(layer);

    map.events.register('click', map, findLayerClick);

    update_meta();

}

function update_meta () {
    OpenLayers.Request.GET({
        url: wms_url,
        async: false,
        params: {
            SERVICE: "WMS",
            VERSION: "1.1.1",
            REQUEST: "GetCapabilities"
        },
        success: function(request) {
            var doc = StringToXML(request.responseText);
            var layers = doc.getElementsByTagName("Layer")[0].getElementsByTagName("Layer");
            for (i=0;i<layers.length;i++) {
                if (layers[i].getElementsByTagName("Name")[0].childNodes[0].nodeValue.split(",")[0]==layer_name) {
                    var time_values = getDataOfImmediateChild(layers[i], "Extent").split(",");
                    var select = document.getElementsByTagName("select")[1];
                    select.options.length = 0;
                    for (k=0;k<time_values.length;k++)
                        select.options.add(new Option(time_values[k],time_values[k]));
                    first_update = false;
                    var start_select = document.getElementsByTagName("select")[2];
                    var end_select = document.getElementsByTagName("select")[3];
                    start_select.innerHTML = select.innerHTML;
                    start_select.selectedIndex = 5;
                    end_select.innerHTML = select.innerHTML;
                    var legend_url = layers[i].getElementsByTagName("LegendURL")[0].getElementsByTagName("OnlineResource")[0].getAttributeNS('http://www.w3.org/1999/xlink', 'href');
                    document.getElementById("map_legend").src = legend_url;
                    time_value = document.getElementsByTagName("select")[1].value;
                }
            }
        }, 
        failure: function() {
            alert("Trouble getting capabilities doc");
            OpenLayers.Console.error.apply(OpenLayers.Console, arguments);
        }
    });
}

function update_layer_params() {
    var new_layer = document.getElementsByTagName("select")[0].value;
    time_value = document.getElementsByTagName("select")[1].value;
    if (new_layer!=layer_name) {
        layer_name = new_layer;
        update_meta();
    }
    layer.mergeNewParams({time: time_value,layers:layer_name});
}

function go(direction) {
    if (direction=="down")
        document.getElementsByTagName("select")[1].selectedIndex++;
    else if (direction=="up")
        document.getElementsByTagName("select")[1].selectedIndex--;
    update_layer_params();
}

/*
 * An event occurred so now drill down the layers to get the info
 */
function findLayerClick(event) {

    mouseLoc = map.getLonLatFromPixel(event.xy);

    var url = layer.getFullRequestString({
                REQUEST: "GetFeatureInfo",
                EXCEPTIONS: "application/vnd.ogc.se_xml",
                BBOX: map.getExtent().toBBOX(),
                MAX_FEATURES: 1,
                X: event.xy.x,
                Y: event.xy.y,
                INFO_FORMAT: 'text/html',
                QUERY_LAYERS: layer_name,
                // RADIUS: 40,
                FEATURE_COUNT: 1,
                WIDTH: map.size.w,
                HEIGHT: map.size.h},
                wms_url + '?');

    OpenLayers.Request.GET({url: url,callback:setHTML,scope:this});

    // Event.stop(event);
}


function setHTML(response) {
    if (response.status==500)
        var text = ""
    else
        var text = response.responseText;
    document.getElementById("featureinfo").innerHTML = text
}

function getNodeText(xmlNode) {
    if(!xmlNode) return '';
    if(typeof(xmlNode.textContent) != "undefined") return xmlNode.textContent;
    return xmlNode.firstChild.nodeValue;
}

function getDataOfImmediateChild(parentTag, subTagName)
{
    var val = "";
    var listOfChildTextNodes;
    var directChildren = parentTag.childNodes;
    for (m=0; m < directChildren.length; m++)
    {
        if (directChildren[m].nodeName == subTagName)
        {
            /* Found the tag, extract its text value */
            listOfChildTextNodes = directChildren[m].childNodes;
            for (n=0; n < listOfChildTextNodes.length; n++)
            {
              val += listOfChildTextNodes[n].nodeValue;
            }
         }
     }
     return val;
}

function StringToXML (text) {
    if (window.ActiveXObject) {
        var doc = new ActiveXObject('Microsoft.XMLDOM');
        doc.async = 'false';
        doc.loadXML(text);
    } else {
        var parser = new DOMParser();
        var doc = parser.parseFromString(text,'text/xml');
    }
    return doc;
}

function export_to_geotiff () {
    window.location = wms_tools_url + "?ACTION=download_geotiff&TIME=" + time_value + "&LAYER=" + layer_name;
}

function view_accumulated_rain () {
    window.location = wms_tools_url + "?ACTION=accumulated_rain&TIME=" + time_value + "&LAYER=" + layer_name;
}

function export_to_kmz () {
    var start_time = document.getElementsByTagName("select")[2].value;
    var end_time = document.getElementsByTagName("select")[3].value;
    if (document.getElementsByTagName("select")[3].selectedIndex>document.getElementsByTagName("select")[2].selectedIndex) {
        alert( "check start and end times" )
        return
    }
    window.location = wms_tools_url + "?ACTION=export_to_kmz&START_TIME=" + start_time + "&END_TIME=" + end_time + "&LAYER=" + layer_name;
}
