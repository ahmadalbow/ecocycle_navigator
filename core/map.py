from functools import reduce
import operator
import openrouteservice as ors
import folium
import requests
from shapely.geometry import LineString, Point
from shapely.ops import transform
import pyproj



import openrouteservice as ors
import folium

class Map:
    def __init__(self, api_key, center=[51.048431, 13.736864], zoom_start=13, tiles="cartodbpositron"):
        """
        Initialize the Map instance.
        
        Attributes:
        - api_key: Your OpenRouteService API key.
        - center: The center of the folium map (default is set for Dresden).
        - zoom_start: Initial zoom level for the map.
        - tiles: The map tileset to use (e.g., "cartodbpositron").
        - client: The OpenRouteService client for routing requests.
        - map: The Folium map object.
        - routes: A list to store route data returned by the API.
        """
        self.api_key = api_key
        self.client = ors.Client(key=api_key)
        self.center = center
        self.zoom_start = zoom_start
        self.tiles = tiles
        self.map = folium.Map(location=self.center, zoom_start=self.zoom_start, tiles=self.tiles)
        self.routes = []  # To store route data

    def get_route(self, start, end, profile='cycling-regular', alternative_routes=None):
        """
        Get a route between two points using the OpenRouteService API.
        
        Parameters:
        - start: A list or tuple representing the starting point [lat, lon].
        - end: A list or tuple representing the ending point [lat, lon].
        - profile: The travel mode (e.g., 'cycling-regular', 'foot-walking', etc.).
        - alternative_routes: An optional dictionary for alternative route parameters.
          Default: {"target_count": 3, "share_factor": 0.2, "weight_factor": 5}
          
        Returns:
        - route: The route data in GeoJSON format.
        """
        # Provide default alternative_routes if none are provided
        if alternative_routes is None:
            alternative_routes = {"target_count": 3, "share_factor": 0.2, "weight_factor": 3}
        
        # OpenRouteService expects coordinates in [lon, lat] order.
        # We assume the inputs are in [lat, lon] so we reverse them.
        start_rev = list(reversed(start))
        end_rev = list(reversed(end))
        coords = [start_rev, end_rev]
        
        # Request the route from OpenRouteService
        route = self.client.directions(
            coordinates=coords,
            profile=profile,
            format='geojson',
           alternative_routes=alternative_routes
        )
        
        # Store the route in the object's routes list
        self.routes.append(route)
        return route

import requests

class TomTomRouter:
    def __init__(self, api_key):
        """
        Initialize the TomTomRouter with your TomTom API key.
        
        Parameters:
        api_key (str): Your TomTom API key.
        """
        self.api_key = api_key

    def get_route(self, start, end, travelMode="bicycle", alternative_routes=None):
        """
        Get possible routes between two points using the TomTom Routing API.
        
        Parameters:
          start (tuple): Starting coordinate in (longitude, latitude) order.
          end (tuple): Ending coordinate in (longitude, latitude) order.
          travelMode (str): The mode of travel (e.g. "bicycle", "car", "pedestrian").
          alternative_routes (int or bool, optional): Parameter to request alternative routes.
              If provided, this value will be used to indicate how many alternative routes to compute.
        
        Returns:
          dict: The JSON response from the TomTom API containing route information,
                or None if an error occurs.
        """
        # Base URL for the TomTom Routing API
        base_url = "https://api.tomtom.com/routing/1/calculateRoute"
        
        # Build the route coordinate string in the format "lon,lat:lon,lat"
        route_coords = f"{start[0]},{start[1]}:{end[0]},{end[1]}"
        url = f"{base_url}/{route_coords}/json"
        
        # Set up query parameters.
        params = {
            "key": self.api_key,
            "travelMode": travelMode
        }
        
        # Using correct parameter names for alternative routes.
        if alternative_routes is not None:
            
            params["maxAlternatives"] = alternative_routes

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()  # Will raise an HTTPError for bad responses.
            return response.json()
        except requests.RequestException as e:
            print(f"An error occurred while fetching the route: {e}")
            return None

if __name__ == "__main__":
    # Replace with your actual TomTom API key.
    router = TomTomRouter(api_key="eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF")
    
    # IMPORTANT: TomTom API expects coordinates in (longitude, latitude) order.
    # For Dresden in your code example, the points are given as [lat, lon].
    # Here we convert them accordingly.
    # Provided example:
    # Start: [51.047017, 13.738455]  -> Converted to (13.738455, 51.047017)
    # End:   [51.05237,  13.94082]   -> Converted to (13.94082, 51.05237)
    start_point = ( 51.047017,13.738455)  # (lon, lat)
    end_point   = (  51.05237,13.94082)    # (lon, lat)
    
    routes = router.get_route(start_point, end_point, travelMode="bicycle", alternative_routes=3)
    
    if routes:
        print("Route information received:")
        # Example assumes the following structure:
        # routes = { "routes": [ { "legs": [ { "points": [ [lon, lat], ... ] } ] } ] }
        try:
            route_points = routes["routes"][2]["legs"][0]["points"]
        except (KeyError, IndexError) as e:
            print(f"Unexpected route JSON structure: {e}")
            route_points = None

        if route_points:
            # Create a folium map centered at the start point.
            # Note: for folium, coordinates are given in [lat, lon] order.
            m = folium.Map(location=[start_point[0], start_point[1]], zoom_start=13, tiles="cartodbpositron")
            
            # Add a marker for the start point.
            folium.Marker(location=[start_point[0], start_point[1]], popup="Start", icon=folium.Icon(color="green")).add_to(m)
            
            # Add a marker for the end point.
            folium.Marker(location=[end_point[0], end_point[1]], popup="End", icon=folium.Icon(color="red")).add_to(m)
            
            # Convert the route points from (lon, lat) to (lat, lon) for folium.
            route_latlon = [[pt["latitude"], pt["longitude"]] for pt in route_points]
            
            # Add the route as a PolyLine on the map.
            folium.PolyLine(route_latlon, color="blue", weight=2.5, opacity=1).add_to(m)
            
            # Optionally, add small circle markers along the route.
            for lat, lon in route_latlon:
                folium.CircleMarker(location=[lat, lon], radius=1, color="purple").add_to(m)
            
            # Save the map to an HTML file.
            m.show_in_browser()
            print("Map saved to route_map.html. Open it in your browser to view the route.")
        else:
            print("Could not extract route points from the response.")
    else:
        print("Failed to retrieve route information.")


'if __name__ == "__main__":'
    # Replace 'YOUR_API_KEY' with your actual OpenRouteService API key.
    # my_map = Map(api_key="5b3ce3597851110001cf624886ac3f61a5764b1c9d35363eb9a2c4a9")
    
    # # Define two points in [lat, lon] format.
    # point_a = [51.047017, 13.738455]
    # point_b = [51.05237, 13.94082]
    
    # # Retrieve the route
    # route_data = my_map.get_route(point_a, point_b)
    
    # # (Optional) Do additional processing like adding the route to the map or displaying it.
    # print(route_data["features"][0]["geometry"]["coordinates"])
    # m = folium.Map(location=[51.048431, 13.736864], tiles="cartodbpositron", zoom_start=13)
    # for p in route_data["features"][1]["geometry"]["coordinates"]:
    #     folium.Marker(
    #         location=[p[1], p[0]],
    #         popup="Accident on route",
            
    #     ).add_to(m)
    # m.show_in_browser()

    # Replace with your actual TomTom API key.
