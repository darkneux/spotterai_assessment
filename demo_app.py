import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
import polyline

API_URL = "http://localhost:8000/api/route-with-fuel/"

st.set_page_config(page_title="Fuel Route Optimizer Demo", layout="wide")

st.title("🛣️ Fuel Route Optimizer Demo")
st.markdown("Visualizer for the Fuel Route Optimization API.")

with st.sidebar:
    st.header("Plan Your Trip")
    start_loc = st.text_input("Start Location", value="San Francisco, CA")
    end_loc = st.text_input("End Location", value="Denver, CO")
    
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
                ).addTo(m)
                
                # Add Start and End markers
                folium.Marker(decoded_path[0], popup="Start", icon=folium.Icon(color="green", icon="play")).addTo(m)
                folium.Marker(decoded_path[-1], popup="End", icon=folium.Icon(color="red", icon="stop")).addTo(m)
                
                # Add Fuel Stops
                st.subheader("Optimal Fuel Stops")
                stops_data = []
                for stop in fuel_plan["stops"]:
                    # Add to map
                    popup_text = f"<b>{stop['name']}</b><br>Price: ${stop['price_per_gallon']:.2f}/gal<br>Buy: {stop['gallons_purchased']:.1f} gal<br>Cost: ${stop['cost']:.2f}"
                    folium.Marker(
                        location=[stop["lat"], stop["lng"]],
                        popup=popup_text,
                        icon=folium.Icon(color="orange", icon="gas-pump", prefix="fa")
                    ).addTo(m)
                    
                    # Add to table data
                    stops_data.append({
                        "Station": stop["name"],
                        "Mile Marker": f"{stop['distance_along_route_miles']:.1f}",
                        "Price/Gal": f"${stop['price_per_gallon']:.2f}",
                        "Gallons Bought": f"{stop['gallons_purchased']:.1f}",
                        "Cost": f"${stop['cost']:.2f}"
                    })
                
                # Render the map
                st_folium(m, width=1200, height=600)
                
                # Render the data table
                st.table(stops_data)
                
            else:
                st.error(f"API Error: {data.get('error', {}).get('message', 'Unknown Error')}")
                
        except requests.exceptions.ConnectionError:
            st.error("Failed to connect to the backend API. Is the Django server running on localhost:8000?")
