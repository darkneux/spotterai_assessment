import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
import polyline

API_URL = "http://localhost:8000/api/route-with-fuel/"

st.set_page_config(page_title="Fuel Route Optimizer Demo", layout="wide")

st.title("🛣️ Fuel Route Optimizer Demo")
st.markdown("Visualizer for the Fuel Route Optimization API.")

# Initialize session state to store API results
if "api_data" not in st.session_state:
    st.session_state.api_data = None

KNOWN_CITIES = [
    "San Francisco, CA", "Los Angeles, CA", "San Diego, CA", "Sacramento, CA",
    "Las Vegas, NV", "Phoenix, AZ", "Denver, CO", "Salt Lake City, UT",
    "Dallas, TX", "Houston, TX", "Austin, TX", "Oklahoma City, OK",
    "Chicago, IL", "St Louis, MO", "Kansas City, MO", "New York, NY",
    "Boston, MA", "Atlanta, GA", "Miami, FL", "Seattle, WA",
    "Portland, OR", "Minneapolis, MN", "Nashville, TN", "Memphis, TN",
    "Albuquerque, NM", "Amarillo, TX", "Flagstaff, AZ", "Barstow, CA"
]

with st.sidebar:
    st.header("Plan Your Trip")
    start_loc = st.selectbox("Start Location", KNOWN_CITIES, index=0)
    end_loc = st.selectbox("End Location", KNOWN_CITIES, index=6)
    
    # Optional parameters we can send to our new smart cache
    max_range = st.slider("Vehicle Max Range (miles)", 100, 1000, 500, step=50)
    mpg = st.slider("Miles Per Gallon (MPG)", 5, 40, 10, step=1)
    
    plan_button = st.button("Optimize Route")

if plan_button:
    with st.spinner("Calculating optimal route and fuel stops..."):
        payload = {
            "start": start_loc,
            "end": end_loc,
            "max_range_miles": max_range,
            "miles_per_gallon": mpg
        }
        
        try:
            response = requests.post(API_URL, json=payload)
            data = response.json()
            
            if response.status_code == 200:
                # Save the successful data to session state
                st.session_state.api_data = data
            else:
                st.session_state.api_data = None
                st.error(f"API Error: {data.get('error', {}).get('message', 'Unknown Error')}")
                
        except requests.exceptions.ConnectionError:
            st.session_state.api_data = None
            st.error("Failed to connect to the backend API. Is the Django server running on localhost:8000?")

# Render the UI if we have data in the session state
if st.session_state.api_data is not None:
    data = st.session_state.api_data
    route_data = data["route"]
    fuel_plan = data["fuel_plan"]
    meta = data["meta"]
    
    # --- Metrics ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Fuel Cost", f"${fuel_plan['total_cost']:.2f}")
    col2.metric("Total Distance", f"{route_data['distance_miles']:.1f} mi")
    col3.metric("Total Gallons", f"{fuel_plan['total_gallons']:.1f} gal")
    col4.metric("Cache Hit", str(meta['cache_hit']))
    
    st.success(f"Route calculated successfully via {route_data['provider']}!")
    
    # --- Map Rendering ---
    decoded_path = polyline.decode(route_data["polyline"])
    
    # Center map on the middle of the route
    mid_point = decoded_path[len(decoded_path) // 2]
    m = folium.Map(location=mid_point, zoom_start=5)
    
    # Draw the highway route
    folium.PolyLine(
        decoded_path,
        weight=5,
        color='blue',
        opacity=0.7
    ).add_to(m)
    
    # Add Start and End markers
    folium.Marker(decoded_path[0], popup="Start", icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker(decoded_path[-1], popup="End", icon=folium.Icon(color="red", icon="stop")).add_to(m)
    
    st.subheader("Optimal Fuel Stops")
    
    # Prepare table data
    stops_data = []
    for stop in fuel_plan["stops"]:
        stops_data.append({
            "Station": stop["name"],
            "Mile Marker": f"{stop['distance_along_route_miles']:.1f}",
            "Price/Gal": f"${stop['price_per_gallon']:.2f}",
            "Gallons Bought": f"{stop['gallons_purchased']:.1f}",
            "Cost": f"${stop['cost']:.2f}"
        })
        
    # Check if a row is selected in the table
    selected_idx = None
    if "station_table" in st.session_state:
        selected_rows = st.session_state.station_table.get("selection", {}).get("rows", [])
        if selected_rows:
            selected_idx = selected_rows[0]

    # Add Fuel Stops to Map
    for idx, stop in enumerate(fuel_plan["stops"]):
        is_selected = (idx == selected_idx)
        
        # Highlight the selected station
        color = "red" if is_selected else "orange"
        icon_type = "star" if is_selected else "gas-pump"
        
        popup_text = f"<b>{stop['name']}</b><br>Price: ${stop['price_per_gallon']:.2f}/gal<br>Buy: {stop['gallons_purchased']:.1f} gal<br>Cost: ${stop['cost']:.2f}"
        
        marker = folium.Marker(
            location=[stop["lat"], stop["lng"]],
            popup=popup_text,
            icon=folium.Icon(color=color, icon=icon_type, prefix="fa")
        )
        marker.add_to(m)
        
        # If this is the selected station, center the map on it
        if is_selected:
            m.location = [stop["lat"], stop["lng"]]
            m.zoom_start = 8

    # Render the map 
    st_folium(m, width=1200, height=500, returned_objects=[])
    
    # Render the interactive data table
    st.markdown("👇 **Click on any row below to highlight and zoom to that station on the map.**")
    st.dataframe(
        stops_data,
        key="station_table",
        on_select="rerun",
        selection_mode="single-row",
        use_container_width=True,
        hide_index=True
    )
