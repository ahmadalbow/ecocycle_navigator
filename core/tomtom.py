import requests
import folium

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

    def get_traffic_flow(self, coordinate, zoom=10):
        """
        Get traffic flow information at a given coordinate using TomTom's Traffic Flow API.

        Parameters:
            coordinate (tuple): A point on the map in (latitude, longitude) order.
            zoom (int): The zoom level for the traffic flow request (affects granularity).

        Returns:
            dict: The JSON response from the Traffic Flow API, or None if an error occurs.
        """
        # TomTom Traffic Flow API endpoint (absolute version).
        base_url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute"
        url = f"{base_url}/{zoom}/json"
        # For traffic API, the coordinate is typically provided as "lat,lon"
        params = {
            "point": f"{coordinate[0]},{coordinate[1]}",
            "key": self.api_key
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"An error occurred while fetching traffic flow: {e}")
            return None


if __name__ == "__main__":
    # Replace with your actual TomTom API key.
    router = TomTomRouter(api_key="eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF")
    
    # IMPORTANT: TomTom Routing API expects coordinates in (longitude, latitude) order.
    # In this example the points are provided as (latitude, longitude) for clarity.
    # Adjust accordingly if necessary.
    # Provided examples (Dresden area):
    # Start: [51.047017, 13.738455]
    # End:   [51.05237,  13.94082]
    # Here we assume the provided tuples are (latitude, longitude). For routing, convert them:
    start_point = (51.047017, 13.738455)  # (lon, lat)
    end_point   = (51.05237, 13.75555 )    # (lon, lat)
    
    routes = router.get_route(start_point, end_point, travelMode="bicycle")
    
    if routes:
        print("Route information received:")
        try:
            # Adjust extraction if needed based on the actual route structure.
            route_points = routes["routes"][0]["legs"][0]["points"]
            routlist = ""
            for i in route_points:
                latitude = i["latitude"]
                longitude = i["longitude"]
                routlist = routlist + f",[{latitude},{longitude}]"
            print(route_points)
        except (KeyError, IndexError) as e:
            print(f"Unexpected route JSON structure: {e}")
            route_points = None

        if route_points:
            # Create a folium map centered at the start point (converted for Folium: [lat, lon]).
            m = folium.Map(location=[start_point[0], start_point[1]], zoom_start=13, tiles="cartodbpositron")
            
            # Add markers for start and end points.
            folium.Marker(location=[start_point[0], start_point[1]], popup="Start", icon=folium.Icon(color="green")).add_to(m)
            folium.Marker(location=[end_point[0], end_point[1]], popup="End", icon=folium.Icon(color="red")).add_to(m)
            
            # Convert route points to [lat, lon] for Folium.
            # Here we assume each point is a dictionary with keys "latitude" and "longitude".
            route_latlon = [[pt["latitude"], pt["longitude"]] for pt in route_points]
            
            # Draw the route on the map.
            folium.PolyLine(route_latlon, color="blue", weight=2.5, opacity=1).add_to(m)
            
            # Optionally, add circle markers along the route.
            for lat, lon in route_latlon:
                folium.CircleMarker(location=[lat, lon], radius=1, color="purple").add_to(m)
            
            # ========================
            # GET TRAFFIC FLOW INFO:
            # ========================
            # For demonstration, we sample every 5th point along the route.
            sampled_points = route_latlon[::5]
            for pt in sampled_points:
                # Here pt is in (lat, lon) order, which is what our traffic flow API expects.
                traffic_info = router.get_traffic_flow(pt)
                if traffic_info:
                    # Extract some traffic flow values.
                    flow_data = traffic_info.get("flowSegmentData", {})
                    current_speed = flow_data.get("currentSpeed", "N/A")
                    free_flow_speed = flow_data.get("freeFlowSpeed", "N/A")
                    # You can extract more details as needed.
                    popup_text = (f"Traffic Info:\n"
                                  f"Current Speed: {current_speed} km/h\n"
                                  f"Free Flow Speed: {free_flow_speed} km/h")
                    
                    # Add a marker with the traffic flow information.
                    folium.Marker(
                        location=[pt[0], pt[1]],
                        popup=popup_text,
                        icon=folium.Icon(color="orange", icon="info-sign")
                    ).add_to(m)
            
            # Show the map in the browser.
            m.show_in_browser()
            print("Map displayed with route and traffic flow markers.")
        else:
            print("Could not extract route points from the response.")
    else:
        print("Failed to retrieve route information.")
