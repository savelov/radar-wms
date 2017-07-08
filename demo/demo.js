//var wms_url = "/baltrad/baltrad_wms.py";
var wms_url = "/baltrad_wsgi";
//var wms_url = "http://localhost:8081";
var wms_tools_url = "/baltrad_tools_wsgi";

/* do not edit anything below this */
var map;
var wmsLayer;
var lineLayer;
var layer_name;
var first_update = true;
var time_value = null; // current time
// update every 1 minutes
var updater = setInterval(update_times_and_refresh,60000);

var bearing=45;
var interval_id=0;


function update_times_and_refresh () {
    if (document.getElementsByTagName("input")[0].checked) {
	update_meta (); 
	document.getElementsByTagName("select")[1].selectedIndex = 0;
	update_layer_params();
    }
}

function movie (direction) {

    if (interval_id!=0) {
        window.clearInterval(interval_id);
        interval_id=0;
    }

    if (direction=="up" || direction=="down")
        interval_id=window.setInterval(function() { go(direction); },1000);

}

function destination(lng, lat, dist, heading) {

var R=6371;

    lat *= Math.PI / 180;
    lng *= Math.PI / 180;
    heading *= Math.PI / 180;

    var lat2 = Math.asin( Math.sin(lat)*Math.cos(dist/R) +
                    Math.cos(lat)*Math.sin(dist/R)*Math.cos(heading) );
    var lng2 = lng + Math.atan2(Math.sin(heading)*Math.sin(dist/R)*Math.cos(lat),
                         Math.cos(dist/R)-Math.sin(lat)*Math.sin(lat2));

      return [180 / Math.PI * lng2, 180 / Math.PI * lat2 ];

}


function init() {

      layer_name = document.getElementsByTagName("select")[0].value;

      var wmsSource = new ol.source.ImageWMS({
        url: wms_url,
        params: {'LAYERS': layer_name},
        ratio: 1,
        serverType: 'geoserver'
      });

      wmsLayer = new ol.layer.Image({
	  opacity : 0.6,
          source: wmsSource
      });


      var source = new ol.source.Vector();


      lineLayer = new ol.layer.Vector({
	style: new ol.style.Style({
    	    fill: new ol.style.Fill({ color: '#000000', weight: 4 }),
    	    stroke: new ol.style.Stroke({ color: '#000000', width: 2 })
	}),
        source: source
      });

      var view = new ol.View({
          center: ol.proj.fromLonLat([37.4, 55.6]),
          zoom: 6
      });

      var map = new ol.Map({
        layers: [ new ol.layer.Tile({ source: new ol.source.OSM() }), wmsLayer, lineLayer],
        target: 'map',
        view: view
      });

        zoomslider = new ol.control.ZoomSlider();
        map.addControl(zoomslider);
//    map.addControl(new OpenLayers.Control.LayerSwitcher());


//    map.events.register('click', map, findLayerClick);

    update_meta();
    update_layer_params();

}

function update_meta () {

    var xmlhttp = new XMLHttpRequest();
    var url = wms_url+'?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities';

    xmlhttp.onreadystatechange = function() {
    if (xmlhttp.readyState == 4 && xmlhttp.status == 200) {

            var doc = StringToXML(xmlhttp.responseText);
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

        } 
//        else  {
//            alert("Trouble getting capabilities doc");
//        OpenLayers.Console.error.apply(OpenLayers.Console, arguments);
//        }
    };


    xmlhttp.open("GET", url, true);
    xmlhttp.send();
}

function update_layer_params() {
    var new_layer = document.getElementsByTagName("select")[0].value;
    var new_time_value = document.getElementsByTagName("select")[1].value;
    if (new_layer!=layer_name) {
        layer_name = new_layer;
        update_meta();
    }
    time_value=new_time_value;
    wmsLayer.getSource().updateParams({'TIME': time_value,'LAYERS': layer_name});
    document.getElementsByTagName("select")[1].value=new_time_value;

    var xmlhttp = new XMLHttpRequest();
    var url = '/vector_wsgi?time='+time_value+'&title='+layer_name;

    xmlhttp.onreadystatechange = function() {
    if (xmlhttp.readyState == 4 && xmlhttp.status == 200) {
	lineLayer.getSource().clear();

	var myArr = JSON.parse(xmlhttp.responseText);
        var features = new Array(myArr.length);

	for (var i=0; i<myArr.length; i++) {
	    var lat = myArr[i][0];
	    var lon = myArr[i][1];
	    var dist= myArr[i][2]*3.6;
	    var head= myArr[i][3];


	    var points=[[lon,lat],destination(lon, lat, dist, head)];
	    for (var j = 0; j < points.length; j++) {
		points[j] = ol.proj.transform(points[j], 'EPSG:4326', 'EPSG:3857');
	    }
	    features[i] = new ol.Feature({
		geometry: new ol.geom.LineString(points)
	    });

	}
    	lineLayer.getSource().addFeatures(features);
    }
    };

    xmlhttp.open("GET", url, true);
    xmlhttp.send();

}

function go(direction) {
    var current_index=document.getElementsByTagName("select")[1].selectedIndex;

    if (direction=="down" && current_index<document.getElementsByTagName("select")[1].length-1)
        document.getElementsByTagName("select")[1].selectedIndex++;
    else if (direction=="up" && current_index>0)
        document.getElementsByTagName("select")[1].selectedIndex--;
    else movie('stop');
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
