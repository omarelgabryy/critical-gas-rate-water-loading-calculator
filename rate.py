import streamlit as st
import math

# Set page configuration
st.set_page_config(page_title="Critical Rate Calculator", page_icon="🛢️", layout="centered")

# Customizing the UI with a title and description
st.title("Gas Well Water Loading Calculator 🛢️")
st.markdown("""
This application calculates the **Turner Critical Gas Rate** required to keep a gas well unloaded. 
Enter your well parameters below to determine the minimum flow rate needed to lift water droplets to the surface.
""")

st.divider()

# Creating a clean two-column layout for user inputs
col1, col2 = st.columns(2)

with col1:
    st.subheader("Fluid Properties")
    # Changed from Specific Gravity to Gas Density
    gas_density = st.number_input("Gas Density (lb/ft³)", min_value=0.1, value=4.6, step=0.1)
    water_density = st.number_input("Water Density (lb/ft³)", min_value=10.0, value=67.0, step=0.1)
    z_factor = st.number_input("Z-Factor", min_value=0.1, value=0.88433, step=0.00001)

with col2:
    st.subheader("Wellhead Conditions")
    pressure = st.number_input("Wellhead Pressure (psia)", min_value=10.0, value=292.7, step=0.1)
    temp_f = st.number_input("Wellhead Temperature (°F)", min_value=0.0, value=137.0, step=1.0)
    tubing_id = st.number_input("Tubing Inner Diameter (inches)", min_value=1.0, value=4.5, step=0.125)

st.divider()

# Calculation Button
if st.button("Calculate Critical Rate", type="primary", use_container_width=True):
    
    if gas_density >= water_density:
        st.error("Error: Gas density cannot be greater than or equal to water density. Please check your inputs.")
    else:
        # 1. Convert Temperature to Rankine
        temp_r = temp_f + 460.0
        
        # 2. Calculate Cross Sectional Area (ft2)
        # Tubing ID is in inches. Divide by 24 to get radius in feet.
        area = math.pi * (tubing_id / 24.0)**2
        
        # 3. Surface Tension for Water (dynes/cm)
        sigma = 60.0
        
        # 4. Calculate Turner Critical Velocity (ft/s) 
        # Using 1.92 constant to match your Excel sheet
        critical_velocity = (1.92 * (sigma * (water_density - gas_density))**0.25) / (gas_density**0.5)
            
        # 5. Calculate Critical Gas Rate (MMscfd)
        # Using 3.067 constant to match your Excel sheet
        critical_rate = (3.067 * pressure * critical_velocity * area) / (temp_r * z_factor)
            
        # Display Results
        st.success("Calculation Successful!")
            
        res_col1, res_col2 = st.columns(2)
        res_col1.metric("Critical Gas Rate", f"{critical_rate:.3f} MMscfd")
        res_col2.metric("Critical Velocity", f"{critical_velocity:.2f} ft/s")
            
        if critical_rate > 0:
            st.info(f"💡 The well must produce more than **{critical_rate:.3f} MMscfd** to continuously lift water to the surface and avoid liquid loading.")