import streamlit as st
import pandas as pd
import numpy as np
import math
from scipy.optimize import curve_fit
import plotly.graph_objects as go

# Set page configuration
st.set_page_config(page_title="Gas Well Performance & Critical Rate", page_icon="🛢️", layout="wide")

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
    st.subheader("Wellhead Conditions")
    pressure_psig = st.number_input("Current Wellhead Pressure (psig)", min_value=0.0, value=278.0, step=1.0)
    temp_f = st.number_input("Wellhead Temperature (°F)", min_value=0.0, value=137.0, step=1.0)
    tubing_id = st.number_input("Current Tubing ID (inches)", min_value=1.0, value=4.5, step=0.125)

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
st.subheader("📈 Historical Analysis, Pressure Limits & Workover Simulation")

def arps_hyperbolic(t, qi, Di, b):
    return qi / ((1 + b * Di * t) ** (1 / b))

def parse_robust_dates(series):
    return pd.to_datetime(series, errors='coerce')

def clean_numeric(series):
    """Converts numbers to floats and coerces any text or non-numeric strings to NaN."""
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
    
    st.markdown("**1. Map Excel Columns:**")
    col_map1, col_map2, col_map3, col_map4 = st.columns(4)
    
    default_date = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['date', 'time', 'timestamp'])), 0)
    default_gas = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['gas', 'qg', 'rate', 'fn'])), min(1, len(available_cols)-1))
    default_pwh = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pwh', 'pressure', 'pres', 'fq'])), min(2, len(available_cols)-1))
    default_pfl = next((i for i, col in enumerate(available_cols) if any(k in col.lower() for k in ['pfl', 'flowline', 'line'])), min(3, len(available_cols)-1))

    with col_map1:
        date_col = st.selectbox("Date Column", available_cols, index=default_date)
    with col_map2:
        gas_col = st.selectbox("Gas Rate Column", available_cols, index=default_gas)
    with col_map3:
        pwh_col = st.selectbox("Wellhead Pressure (Pwh)", available_cols, index=default_pwh)
    with col_map4:
        pfl_col = st.selectbox("Flowline Pressure (Pfl)", available_cols, index=default_pfl)

    st.markdown("**2. Workover Simulation (Velocity String):**")
    col_wo1, col_wo2 = st.columns(2)
    with col_wo1:
        wo_tubing = st.selectbox(
            "Select Proposed Workover Tubing ID", 
            options=[1.500, 1.995, 2.441, 2.992, 3.958], 
            format_func=lambda x: f"{x} inches", 
            index=1
        )
    with col_wo2:
        wo_date_input = st.date_input(
            "Select Scheduled Workover Date",
            value=pd.to_datetime("today").date()
        )

    if st.button("Run Forecast & Workover Analysis", type="primary"):
        try:
            df = pd.DataFrame()
            df['Date'] = parse_robust_dates(df_raw[date_col])
            df['Gas_Rate'] = clean_numeric(df_raw[gas_col])
            df['Pwh'] = clean_numeric(df_raw[pwh_col])
            df['Pfl'] = clean_numeric(df_raw[pfl_col])
            
            # Neglect rows with non-numeric text or missing data
            df = df.dropna(subset=['Date', 'Gas_Rate', 'Pwh', 'Pfl']).sort_values('Date').reset_index(drop=True)
            
            if len(df) < 3:
                st.error("Not enough valid numeric data rows found. Ensure parameters contain valid numbers.")
            else:
                # --- HISTORICAL CUMULATIVE PRODUCTION (FIRST DATE TO LAST HISTORICAL DATE) ---
                df['Days_Step'] = df['Date'].diff().dt.total_seconds() / (24 * 3600)
                df['Days_Step'] = df['Days_Step'].fillna(1.0) # default first entry step
                hist_cum_mmscf = (df['Gas_Rate'] * df['Days_Step']).sum()

                df_active = df[df['Gas_Rate'] > 0].copy().reset_index(drop=True)
                
                if len(df_active) < 3:
                    st.error("Not enough positive gas production data rows found.")
                else:
                    # Decline Curve Fitting
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

                    # Pressure decline rate
                    p_fit = np.polyfit(fit_df.index, fit_df['Pwh'], 1)
                    monthly_dP = max(-p_fit[0], 0.0)
                    
                    qi_last = float(df_active['Gas_Rate'].iloc[-1])
                    last_Pwh_psig = float(df_active['Pwh'].iloc[-1])
                    last_Pfl_psig = float(df_active['Pfl'].iloc[-1])

                    st.success(f"DCA Parameters Calculated: Annual Decline = {fit_Di*12*100:.1f}% | b = {fit_b:.2f} | Pressure Drop = {monthly_dP:.2f} psi/mo")

                    # Project 60 months forward to evaluate limits
                    future_months = 60
                    last_historical_date = df['Date'].iloc[-1]
                    future_t = np.arange(1, future_months + 1)
                    
                    forecast_qg = arps_hyperbolic(future_t, qi_last, fit_Di, fit_b)
                    forecast_Pwh_psig = np.maximum(last_Pwh_psig - (monthly_dP * future_t), 0.0)
                    forecast_Pfl_psig = np.full(future_months, last_Pfl_psig)
                    forecast_Pwh_psia = forecast_Pwh_psig + 14.7
                    
                    forecast_dates = [last_historical_date + pd.DateOffset(months=i) for i in range(1, future_months + 1)]
                    wo_dt = pd.Timestamp(wo_date_input)

                    forecast_qc_base = []
                    forecast_qc_wo = []
                    
                    for f_date, P_psia in zip(forecast_dates, forecast_Pwh_psia):
                        temp_r = temp_f + 459.67
                        vc = (1.9116 * (60.0 * (water_density - gas_density))**0.25) / (gas_density**0.5)
                        
                        # Base case uses original tubing ID throughout
                        area_base = math.pi * ((tubing_id / 2.0) / 12.0)**2
                        qc_base = (3.066894 * P_psia * vc * area_base) / (temp_r * z_factor)
                        forecast_qc_base.append(qc_base)
                        
                        # Workover case uses original ID before wo_dt, and switch to wo_tubing on/after wo_dt
                        active_tubing = wo_tubing if f_date >= wo_dt else tubing_id
                        area_wo = math.pi * ((active_tubing / 2.0) / 12.0)**2
                        qc_wo = (3.066894 * P_psia * vc * area_wo) / (temp_r * z_factor)
                        forecast_qc_wo.append(qc_wo)

                    # Arrays for seamless plotting
                    plot_dates = [last_historical_date] + forecast_dates
                    plot_qg = [qi_last] + list(forecast_qg)
                    plot_qc_base = [forecast_qc_base[0]] + list(forecast_qc_base)
                    plot_qc_wo = [forecast_qc_wo[0]] + list(forecast_qc_wo)
                    plot_Pwh = [last_Pwh_psig] + list(forecast_Pwh_psig)
                    plot_Pfl = [last_Pfl_psig] + list(forecast_Pfl_psig)

                    # --- LIMIT EVALUATION ---
                    base_limit_idx = future_months
                    wo_limit_idx = future_months
                    base_death_reason = "End of 5-year forecast"
                    wo_death_reason = "End of 5-year forecast"

                    for i in range(future_months):
                        if forecast_qg[i] <= forecast_qc_base[i]:
                            base_limit_idx = i
                            base_death_reason = f"Liquid Loading ({forecast_dates[i].strftime('%b %Y')})"
                            break
                        if forecast_Pwh_psig[i] <= forecast_Pfl_psig[i]:
                            base_limit_idx = i
                            base_death_reason = f"Pwh ≤ Pfl ({forecast_dates[i].strftime('%b %Y')})"
                            break

                    for i in range(future_months):
                        if forecast_qg[i] <= forecast_qc_wo[i]:
                            wo_limit_idx = i
                            wo_death_reason = f"Liquid Loading ({forecast_dates[i].strftime('%b %Y')})"
                            break
                        if forecast_Pwh_psig[i] <= forecast_Pfl_psig[i]:
                            wo_limit_idx = i
                            wo_death_reason = f"Pwh ≤ Pfl ({forecast_dates[i].strftime('%b %Y')})"
                            break

                    # --- TOTAL CUMULATIVE PRODUCTION (HISTORICAL + FORECAST) ---
                    days_per_month = 30.4375
                    
                    base_forecast_cum = np.sum(forecast_qg[:base_limit_idx]) * days_per_month if base_limit_idx > 0 else 0.0
                    wo_forecast_cum = np.sum(forecast_qg[:wo_limit_idx]) * days_per_month if wo_limit_idx > 0 else 0.0

                    base_total_cum = hist_cum_mmscf + base_forecast_cum
                    wo_total_cum = hist_cum_mmscf + wo_forecast_cum
                    incremental_gain = wo_total_cum - base_total_cum

                    # Display Dashboard Metrics
                    st.subheader("📊 Total Lifetime Cumulative Production (Start Date to Failure)")
                    metric_col1, metric_col2, metric_col3 = st.columns(3)
                    
                    with metric_col1:
                        st.info(f"**Base Case ({tubing_id}\" ID)**\n\n"
                                f"• **Historical Cum:** {hist_cum_mmscf:.1f} MMscf\n\n"
                                f"• **Forecast Cum:** {base_forecast_cum:.1f} MMscf\n\n"
                                f"• **Total Lifetime Cum:** {base_total_cum:.1f} MMscf\n\n"
                                f"**Constraint:** {base_death_reason}")
                        
                    with metric_col2:
                        st.success(f"**Workover Case ({wo_tubing}\" ID)**\n\n"
                                   f"• **Historical Cum:** {hist_cum_mmscf:.1f} MMscf\n\n"
                                   f"• **Forecast Cum:** {wo_forecast_cum:.1f} MMscf\n\n"
                                   f"• **Total Lifetime Cum:** {wo_total_cum:.1f} MMscf\n\n"
                                   f"**Constraint:** {wo_death_reason}")
                        
                    with metric_col3:
                        st.warning(f"**Workover Incremental Gain**\n\n"
                                   f"**+{incremental_gain:.1f} MMscf**\n\n"
                                   f"Extends production by {max(0, wo_limit_idx - base_limit_idx)} months")

                    # CHART 1: Production Rate vs Critical Rates
                    fig_rate = go.Figure()
                    fig_rate.add_trace(go.Scatter(x=df['Date'], y=df['Gas_Rate'], mode='markers+lines', name='Historical Gas Rate', line=dict(color='gray', dash='dot')))
                    fig_rate.add_trace(go.Scatter(x=plot_dates, y=plot_qg, mode='lines', name='Forecasted Gas Rate (qg)', line=dict(color='#2ecc71', width=3)))
                    
                    if base_limit_idx < future_months:
                        fig_rate.add_trace(go.Scatter(x=[forecast_dates[base_limit_idx]], y=[forecast_qg[base_limit_idx]], mode='markers', marker=dict(color='red', size=12, symbol='x'), name='Base Case Limit'))
                    
                    if wo_limit_idx < future_months:
                        fig_rate.add_trace(go.Scatter(x=[forecast_dates[wo_limit_idx]], y=[forecast_qg[wo_limit_idx]], mode='markers', marker=dict(color='gold', size=12, symbol='star'), name='Workover Limit'))

                    fig_rate.add_trace(go.Scatter(x=plot_dates, y=plot_qc_base, mode='lines', name=f'Base Critical Rate ({tubing_id}")', line=dict(color='#e74c3c', width=2, dash='dash')))
                    fig_rate.add_trace(go.Scatter(x=plot_dates, y=plot_qc_wo, mode='lines', name=f'Workover Critical Rate ({wo_tubing}")', line=dict(color='#f1c40f', width=2, dash='dash')))

                    # Add vertical marker line for Workover Date
                    fig_rate.add_vline(x=wo_dt.strftime('%Y-%m-%d'), line_dash="dash", line_color="gold", annotation_text="Workover Date", annotation_position="top left")

                    fig_rate.update_layout(
                        title="1. Production Rate Forecast vs. Critical Gas Rates",
                        xaxis_title="Date",
                        yaxis_title="Gas Rate (MMscfd)",
                        template="plotly_dark",
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig_rate, use_container_width=True)

                    # CHART 2: Wellhead Pressure vs Flowline Pressure
                    fig_pres = go.Figure()
                    fig_pres.add_trace(go.Scatter(x=df['Date'], y=df['Pwh'], mode='lines', name='Historical Pwh', line=dict(color='#3498db', dash='dot')))
                    fig_pres.add_trace(go.Scatter(x=df['Date'], y=df['Pfl'], mode='lines', name='Historical Pfl', line=dict(color='#e67e22', dash='dot')))
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