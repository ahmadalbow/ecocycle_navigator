from functools import reduce
import operator
import openrouteservice as ors
import folium
from shapely.geometry import LineString, Point
from shapely.ops import transform
import pyproj

# Initialize the client with your API key
client = ors.Client(key="5b3ce3597851110001cf624886ac3f61a5764b1c9d35363eb9a2c4a9")

# Create a folium map
m = folium.Map(location=[51.048431, 13.736864], tiles="cartodbpositron", zoom_start=13)

# Define start and end coordinates (reversed to match the API's expected [lng, lat] format)
coords = [
    list(reversed([51.047017, 13.738455])), 
    list(reversed([51.05237, 12.74082]))
]

# Request directions with alternative routes (up to 3)
route = client.directions(
    coordinates=coords,
    profile='cycling-regular',
    format='geojson',
    alternative_routes={
        "target_count": 3,     # Request 3 routes
        "share_factor": 0.2,   # Adjusts similarity between routes
        "weight_factor": 5     # Allows alternatives to be longer than the best route
    }
)

# List of colors to differentiate routes on the map
colors = ["blue", "red", "green", "yellow"]

# Setup a transformer to project geographic coordinates (EPSG:4326) to a metric system (UTM zone 33N, EPSG:32633)
project = pyproj.Transformer.from_crs("epsg:4326", "epsg:32633", always_xy=True).transform

# We'll store the projected route LineStrings for accident checking
projected_routes = []

# Loop through each route (feature) from the API and add it to the map.
for i, feature in enumerate(route["features"]):
    # The route coordinates are provided in [lng, lat] order.
    route_coords = feature["geometry"]["coordinates"]
    
    # Draw the route on the map (convert each [lng, lat] to [lat, lng] for folium)
    coords_line = [list(reversed(coord)) for coord in route_coords]
    folium.PolyLine(locations=coords_line, color=colors[i % len(colors)]).add_to(m)
    
    # Create a Shapely LineString from the route and project it to a metric CRS
    line = LineString(route_coords)
    line_projected = transform(project, line)
    projected_routes.append(line_projected)

# Define accident data: list of accidents given as [lon, lat]
# (Assuming accident coordinates are provided in the order [longitude, latitude])
accidents = [
    [13.739000, 51.048500],
    [13.742000, 51.053000],
    [13.741886,51.047241],
   [13.635054, 51.097126], 
    # Add more accident points as needed
]

# Define a distance threshold (in meters) for an accident to be considered "on" the route.
threshold = 20

# Check each accident against every route's buffer.
for accident in accidents:
    accident_point = Point(accident)
    # Project the accident point into the same metric coordinate system
    accident_point_projected = transform(project, accident_point)
    
    on_route = False
    # Check if the accident lies within the buffered corridor of any route.
    for line in projected_routes:
        buffer = line.buffer(threshold)
        if buffer.contains(accident_point_projected):
            on_route = True
            break
    
    # Add a marker on the map for the accident.
    # Folium requires the location in [lat, lon] order.
    if on_route:
        folium.Marker(
            location=[accident[1], accident[0]],
            popup="Accident on route",
            icon=folium.Icon(color="red", icon="exclamation-triangle", prefix='fa')
        ).add_to(m)
    else:
        # Optionally mark accidents that are not near any route
        folium.Marker(
            location=[accident[1], accident[0]],
            popup="Accident off route",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)

# Finally, show the map in your browser
m.show_in_browser()
