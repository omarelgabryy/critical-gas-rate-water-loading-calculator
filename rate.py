import streamlit as st
import pandas as pd
import numpy as np
import math
from scipy.optimize import curve_fit
import plotly.graph_objects as go

# Set page configuration
st.set_page_config(page_title="Gas Well Performance & Critical Rate", page_icon="🛢️", layout="centered")

st.title("Gas Well Performance & Pressure Forecast 🛢️")

# --- 1. SINGLE WELL CALCULATOR & INPUTS ---
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("Fluid Properties")
    gas_density = st.number_input("Gas Density (lb/ft³)", min_value=0.1, value=4.6, step=0.1)
    water_density = st.number_input("Water Density (lb/ft³)", min_value=10.0, value=67.0, step=0.1)
    z_factor = st.number_input("Z-Factor", min_value=0.1000, value=0.8843, step=0.0001, format="%0.4f")

with col2:
    st.subheader("Wellhead & Line Conditions")
    pressure_psig = st.number_input("Current Wellhead Pressure (psig)", min_value=0.0, value=278.0, step=1.0)
    flowline_psig = st.number_input("Min Flowline Pressure Limit (psig)", min_value=0.0, value=50.0, step=5.0)
    temp_f = st.number_input("Wellhead Temperature (°F)", min_value=0.0, value=137.0, step=1.0)
    tubing_id = st.number_input("Tubing Inner Diameter (inches)", min_value=1.0, value=4.5, step=0.125)

if st.button("Calculate Current Critical Rate", type="primary", use_container_width=True):
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
        res_col1.metric("Critical Gas Rate (qc)", f"{critical_rate:.3f} MMscfd")
        res_col2.metric("Critical Velocity (vc)", f"{critical_velocity:.2f} ft/s")

# --- 2. HISTORICAL EXCEL FORECASTING MODULE ---
st.divider()
st.subheader("📈 Historical Analysis & Dual Limits Forecast")

def arps_hyperbolic(t, qi, Di, b):
    return qi / ((1 + b * Di * t) ** (1 / b))

def parse_robust_dates(series):
    return pd.to_datetime(series, errors='coerce')

def clean_numeric(series):
    """Converts strings like 'S.I', blanks, or formatted text into numeric floats."""
    cleaned = series.astype(str).str.replace(',', '', regex=False).str.strip()
    return pd.to_numeric(cleaned, errors='coerce')

uploaded_file = st.file_uploader("Upload Historical Well Data (Excel)", type=["xlsx", "xls"])

if uploaded_file is not None:
    header_row = st.number_input("Header Row (Row number where column names are located)", min_value=1, value=1, step=1) - 1
    
    excel_file = pd.ExcelFile(uploaded_file)
    sheet_name = st.selectbox("Select Sheet", excel_file.sheet_names)
    
    df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=header_row)
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    
    available_cols = list(df_raw.columns)
    
    st.markdown("**Map Excel Columns:**")
    col_map1, col_map2, col_map3, col_map4 = st.columns(4)
    
    # Auto-detect column headers
    default_date = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['date', 'time', 'timestamp'])), 0)
    default_gas = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['gas', 'qg', 'rate', 'fn'])), min(1, len(available_cols)-1))
    default_pwh = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pwh', 'pressure', 'pres', 'fq'])), min(2, len(available_cols)-1))
    default_pfl = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pfl', 'flowline', 'line'])), -1)

    with col_map1:
        date_col = st.selectbox("Date Column", available_cols, index=default_date)
    with col_map2:
        gas_col = st.selectbox("Gas Rate Column", available_cols, index=default_gas)
    with col_map3:
        pwh_col = st.selectbox("Wellhead Pressure (Pwh)", available_cols, index=default_pwh)
    with col_map4:
        pfl_col_options = ["Use Input Field Value Above"] + available_cols
        pfl_select_index = (default_pfl + 1) if default_pfl != -1 else 0
        pfl_col = st.selectbox("Flowline Pressure (Pfl)", pfl_col_options, index=pfl_select_index)

    if st.button("Run Complete Forecast Analysis"):
        try:
            df = pd.DataFrame()
            df['Date'] = parse_robust_dates(df_raw[date_col])
            df['Gas_Rate'] = clean_numeric(df_raw[gas_col]).fillna(0.0) # S.I becomes 0.0
            df['Pwh'] = clean_numeric(df_raw[pwh_col])
            
            # Use column data if mapped, otherwise use the numeric input from Section 1
            if pfl_col != "Use Input Field Value Above":
                df['Pfl'] = clean_numeric(df_raw[pfl_col])
            else:
                df['Pfl'] = flowline_psig
            
            # Clean invalid dates and sort chronologically
            df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
            df['Pwh'] = df['Pwh'].replace(0, np.nan).ffill().bfill()
            df['Pfl'] = df['Pfl'].replace(0, np.nan).ffill().bfill()
            
            # Remove trailing blank/shut-in rows beyond last production date
            active_mask = df['Gas_Rate'] > 0
            if not active_mask.any():
                st.error("No positive gas rate data found in the selected gas column.")
            else:
                last_active_index = active_mask.iloc[::-1].idxmax()
                df = df.iloc[:last_active_index + 1].copy().reset_index(drop=True)

                # Filter active production days for DCA curve fitting
                df_active = df[df['Gas_Rate'] > 0].copy().reset_index(drop=True)
                
                # Monthly aggregation
                df_monthly = df_active.set_index('Date').resample('MS').agg({'Gas_Rate': 'mean', 'Pwh': 'mean', 'Pfl': 'mean'}).dropna().reset_index()
                fit_df = df_monthly if len(df_monthly) >= 3 else df_active
                
                # Fit Arps Decline Curve
                peak_idx = fit_df['Gas_Rate'].idxmax()
                df_decline = fit_df.iloc[peak_idx:].copy().reset_index(drop=True)
                if len(df_decline) < 3:
                    df_decline = fit_df.copy().reset_index(drop=True)

                df_decline['Months'] = (df_decline['Date'] - df_decline['Date'].iloc[0]).dt.days / 30.4375
                qi_peak = float(df_decline['Gas_Rate'].iloc[0])
                
                try:
                    popt, _ = curve_fit(
                        arps_hyperbolic, 
                        df_decline['Months'], 
                        df_decline['Gas_Rate'], 
                        p0=[qi_peak, 0.02, 0.5], 
                        bounds=([0, 0.001, 0.01], [np.inf, 1.0, 1.0])
                    )
                    _, fit_Di, fit_b = popt
                except Exception:
                    fit_Di, fit_b = 0.02, 0.5

                # Linear regression for Wellhead Pressure drop rate
                p_fit = np.polyfit(fit_df.index, fit_df['Pwh'], 1)
                monthly_dP = max(-p_fit[0], 0.0)
                
                qi_last = float(df_active['Gas_Rate'].iloc[-1])
                last_Pwh_psig = float(df_active['Pwh'].iloc[-1])
                last_Pfl_psig = float(df_active['Pfl'].iloc[-1]) if pfl_col != "Use Input Field Value Above" else flowline_psig

                st.success(f"Parameters: Annual Decline = {fit_Di*12*100:.1f}% | b = {fit_b:.2f} | Pressure Drop = {monthly_dP:.2f} psi/mo")

                # Project 36 months forward
                future_months = 36
                last_historical_date = df['Date'].iloc[-1]
                future_t = np.arange(1, future_months + 1)
                
                forecast_qg = arps_hyperbolic(future_t, qi_last, fit_Di, fit_b)
                forecast_Pwh_psig = np.maximum(last_Pwh_psig - (monthly_dP * future_t), 0.0)
                forecast_Pfl_psig = np.full(future_months, last_Pfl_psig)
                
                forecast_Pwh_psia = forecast_Pwh_psig + 14.7
                forecast_qc = []
                for P_psia in forecast_Pwh_psia:
                    temp_r = temp_f + 459.67
                    area = math.pi * ((tubing_id / 2.0) / 12.0)**2
                    vc = (1.9116 * (60.0 * (water_density - gas_density))**0.25) / (gas_density**0.5)
                    qc = (3.066894 * P_psia * vc * area) / (temp_r * z_factor)
                    forecast_qc.append(qc)

                forecast_dates = [last_historical_date + pd.DateOffset(months=i) for i in range(1, future_months + 1)]

                # Build seamless continuity arrays
                plot_dates = [last_historical_date] + forecast_dates
                plot_qg = [qi_last] + list(forecast_qg)
                plot_qc = [forecast_qc[0]] + list(forecast_qc)
                plot_Pwh = [last_Pwh_psig] + list(forecast_Pwh_psig)
                plot_Pfl = [last_Pfl_psig] + list(forecast_Pfl_psig)

                # Find Limit Months
                loading_month = None
                pressure_limit_month = None

                for i in range(future_months):
                    if loading_month is None and forecast_qg[i] <= forecast_qc[i]:
                        loading_month = forecast_dates[i].strftime("%B %Y")
                    
                    if pressure_limit_month is None and forecast_Pwh_psig[i] <= forecast_Pfl_psig[i]:
                        pressure_limit_month = forecast_dates[i].strftime("%B %Y")

                # --- INSIGHTS & WARNINGS ---
                st.subheader("📋 Well Operating Limits Summary")
                res_col1, res_col2 = st.columns(2)
                
                with res_col1:
                    if loading_month:
                        st.warning(f"⚠️ **Liquid Loading Limit:**\nExpected around **{loading_month}**.")
                    else:
                        st.success(f"✅ **Liquid Loading:**\nAbove critical rate for >36 months.")

                with res_col2:
                    if pressure_limit_month:
                        st.error(f"🛑 **Min Flowline Pressure Limit:**\n$P_{{wh}} \\le P_{{fl}}$ around **{pressure_limit_month}**.")
                    else:
                        st.success(f"✅ **Flowline Pressure:**\n$P_{{wh}}$ remains above $P_{{fl}}$ for >36 months.")

                # --- VISUALIZATION 1: GAS RATE VS CRITICAL RATE ---
                fig_rate = go.Figure()
                fig_rate.add_trace(go.Scatter(x=df['Date'], y=df['Gas_Rate'], mode='markers+lines', name='Historical Gas Rate', line=dict(color='gray', dash='dot')))
                fig_rate.add_trace(go.Scatter(x=plot_dates, y=plot_qg, mode='lines', name='Forecasted Gas Rate (qg)', line=dict(color='#2ecc71', width=3)))
                fig_rate.add_trace(go.Scatter(x=plot_dates, y=plot_qc, mode='lines', name='Critical Rate Threshold (qc)', line=dict(color='#e74c3c', width=2, dash='dash')))

                fig_rate.update_layout(
                    title="1. Production Rate Forecast vs. Critical Rate (Liquid Loading)",
                    xaxis_title="Date",
                    yaxis_title="Gas Rate (MMscfd)",
                    template="plotly_dark",
                    hovermode="x unified"
                )
                st.plotly_chart(fig_rate, use_container_width=True)

                # --- VISUALIZATION 2: WELLHEAD PRESSURE VS FLOWLINE PRESSURE ---
                fig_pres = go.Figure()
                fig_pres.add_trace(go.Scatter(x=df['Date'], y=df['Pwh'], mode='lines', name='Historical Pwh', line=dict(color='#3498db', dash='dot')))
                fig_pres.add_trace(go.Scatter(x=plot_dates, y=plot_Pwh, mode='lines', name='Forecasted Pwh', line=dict(color='#00bc8c', width=3)))
                fig_pres.add_trace(go.Scatter(x=plot_dates, y=plot_Pfl, mode='lines', name='Flowline Pressure Limit (Pfl)', line=dict(color='#e74c3c', width=2, dash='dash')))

                fig_pres.update_layout(
                    title="2. Wellhead Pressure (Pwh) Forecast vs. Flowline Pressure Limit (Pfl)",
                    xaxis_title="Date",
                    yaxis_title="Pressure (psig)",
                    template="plotly_dark",
                    hovermode="x unified"
                )
                st.plotly_chart(fig_pres, use_container_width=True)

        except Exception as e:
            st.error(f"Error executing analysis: {e}")