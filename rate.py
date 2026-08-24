import streamlit as st
import pandas as pd
import numpy as np
import math
from scipy.optimize import curve_fit
import plotly.graph_objects as go

# Set page configuration
st.set_page_config(page_title="Critical Rate Calculator", page_icon="🛢️", layout="centered")

st.title("Gas Well Water Loading Calculator 🛢️")

# --- 1. SINGLE WELL CALCULATOR ---
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("Fluid Properties")
    gas_density = st.number_input("Gas Density (lb/ft³)", min_value=0.1, value=4.6, step=0.1)
    water_density = st.number_input("Water Density (lb/ft³)", min_value=10.0, value=67.0, step=0.1)
    z_factor = st.number_input("Z-Factor", min_value=0.1000, value=0.8843, step=0.0001, format="%0.4f")

with col2:
    st.subheader("Wellhead Conditions")
    pressure_psig = st.number_input("Wellhead Pressure (psig)", min_value=0.0, value=278.0, step=1.0)
    temp_f = st.number_input("Wellhead Temperature (°F)", min_value=0.0, value=137.0, step=1.0)
    tubing_id = st.number_input("Tubing Inner Diameter (inches)", min_value=1.0, value=4.5, step=0.125)

if st.button("Calculate Critical Rate", type="primary", use_container_width=True):
    if gas_density >= water_density:
        st.error("Error: Gas density cannot be greater than or equal to water density.")
    else:
        pressure_psia = pressure_psig + 14.7
        temp_r = temp_f + 459.67
        area = math.pi * ((tubing_id / 2.0) / 12.0)**2
        sigma = 60.0
        
        critical_velocity = (1.9116 * (sigma * (water_density - gas_density))**0.25) / (gas_density**0.5)
        critical_rate = (3.066894 * pressure_psia * critical_velocity * area) / (temp_r * z_factor)
            
        res_col1, res_col2 = st.columns(2)
        res_col1.metric("Critical Gas Rate", f"{critical_rate:.3f} MMscfd")
        res_col2.metric("Critical Velocity", f"{critical_velocity:.2f} ft/s")

# --- 2. HISTORICAL EXCEL FORECASTING MODULE ---
st.divider()
st.subheader("📈 Historical Data Upload & Forecast")

def arps_hyperbolic(t, qi, Di, b):
    return qi / ((1 + b * Di * t) ** (1 / b))

def parse_robust_dates(series):
    """Parses dates from mixed strings, ISO dates, and Excel serial numbers safely."""
    numeric_series = pd.to_numeric(series, errors='coerce')
    string_mask = numeric_series.isna() & series.notna()
    
    parsed = pd.Series(index=series.index, dtype='datetime64[ns]')
    
    # Parse standard string dates
    if string_mask.any():
        parsed.update(pd.to_datetime(series[string_mask], format='mixed', errors='coerce'))
        
    # Parse numeric Excel serial numbers (e.g., 43251 -> 2018-05-31)
    num_mask = numeric_series.notna()
    if num_mask.any():
        parsed.update(pd.to_datetime(numeric_series[num_mask], unit='D', origin='1899-12-30', errors='coerce'))
        
    return parsed

uploaded_file = st.file_uploader("Upload Historical Well Data (Excel)", type=["xlsx", "xls"])

if uploaded_file is not None:
    # Header row selector in case column headers are not in Row 1
    header_row = st.number_input("Header Row (Set to row number where column names are located)", min_value=1, value=1, step=1) - 1
    
    excel_file = pd.ExcelFile(uploaded_file)
    sheet_name = st.selectbox("Select Sheet", excel_file.sheet_names)
    
    df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=header_row)
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    
    available_cols = list(df_raw.columns)
    
    st.markdown("**Map Excel Columns:**")
    col_map1, col_map2, col_map3 = st.columns(3)
    
    # Auto-detect best guesses for columns
    default_date = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['date', 'time', 'timestamp'])), 0)
    default_gas = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['gas', 'qg', 'rate'])), min(1, len(available_cols)-1))
    default_pwh = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pwh', 'pressure', 'pres'])), min(2, len(available_cols)-1))

    with col_map1:
        date_col = st.selectbox("Date Column", available_cols, index=default_date)
    with col_map2:
        gas_col = st.selectbox("Gas Rate Column", available_cols, index=default_gas)
    with col_map3:
        pwh_col = st.selectbox("Wellhead Pressure Column", available_cols, index=default_pwh)

    if st.button("Run Decline & Forecast Analysis"):
        try:
            df = pd.DataFrame()
            
            # Robust Date Parsing
            df['Date'] = parse_robust_dates(df_raw[date_col])
            
            # Clean numeric values
            df['Gas_Rate'] = pd.to_numeric(df_raw[gas_col], errors='coerce')
            df['Pwh'] = pd.to_numeric(df_raw[pwh_col], errors='coerce')
            
            # Filter out invalid dates and non-positive gas rates
            df = df.dropna(subset=['Date', 'Gas_Rate']).copy()
            df = df[df['Gas_Rate'] > 0]
            
            # Fill missing Pwh values so pressure gaps don't drop valid production rows
            df['Pwh'] = df['Pwh'].replace(0, np.nan).ffill().bfill()
            
            # Sort chronologically
            df = df.sort_values('Date').reset_index(drop=True)
            
            if len(df) < 3:
                st.error("Not enough valid data rows found under selected columns. Adjust Header Row or Column Mapping.")
            else:
                # Convert time index to months
                df['Months'] = (df['Date'] - df['Date'].iloc[0]).dt.days / 30.4375
                qi_input = float(df['Gas_Rate'].iloc[-1])
                
                # Fit Arps Decline Curve
                try:
                    popt, _ = curve_fit(arps_hyperbolic, df['Months'], df['Gas_Rate'], p0=[qi_input, 0.02, 0.5], bounds=(0, [np.inf, 1.0, 1.0]))
                    _, fit_Di, fit_b = popt
                except Exception:
                    fit_Di, fit_b = 0.02, 0.5  # Fallback parameters if fitting noise fails
                
                # Fit Pressure Drop (Linear Regression)
                p_fit = np.polyfit(df['Months'], df['Pwh'], 1)
                monthly_dP = max(-p_fit[0], 0.0)
                last_Pwh_psig = float(df['Pwh'].iloc[-1])

                st.success(f"Calculated Parameters: Decline = {fit_Di*12*100:.1f}%/yr | b = {fit_b:.2f} | Pressure Drop = {monthly_dP:.2f} psi/mo")

                # Forecast 36 Months
                future_months = 36
                future_t = np.arange(1, future_months + 1)
                
                forecast_qg = arps_hyperbolic(future_t, qi_input, fit_Di, fit_b)
                forecast_Pwh_psig = np.maximum(last_Pwh_psig - (monthly_dP * future_t), 0.0)
                forecast_Pwh_psia = forecast_Pwh_psig + 14.7
                
                forecast_qc = []
                for P_psia in forecast_Pwh_psia:
                    temp_r = temp_f + 459.67
                    area = math.pi * ((tubing_id / 2.0) / 12.0)**2
                    vc = (1.9116 * (60.0 * (water_density - gas_density))**0.25) / (gas_density**0.5)
                    qc = (3.066894 * P_psia * vc * area) / (temp_r * z_factor)
                    forecast_qc.append(qc)

                forecast_dates = [df['Date'].iloc[-1] + pd.DateOffset(months=i) for i in range(1, future_months + 1)]

                # Find Intersection Point
                loading_month = None
                for i in range(future_months):
                    if forecast_qg[i] <= forecast_qc[i]:
                        loading_month = forecast_dates[i].strftime("%B %Y")
                        break

                if loading_month:
                    st.warning(f"⚠️ **Forecast Warning:** Liquid loading is expected to begin around **{loading_month}**.")
                else:
                    st.info("✅ Well is projected to remain above the critical rate for the next 36 months.")

                # Plotly Visualization
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df['Date'], y=df['Gas_Rate'], mode='markers+lines', name='Historical Gas Rate', line=dict(color='gray', dash='dot')))
                fig.add_trace(go.Scatter(x=forecast_dates, y=forecast_qg, mode='lines', name='Forecasted Gas Rate (qg)', line=dict(color='#2ecc71', width=3)))
                fig.add_trace(go.Scatter(x=forecast_dates, y=forecast_qc, mode='lines', name='Critical Rate Threshold (qc)', line=dict(color='#e74c3c', width=2, dash='dash')))

                fig.update_layout(
                    title="Production Forecast vs. Critical Gas Rate",
                    xaxis_title="Date",
                    yaxis_title="Gas Rate (MMscfd)",
                    template="plotly_dark",
                    hovermode="x unified"
                )

                st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f"Error executing analysis: {e}")