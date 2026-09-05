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
var time_value = -1; // current time
// update every 5 minutes 
var updater = setInterval(update_times_and_refresh,300000);

var bearing=45;
var interval_id=0;

let WMS_TOKEN = null;
let LEGEND_BASE_URL = null;

async function refreshToken() {
    // /get_token answers 429 when this address is over its budget, and
    // that body is not JSON.  Keep whatever token we already hold rather
    // than throwing: it has up to 60 s left on it, and the next refresh
    // is 30 s away.
    const res = await fetch("/get_token");
    if (!res.ok) return;

    const data = await res.json();
    WMS_TOKEN = data.token;

    refreshLegend(); // ð¥ instant legend update
}

function refreshLegend() {
    if (!LEGEND_BASE_URL || !WMS_TOKEN) return;

    const img = document.getElementById("map_legend");

    const newUrl = LEGEND_BASE_URL + "&token=" + encodeURIComponent(WMS_TOKEN);

    // avoid redundant reloads
    if (img.dataset.lastUrl !== newUrl) {
        img.src = newUrl;
        img.dataset.lastUrl = newUrl;
    }
}

async function update_times_and_refresh () {
    await refreshToken(); 
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


async function init() {

      await refreshToken();
      setInterval(refreshToken, 30000); // refresh every 30s

      layer_name = document.getElementsByTagName("select")[0].value;

      var wmsSource = new ol.source.ImageWMS({
        url: wms_url,
        params: {'LAYERS': layer_name},

        imageLoadFunction: function(image, src) {
           if (!WMS_TOKEN) return;
           const separator = src.includes("?") ? "&" : "?";
           image.getImage().src = src + separator + "token=" + encodeURIComponent(WMS_TOKEN);
        },

        ratio: 1,
        serverType: 'geoserver'
      });

      wmsLayer = new ol.layer.Image({
	  opacity : 0.7,
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

      map = new ol.Map({
        layers: [ new ol.layer.Tile({ source: new ol.source.OSM({ 
             url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' }) 
              }), wmsLayer, lineLayer],
        target: 'map',
        view: view
      });

//    map.addControl(new OpenLayers.Control.LayerSwitcher());

     const source1 = new ol.source.Vector();
     const layer = new ol.layer.Vector({
       source: source1,
      });
     map.addLayer(layer);

    navigator.geolocation.watchPosition(
      function (pos) {
    const coords = [pos.coords.longitude, pos.coords.latitude];
    const accuracy = ol.geom.Polygon.circular(coords, pos.coords.accuracy);
    source1.clear(true);
    source1.addFeatures([
      new ol.Feature(
        accuracy.transform('EPSG:4326', map.getView().getProjection())
      ),
      new ol.Feature(new ol.geom.Point(ol.proj.fromLonLat(coords))),
    ]);
  },
  function (OAerror) {
    alert(`ERROR: ${error.message}`);
  },
  {
    enableHighAccuracy: true,
  }
);

    zoomslider = new ol.control.ZoomSlider()
    map.addControl(zoomslider);


const locate = document.createElement('div');
locate.className = 'ol-control ol-unselectable locate';
locate.innerHTML = '<button title="Locate me">â—Ž</button>';
locate.addEventListener('click', function () {
  if (!source1.isEmpty()) {
    map.getView().fit(source1.getExtent(), {
      maxZoom: 7,
      duration: 500,
    });
 }
});
map.addControl(
  new ol.control.Control({
    element: locate,
  })
);

    map.on('click',  findLayerClick)

    update_meta();
    update_layer_params();

}

function update_meta () {

    var xmlhttp = new XMLHttpRequest();
    var url = wms_url+'?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities&token='+encodeURIComponent(WMS_TOKEN);

    xmlhttp.onreadystatechange = function() {
    if (xmlhttp.readyState == 4 && xmlhttp.status == 200) {

            var doc = StringToXML(xmlhttp.responseText);
            var layers = doc.getElementsByTagName("Layer")[0].getElementsByTagName("Layer");
            for (i=0;i<layers.length;i++) {
                if (layers[i].getElementsByTagName("Name")[0].childNodes[0].nodeValue.split(",")[0]==layer_name.split(",")[0]) {
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
		    LEGEND_BASE_URL = layers[i].getElementsByTagName("LegendURL")[0]
			.getElementsByTagName("OnlineResource")[0]
			.getAttributeNS('http://www.w3.org/1999/xlink', 'href')
			.replace('http://','https://');

		    // initial load
		    refreshLegend();
                    if (time_value==-1) {
                        time_value = document.getElementsByTagName("select")[1].value;
                    } else {
                        document.getElementsByTagName("select")[1].value=time_value;
                    }
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

    load_vectors(false);
}

/*
 * The phenomena vectors need a token now.  init() and the five-minute
 * refresh both mint one before anything is drawn, so WMS_TOKEN is normally
 * ready by the time this runs; the 403 retry covers the one case where it
 * is not, a token that went stale between two of the 30 s refreshes.
 */
function load_vectors(retrying) {

    if (!WMS_TOKEN) {
        if (!retrying) refreshToken().then(function() { load_vectors(true); });
        return;
    }

    var xmlhttp = new XMLHttpRequest();
    var url = '/vector_wsgi?time='+time_value+'&title='+layer_name
            + '&token='+encodeURIComponent(WMS_TOKEN);

    xmlhttp.onreadystatechange = function() {
    if (xmlhttp.readyState != 4) return;

    if (xmlhttp.status == 403 && !retrying) {
        refreshToken().then(function() { load_vectors(true); });
        return;
    }

    if (xmlhttp.status == 200) {
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

  const viewResolution = /** @type {number} */ (map.getView().getResolution());
  const url = wmsLayer.getSource().getFeatureInfoUrl(
    event.coordinate,
    viewResolution,
    map.getView().getProjection(),
    {'INFO_FORMAT': 'text/html'},
  ) +'&token='+encodeURIComponent(WMS_TOKEN);


        if (url) {
          document.getElementById('featureinfo').innerHTML =
              '<iframe seamless src="' + url + '"></iframe>';
        }

//    OpenLayers.Request.GET({url: url,callback:setHTML,scope:this});

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
    window.location = wms_tools_url + "?ACTION=download_geotiff&TIME=" + time_value + "&LAYER=" + layer_name.split(",")[0];
}

function view_accumulated_rain () {
    window.location = wms_tools_url + "?ACTION=accumulated_rain&TIME=" + time_value + "&LAYER=" + layer_name.split(",")[0];
}

function export_to_kmz () {
    var start_time = document.getElementsByTagName("select")[2].value;
    var end_time = document.getElementsByTagName("select")[3].value;
    if (document.getElementsByTagName("select")[3].selectedIndex>document.getElementsByTagName("select")[2].selectedIndex) {
        alert( "check start and end times" )
        return
    }
    window.location = wms_tools_url + "?ACTION=export_to_kmz&START_TIME=" + start_time + "&END_TIME=" + end_time + "&LAYER=" + layer_name.split(",")[0];
}
