import streamlit as st
import pandas as pd
import numpy as np
import math
from scipy.optimize import curve_fit
import plotly.graph_objects as go
from datetime import datetime, date

# Set page configuration
st.set_page_config(page_title="Gas Well Performance & Forecast", page_icon="🛢️", layout="wide")

st.title("Gas Well Performance & Workover Scheduler 🛢️")

# --- 1. SINGLE WELL CALCULATOR & INPUTS ---
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("Fluid Properties")
    gas_density = st.number_input("Gas Density (lb/ft³)", min_value=0.1, value=4.6, step=0.1)
    water_density = st.number_input("Water Density (lb/ft³)", min_value=10.0, value=67.0, step=0.1)
    z_factor = st.number_input("Z-Factor", min_value=0.1000, value=0.8843, step=0.0001, format="%0.4f")

with col2:
    st.subheader("Wellhead Conditions")
    pressure_psig = st.number_input("Current Wellhead Pressure (psig)", min_value=0.0, value=278.0, step=1.0)
    temp_f = st.number_input("Wellhead Temperature (°F)", min_value=0.0, value=137.0, step=1.0)
    tubing_id = st.number_input("Current Tubing ID (inches)", min_value=1.0, value=3.5, step=0.125)

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

# --- 2. HISTORICAL EXCEL FORECASTING & WORKOVER SCHEDULER ---
st.divider()
st.subheader("📈 Historical Analysis, Workover Scheduler & Forecast Table")

def arps_hyperbolic(t, qi, Di, b):
    return qi / ((1 + b * Di * t) ** (1 / b))

def parse_robust_dates(series):
    return pd.to_datetime(series, errors='coerce')

def clean_numeric(series):
    cleaned = series.astype(str).str.replace(',', '', regex=False).str.strip()
    return pd.to_numeric(cleaned, errors='coerce')

uploaded_file = st.file_uploader("Upload Historical Well Data (Excel)", type=["xlsx", "xls"])

if uploaded_file is not None:
    header_row = st.number_input("Header Row (Row index where column headers are located)", min_value=1, value=1, step=1) - 1
    
    excel_file = pd.ExcelFile(uploaded_file)
    sheet_name = st.selectbox("Select Sheet", excel_file.sheet_names)
    
    df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=header_row)
    df_raw.columns = df_raw.columns.astype(str).str.strip()
    available_cols = list(df_raw.columns)
    
    st.markdown("**1. Map Excel Columns:**")
    col_map1, col_map2, col_map3, col_map4 = st.columns(4)
    
    default_date = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['date', 'time', 'timestamp'])), 0)
    default_gas = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['gas', 'qg', 'rate', 'fn'])), min(1, len(available_cols)-1))
    default_pwh = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pwh', 'pressure', 'whfp'])), min(2, len(available_cols)-1))
    default_pfl = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pfl', 'flowline', 'flp'])), min(3, len(available_cols)-1))

    with col_map1:
        date_col = st.selectbox("Date Column", available_cols, index=default_date)
    with col_map2:
        gas_col = st.selectbox("Gas Rate Column", available_cols, index=default_gas)
    with col_map3:
        pwh_col = st.selectbox("Wellhead Pressure (Pwh)", available_cols, index=default_pwh)
    with col_map4:
        pfl_col = st.selectbox("Flowline Pressure (Pfl)", available_cols, index=default_pfl)

    # Dynamic date detection for better default workover date
    temp_dates = parse_robust_dates(df_raw[date_col]).dropna()
    last_hist_dt = temp_dates.max().date() if not temp_dates.empty else date(2018, 7, 1)

    st.markdown("**2. Workover Simulation & Planning:**")
    col_wo1, col_wo2 = st.columns(2)
    with col_wo1:
        wo_tubing = st.selectbox(
            "Proposed Workover Tubing ID", 
            options=[1.500, 1.995, 2.441, 2.992, 3.958], 
            format_func=lambda x: f"{x} inches", 
            index=1
        )
    with col_wo2:
        workover_date_input = st.date_input("Planned Workover Execution Date", value=last_hist_dt)

    if st.button("Run Schedule & Generate Forecast Table", type="primary"):
        try:
            df = pd.DataFrame()
            df['Date'] = parse_robust_dates(df_raw[date_col])
            df['Gas_Rate'] = clean_numeric(df_raw[gas_col])
            df['Pwh'] = clean_numeric(df_raw[pwh_col])
            df['Pfl'] = clean_numeric(df_raw[pfl_col])
            
            df = df.dropna(subset=['Date', 'Gas_Rate', 'Pwh', 'Pfl']).sort_values('Date').reset_index(drop=True)
            
            if len(df) < 3:
                st.error("Not enough valid numeric data rows found.")
            else:
                df_active = df[df['Gas_Rate'] > 0].copy().reset_index(drop=True)
                
                # Calculate Historical Critical Rate for Old Analysis
                temp_r = temp_f + 459.67
                vc = (1.9116 * (60.0 * (water_density - gas_density))**0.25) / (gas_density**0.5)
                area_hist = math.pi * ((tubing_id / 2.0) / 12.0)**2
                df_active['Hist_qc'] = (3.066894 * (df_active['Pwh'] + 14.7) * vc * area_hist) / (temp_r * z_factor)

                # Calculate historical cumulative
                df_active['Days_Step'] = df_active['Date'].diff().dt.total_seconds() / (24 * 3600)
                df_active['Days_Step'] = df_active['Days_Step'].fillna(30.4375)
                hist_cum_mmscf = (df_active['Gas_Rate'] * df_active['Days_Step']).sum()

                # Decline curve analysis
                df_monthly = df_active.set_index('Date').resample('MS').agg({'Gas_Rate': 'mean', 'Pwh': 'mean', 'Pfl': 'mean'}).dropna().reset_index()
                fit_df = df_monthly if len(df_monthly) >= 3 else df_active
                
                peak_idx = fit_df['Gas_Rate'].idxmax()
                df_decline = fit_df.iloc[peak_idx:].copy().reset_index(drop=True)
                if len(df_decline) < 3:
                    df_decline = fit_df.copy().reset_index(drop=True)

                df_decline['Months'] = (df_decline['Date'] - df_decline['Date'].iloc[0]).dt.days / 30.4375
                qi_peak = float(df_decline['Gas_Rate'].iloc[0])
                
                try:
                    popt, _ = curve_fit(arps_hyperbolic, df_decline['Months'], df_decline['Gas_Rate'], p0=[qi_peak, 0.02, 0.5], bounds=([0, 0.001, 0.01], [np.inf, 1.0, 1.0]))
                    _, fit_Di, fit_b = popt
                except Exception:
                    fit_Di, fit_b = 0.02, 0.5

                p_fit = np.polyfit(fit_df.index, fit_df['Pwh'], 1)
                monthly_dP = max(-p_fit[0], 0.0)
                
                qi_last = float(df_active['Gas_Rate'].iloc[-1])
                last_Pwh_psig = float(df_active['Pwh'].iloc[-1])
                last_Pfl_psig = float(df_active['Pfl'].iloc[-1])
                last_historical_date = df_active['Date'].iloc[-1]
                
                wo_dt = pd.Timestamp(workover_date_input)

                st.success(f"DCA Parameters Calculated: Annual Decline = {fit_Di*12*100:.1f}% | b = {fit_b:.2f} | Pressure Drop = {monthly_dP:.2f} psi/mo")

                # Generate forecast steps
                future_months = 60
                days_per_month = 30.4375

                forecast_table_data = []
                running_cum_forecast = 0.0
                well_active = True
                
                for m in range(1, future_months + 1):
                    f_date = last_historical_date + pd.DateOffset(months=m)
                    qg = arps_hyperbolic(m, qi_last, fit_Di, fit_b)
                    pwh = max(last_Pwh_psig - (monthly_dP * m), 0.0)
                    pfl = last_Pfl_psig
                    pwh_psia = pwh + 14.7

                    active_tubing = wo_tubing if f_date >= wo_dt else tubing_id
                    area = math.pi * ((active_tubing / 2.0) / 12.0)**2
                    qc = (3.066894 * pwh_psia * vc * area) / (temp_r * z_factor)

                    status = "Normal Operation"
                    if qg <= qc:
                        status = "Liquid Loading Failure"
                        well_active = False
                    elif pwh <= pfl:
                        status = "Pwh <= Pfl Pressure Limit"
                        well_active = False

                    if well_active:
                        monthly_vol = qg * days_per_month
                        running_cum_forecast += monthly_vol
                        total_cum = hist_cum_mmscf + running_cum_forecast
                    else:
                        monthly_vol = 0.0
                        total_cum = hist_cum_mmscf + running_cum_forecast

                    forecast_table_data.append({
                        "Date": f_date.strftime("%Y-%m-%d"),
                        "Gas Rate qg (MMscfd)": round(qg, 4),
                        "Pwh (psig)": round(pwh, 2),
                        "Pfl (psig)": round(pfl, 2),
                        "Active Tubing ID (in)": active_tubing,
                        "Critical Rate qc (MMscfd)": round(qc, 4),
                        "Monthly Volume (MMscf)": round(monthly_vol, 2),
                        "Forecast Cum (MMscf)": round(running_cum_forecast, 2),
                        "Total Lifetime Cum (MMscf)": round(total_cum, 2),
                        "Operating Status": status
                    })

                    if not well_active:
                        break

                df_forecast_table = pd.DataFrame(forecast_table_data)

                # --- DASHBOARD METRICS ---
                st.subheader("📊 Workover & Forecast Summary Metrics")
                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("Historical Cumulative Gas", f"{hist_cum_mmscf:.1f} MMscf")
                m_col2.metric("Projected Forecast Gas", f"{running_cum_forecast:.1f} MMscf")
                m_col3.metric("Total Recoverable Volume", f"{hist_cum_mmscf + running_cum_forecast:.1f} MMscf")

                # --- CHART 1: GAS RATE & CRITICAL RATE ---
                st.subheader("📉 Gas Production Rate & Critical Rate Analysis")
                fig_rate = go.Figure()
                fig_rate.add_trace(go.Scatter(x=df_active['Date'], y=df_active['Gas_Rate'], mode='markers+lines', name='Historical Gas Rate (qg)', line=dict(color='#3498db', width=1.5)))
                fig_rate.add_trace(go.Scatter(x=df_active['Date'], y=df_active['Hist_qc'], mode='lines', name='Historical Critical Rate (qc)', line=dict(color='#e67e22', dash='dot')))
                fig_rate.add_trace(go.Scatter(x=df_forecast_table['Date'], y=df_forecast_table['Gas Rate qg (MMscfd)'], mode='lines', name='Forecast Gas Rate (qg)', line=dict(color='#2ecc71', width=3)))
                fig_rate.add_trace(go.Scatter(x=df_forecast_table['Date'], y=df_forecast_table['Critical Rate qc (MMscfd)'], mode='lines', name='Forecast Critical Rate (qc)', line=dict(color='#e74c3c', width=2, dash='dash')))

                fig_rate.add_vline(x=wo_dt.strftime('%Y-%m-%d'), line_width=2, line_dash="dash", line_color="gold")
                fig_rate.add_annotation(x=wo_dt.strftime('%Y-%m-%d'), y=float(df_active['Gas_Rate'].max()), text=f"Workover ({wo_tubing}\")", showarrow=True, arrowhead=1, font=dict(color="gold"), arrowcolor="gold")

                fig_rate.update_layout(xaxis_title="Date", yaxis_title="Gas Rate (MMscfd)", template="plotly_dark", hovermode="x unified")
                st.plotly_chart(fig_rate, use_container_width=True)

                # --- CHART 2: WELLHEAD vs FLOWLINE PRESSURE ---
                st.subheader("📉 Wellhead Pressure (Pwh) vs Flowline Pressure (Pfl)")
                fig_press = go.Figure()
                fig_press.add_trace(go.Scatter(x=df_active['Date'], y=df_active['Pwh'], mode='lines', name='Historical Pwh', line=dict(color='#9b59b6')))
                fig_press.add_trace(go.Scatter(x=df_active['Date'], y=df_active['Pfl'], mode='lines', name='Historical Pfl', line=dict(color='#1abc9c')))
                fig_press.add_trace(go.Scatter(x=df_forecast_table['Date'], y=df_forecast_table['Pwh (psig)'], mode='lines', name='Forecast Pwh', line=dict(color='#9b59b6', dash='dash')))
                fig_press.add_trace(go.Scatter(x=df_forecast_table['Date'], y=df_forecast_table['Pfl (psig)'], mode='lines', name='Forecast Pfl', line=dict(color='#1abc9c', dash='dash')))

                fig_press.add_vline(x=wo_dt.strftime('%Y-%m-%d'), line_width=2, line_dash="dash", line_color="gold")

                fig_press.update_layout(xaxis_title="Date", yaxis_title="Pressure (psig)", template="plotly_dark", hovermode="x unified")
                st.plotly_chart(fig_press, use_container_width=True)

                # --- TABULAR FORECAST DISPLAY & DOWNLOAD ---
                st.subheader("📋 Forecast Data Table (Post-Historical)")
                st.dataframe(df_forecast_table, use_container_width=True)

                csv_data = df_forecast_table.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Full Forecast Table (CSV)",
                    data=csv_data,
                    file_name=f"gas_well_forecast_workover_{workover_date_input}.csv",
                    mime="text/csv",
                    type="secondary"
                )

        except Exception as e:
            st.error(f"Error executing analysis: {e}")