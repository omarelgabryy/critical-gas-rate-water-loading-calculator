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
    """Parses native datetimes, string dates, and Excel serial numbers safely."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors='coerce')
    
    num_series = pd.to_numeric(series, errors='coerce')
    parsed = pd.Series(index=series.index, dtype='datetime64[ns]')
    
    excel_mask = num_series.notna() & (num_series > 1000) & (num_series < 100000)
    if excel_mask.any():
        parsed.update(pd.to_datetime(num_series[excel_mask], unit='D', origin='1899-12-30', errors='coerce'))
        
    str_mask = parsed.isna() & series.notna()
    if str_mask.any():
        parsed.update(pd.to_datetime(series[str_mask], format='mixed', errors='coerce'))
        
    return parsed

uploaded_file = st.file_uploader("Upload Historical Well Data (Excel)", type=["xlsx", "xls"])

if uploaded_file is not None:
    header_row = st.number_input("Header Row (Set to row number where column names are located)", min_value=1, value=1, step=1) - 1
    
    excel_file = pd.ExcelFile(uploaded_file)
    sheet_name = st.selectbox("Select Sheet", excel_file.sheet_names)
    
    df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=header_row)
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    
    available_cols = list(df_raw.columns)
    
    st.markdown("**Map Excel Columns:**")
    col_map1, col_map2, col_map3 = st.columns(3)
    
    default_date = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['date', 'time', 'timestamp'])), 0)
    default_gas = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['gas', 'qg', 'rate'])), min(1, len(available_cols)-1))
    default_pwh = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pwh', 'pressure', 'pres'])), min(2, len(available_cols)-1))

    with col_map1:
        date_col = st.selectbox("Date Column", available_cols, index=default_date)
    with col_map2:
        gas_col = st.selectbox("Gas Rate Column", available_cols, index=default_gas)
    with col_map3:
        pwh_col = st.selectbox("Wellhead Pressure Column", available_cols, index=default_pwh)

    future_months = st.slider("Forecast Horizon (Months)", min_value=12, max_value=240, value=60, step=12)

    if st.button("Run Decline & Forecast Analysis"):
        try:
            # Full dataset preserved for plotting history (including zero-rate shut-in periods)
            df_full = pd.DataFrame()
            df_full['Date'] = parse_robust_dates(df_raw[date_col])
            df_full['Gas_Rate'] = pd.to_numeric(df_raw[gas_col], errors='coerce').fillna(0.0)
            df_full['Pwh'] = pd.to_numeric(df_raw[pwh_col], errors='coerce').replace(0, np.nan).ffill().bfill()
            
            df_full = df_full.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)

            # Filtered dataset strictly for DCA Curve Fitting (Active production > 0)
            df_active = df_full[df_full['Gas_Rate'] > 0].copy().reset_index(drop=True)
            
            if len(df_active) < 3:
                st.error("Not enough active production data (> 0 rate) found to fit a decline curve.")
            else:
                # Monthly resampling on active production
                df_monthly = df_active.set_index('Date').resample('MS').agg({'Gas_Rate': 'mean', 'Pwh': 'mean'}).dropna().reset_index()
                fit_df = df_monthly if len(df_monthly) >= 3 else df_active
                
                # Fit Arps from Peak Production rate onwards
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

                p_fit = np.polyfit(fit_df.index, fit_df['Pwh'], 1)
                monthly_dP = max(-p_fit[0], 0.0)
                
                # Starting rate (qi) = Last known active production rate before shut-in
                qi_last = float(df_active['Gas_Rate'].iloc[-1])
                last_Pwh_psig = float(df_active['Pwh'].iloc[-1])

                st.success(f"Calculated Parameters: Decline = {fit_Di*12*100:.1f}%/yr | b = {fit_b:.2f} | Pressure Drop = {monthly_dP:.2f} psi/mo")

                # Forecast from the LATEST date in the full Excel sheet forward
                latest_date = df_full['Date'].iloc[-1]
                future_t = np.arange(1, future_months + 1)
                
                forecast_qg = arps_hyperbolic(future_t, qi_last, fit_Di, fit_b)
                forecast_Pwh_psig = np.maximum(last_Pwh_psig - (monthly_dP * future_t), 0.0)
                forecast_Pwh_psia = forecast_Pwh_psig + 14.7
                
                forecast_qc = []
                for P_psia in forecast_Pwh_psia:
                    temp_r = temp_f + 459.67
                    area = math.pi * ((tubing_id / 2.0) / 12.0)**2
                    vc = (1.9116 * (60.0 * (water_density - gas_density))**0.25) / (gas_density**0.5)
                    qc = (3.066894 * P_psia * vc * area) / (temp_r * z_factor)
                    forecast_qc.append(qc)

                forecast_dates = [latest_date + pd.DateOffset(months=i) for i in range(1, future_months + 1)]

                loading_month = None
                for i in range(future_months):
                    if forecast_qg[i] <= forecast_qc[i]:
                        loading_month = forecast_dates[i].strftime("%B %Y")
                        break

                if loading_month:
                    st.warning(f"⚠️ **Forecast Warning:** Liquid loading is expected to begin around **{loading_month}**.")
                else:
                    st.info(f"✅ Well is projected to remain above the critical rate for the next {future_months} months.")

                # Plotly Visualization showing FULL history (including shut-in zeros up to 2026)
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_full['Date'], y=df_full['Gas_Rate'], mode='markers+lines', name='Historical Gas Rate', line=dict(color='gray', dash='dot')))
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