$.getJSON("tiles.json", function(data) {
    var tiles = [];
    $.each(data, function(timestamp, path) {
	tiles.push({
	    label: timestamp.slice(-5),
	    timestamp: timestamp,
	    path: path
	});
    });
    tiles.sort(function(left, right) {
	return left.timestamp.localeCompare(right.timestamp);
    });
//    tiles = tiles.slice(-12);

mapboxgl.accessToken = 'insert-yourmapbox-token-here';
var map = new mapboxgl.Map({
    container: 'map',
    style: 'mapbox://styles/mapbox/streets-v9',
    maxZoom: 10,
    minZoom: 4,
    zoom: 5,
    center: [40, 56]
});

// Add zoom and rotation controls to the map.
map.addControl(new mapboxgl.NavigationControl());

//TODO add legend 
//    var legend = L.mapbox.legendControl().addLegend(document.getElementById('legend').innerHTML).addTo(map);


    function update(index) {
	var tile = tiles[index];
	$("#slider").find(".ui-slider-handle").text(tile.label);
//	overlay.setUrl(tile.path);
    }

    $("#slider").slider({
	value: 0,
	min: 0,
	max: tiles.length-1,
	step: 1,
	slide: function(event, ui) {
	    update(ui.value);
	},
	change: function(event, ui) {
	    update(ui.value);
	}
    });

map.on('load', function() {

    var frameCount = tiles.length-1;
    for (var i = 0; i < frameCount; i++) {

        map.addLayer({
            id: 'radar' + i,
            source: {
                type: 'image',
                url: 'http://www.nowcast.ru/demo/viz/' + tiles[i].path,
                coordinates: [
	[13.097561869355811, 66.51278036226859],
	[70.89516724960582, 66.51278036226859],
	[70.89516724960582, 40.142145834290915],
	[13.097561869355811, 40.142145834290915]
                ]
            },
            type: 'raster',
            paint: {
                'raster-opacity': 0,
                'raster-opacity-transition': {
                    duration: 0
                }
            }
        });
    }

    var frame = frameCount - 1;
    setInterval(function() {
        map.setPaintProperty('radar' + frame, 'raster-opacity', 0);
        frame = (frame + 1) % frameCount;
        map.setPaintProperty('radar' + frame, 'raster-opacity', 0.7);
        $("#slider").slider('value', frame);
	$("#slider").find(".ui-slider-handle").text(tiles[frame].label);
    }, 200);

});
});
