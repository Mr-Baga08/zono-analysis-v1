# app.py - Main Flask application
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import yfinance as yf
import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import traceback
import os
import uuid
import tempfile
from api.index import app

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_here')

# Use tempfile directory for serverless compatibility
UPLOAD_FOLDER = tempfile.gettempdir()

# Helper functions for technical analysis
def calculate_true_range(data):
    """Calculate True Range for ATR calculation"""
    tr1 = abs(data['High'] - data['Low'])
    tr2 = abs(data['High'] - data['Close'].shift())
    tr3 = abs(data['Low'] - data['Close'].shift())
    tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
    return tr

def calculate_rsi(data, period=14):
    """Calculate the Relative Strength Index"""
    delta = data['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    
    # Calculate RS
    rs = gain / loss
    
    # Calculate RSI
    rsi = 100 - (100 / (1 + rs))
    return rsi

def fetch_stock_data(ticker, interval='5m', period='60d'):
    """Fetch stock data and calculate technical indicators"""
    # Fetch data
    stock = yf.Ticker(ticker)
    data = stock.history(interval=interval, period=period)
    
    # Ensure we have data
    if data.empty:
        raise ValueError(f"No data available for {ticker} at {interval} interval")
    
    # Apply common processing
    return process_data(data)

def process_data(data):
    """Process dataframe and calculate technical indicators"""
    # Ensure required columns exist
    required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"Required column '{col}' not found in data")
    
    # Calculate additional metrics for better zone identification
    data['HL_Range'] = data['High'] - data['Low']
    data['Body_Range'] = abs(data['Open'] - data['Close'])
    data['Upper_Wick'] = data.apply(
        lambda x: x['High'] - max(x['Open'], x['Close']), axis=1
    )
    data['Lower_Wick'] = data.apply(
        lambda x: min(x['Open'], x['Close']) - x['Low'], axis=1
    )
    
    # Calculate volume moving average for reference
    data['Volume_MA'] = data['Volume'].rolling(window=20).mean()
    
    # Calculate ATR-based metrics
    data['TR'] = calculate_true_range(data)
    data['ATR'] = data['TR'].rolling(window=14).mean()
    
    # Calculate technical indicators
    data['SMA20'] = data['Close'].rolling(window=20).mean()
    data['SMA50'] = data['Close'].rolling(window=50).mean()
    data['SMA200'] = data['Close'].rolling(window=200).mean()
    data['RSI'] = calculate_rsi(data)
    
    # Calculate price changes for zone detection
    data['PriceChange'] = data['Close'].pct_change()
    data['RangePercent'] = data['HL_Range'] / data['Close'].shift(1)
    data['VolumePctChange'] = data['Volume'].pct_change()
    
    return data

def process_csv_data(file_path):
    """Process uploaded CSV file into the required format"""
    try:
        # Read the CSV file
        df = pd.read_csv(file_path)
        
        # Check if we have a datetime column
        date_col = None
        for col in df.columns:
            if col.lower() in ['date', 'datetime', 'time', 'timestamp']:
                date_col = col
                break
        
        if date_col:
            # Convert to datetime and set as index
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.set_index(date_col)
        else:
            # If no date column, create a simple index
            df.index = pd.date_range(start='2023-01-01', periods=len(df), freq='D')
        
        # Map common column names to our required format
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'open' in col_lower:
                column_mapping[col] = 'Open'
            elif 'high' in col_lower:
                column_mapping[col] = 'High'
            elif 'low' in col_lower:
                column_mapping[col] = 'Low'
            elif 'close' in col_lower or 'last' in col_lower or 'price' in col_lower:
                column_mapping[col] = 'Close'
            elif 'volume' in col_lower or 'vol' in col_lower:
                column_mapping[col] = 'Volume'
        
        # Check if we have all required columns
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_cols = [col for col in required_cols if col not in column_mapping.values()]
        
        if missing_cols:
            # For missing columns, try to derive them from existing data
            for col in missing_cols:
                if col == 'Open' and 'Close' in column_mapping.values():
                    close_col = [c for c, v in column_mapping.items() if v == 'Close'][0]
                    df['Open'] = df[close_col].shift(1)
                    column_mapping['Open'] = 'Open'
                elif col == 'High' and 'Close' in column_mapping.values():
                    close_col = [c for c, v in column_mapping.items() if v == 'Close'][0]
                    df['High'] = df[close_col] * 1.005  # Approximate
                    column_mapping['High'] = 'High'
                elif col == 'Low' and 'Close' in column_mapping.values():
                    close_col = [c for c, v in column_mapping.items() if v == 'Close'][0]
                    df['Low'] = df[close_col] * 0.995  # Approximate
                    column_mapping['Low'] = 'Low'
                elif col == 'Volume':
                    df['Volume'] = 1000000  # Default placeholder
                    column_mapping['Volume'] = 'Volume'
        
        # Rename columns according to mapping
        df = df.rename(columns=column_mapping)
        
        # Keep only the columns we need plus any extras
        keep_cols = []
        for col in required_cols:
            if col in df.columns:
                keep_cols.append(col)
        
        # Check again if all required columns are available
        if len(keep_cols) < 5:
            raise ValueError(f"Could not identify all required columns. Found: {keep_cols}")
        
        df = df[keep_cols]
        
        # Process the data
        processed_data = process_data(df)
        return processed_data
    
    except Exception as e:
        raise ValueError(f"Error processing CSV file: {str(e)}")

def identify_zones(data, threshold=0.02, lookback=10, breakout_window=5, require_volume=True):
    """
    Advanced zone identification that combines price action, consolidation, and breakouts.
    
    Parameters:
    - data: DataFrame with OHLCV and calculated metrics
    - threshold: Base threshold for price changes to be considered significant
    - lookback: Number of candles to look back for consolidation (K)
    - breakout_window: Number of candles to look ahead for breakout confirmation (M)
    
    Returns:
    - List of zones with metadata
    """
    zones = []
    
    # Ensure minimum data requirements
    min_samples = lookback + breakout_window + 1
    if len(data) < min_samples:
        return zones
    
    # Get ATR multiplier for consolidation detection
    consolidation_threshold = threshold * 1.5
    
    # Identify consolidation and breakout zones
    for i in range(lookback, len(data) - breakout_window):
        # Get the window of candles for consolidation check
        window = data.iloc[i-lookback:i+1]
        
        # Calculate consolidation stats
        max_high = window['High'].max()
        min_low = window['Low'].min()
        price_range = max_high - min_low
        
        # Skip invalid ranges
        if pd.isna(price_range) or price_range == 0:
            continue
        
        # Check if this is a consolidation area (range is small relative to ATR)
        current_atr = data['ATR'].iloc[i]
        is_consolidation = price_range < (consolidation_threshold * current_atr)
        
        # Volume requirement (if enabled)
        volume_condition = True
        if require_volume:
            # Get average volume in this window
            window_vol_avg = window['Volume'].mean()
            # Require the highest volume in window to be significantly above average
            highest_vol = window['Volume'].max()
            volume_condition = highest_vol > (window_vol_avg * 1.2)
        
        # If we have consolidation, check for breakout
        if is_consolidation and volume_condition:
            # Check next few candles for breakout
            breakout_window_data = data.iloc[i+1:i+breakout_window+1]
            
            # Define breakout thresholds (could add small buffer)
            breakout_high = max_high
            breakout_low = min_low
            
            # Check for upward breakout
            upward_breakout = False
            for j, row in breakout_window_data.iterrows():
                if row['Close'] > breakout_high:
                    upward_breakout = True
                    break
            
            # Check for downward breakout
            downward_breakout = False
            for j, row in breakout_window_data.iterrows():
                if row['Close'] < breakout_low:
                    downward_breakout = True
                    break
            
            # Determine zone type based on first breakout
            zone_type = None
            if upward_breakout and not downward_breakout:
                zone_type = 'Demand'  # Buy zone
            elif downward_breakout and not upward_breakout:
                zone_type = 'Supply'  # Sell zone
            
            # Only proceed if we have a clear breakout direction
            if zone_type:
                # Calculate strength based on multiple factors
                
                # 1. Base strength from consolidation quality (tighter = stronger)
                consolidation_quality = 1.0 - (price_range / (3 * current_atr))
                consolidation_quality = max(0, min(1, consolidation_quality))
                
                # 2. Volume factor - more volume = stronger zone
                vol_factor = 0.5
                if require_volume:
                    max_vol = window['Volume'].max()
                    avg_vol = data['Volume_MA'].iloc[i]
                    vol_ratio = max_vol / avg_vol if avg_vol > 0 else 1.0
                    vol_factor = min(1.0, (vol_ratio - 1.0) * 0.5)
                
                # 3. Breakout strength
                breakout_str = 0.5
                if zone_type == 'Demand':
                    # For demand zone, measure how far price moved up
                    highest_close = breakout_window_data['Close'].max()
                    breakout_magnitude = (highest_close - breakout_high) / current_atr
                    breakout_str = min(1.0, breakout_magnitude * 0.5)
                else:
                    # For supply zone, measure how far price moved down
                    lowest_close = breakout_window_data['Close'].min()
                    breakout_magnitude = (breakout_low - lowest_close) / current_atr
                    breakout_str = min(1.0, breakout_magnitude * 0.5)
                
                # Combined strength (0-100%)
                strength = (consolidation_quality * 40) + (vol_factor * 30) + (breakout_str * 30)
                
                # Create zone info
                zone_info = {
                    'level': min_low + (price_range / 2),  # Center of zone
                    'upper': max_high,
                    'lower': min_low,
                    'strength': strength,
                    'date': data.index[i].strftime('%Y-%m-%d %H:%M:%S'),
                    'volume': float(window['Volume'].max()),
                    'avg_volume': float(data['Volume_MA'].iloc[i]) if not pd.isna(data['Volume_MA'].iloc[i]) else 0,
                    'consolidation': True,  # Flag as consolidation-based zone
                    'price_range': float(price_range),
                    'atr': float(current_atr)
                }
                
                zones.append((data.index[i].strftime('%Y-%m-%d %H:%M:%S'), zone_type, zone_info))
    
    # Also run the traditional price action based zone detection
    traditional_zones = identify_price_action_zones(data, threshold, lookback//2, require_volume)
    
    # Combine both types of zones
    all_zones = zones + traditional_zones
    
    # Merge overlapping zones
    if all_zones:
        # Split by type
        supply_zones = [z for z in all_zones if z[1] == 'Supply']
        demand_zones = [z for z in all_zones if z[1] == 'Demand']
        
        # Merge each type
        merged_supply = merge_zones(supply_zones)
        merged_demand = merge_zones(demand_zones)
        
        # Combine back
        all_zones = merged_supply + merged_demand
    
    return all_zones

def identify_price_action_zones(data, threshold=0.02, lookback=5, require_volume=True):
    """Traditional price action based zone identification"""
    zones = []
    
    # Setup lookback window requirements
    min_samples = 3 + lookback  # Need enough bars for analysis
    
    if len(data) < min_samples:
        return zones
        
    # Analyze each bar for zone potential
    for i in range(lookback, len(data) - lookback):
        current_bar = data.iloc[i]
        
        # Skip bars with abnormal ranges
        if pd.isna(current_bar['RangePercent']) or current_bar['RangePercent'] > 0.1:
            continue
            
        # Check if there's enough volume (optional based on settings)
        has_volume = (not require_volume) or (
            current_bar['Volume'] > current_bar['Volume_MA'] * 1.5
        )
        
        if not has_volume:
            continue
            
        # Define before and after windows
        before_window = data.iloc[i-lookback:i]
        after_window = data.iloc[i+1:i+lookback+1]
        
        # Check for supply zone (local top with rejection)
        is_supply = (
            # Higher high than previous bars
            current_bar['High'] > before_window['High'].max() and
            # Significant price drop after
            after_window['Close'].iloc[0] < current_bar['Close'] and
            # Overall trend is downward after
            after_window['Close'].mean() < current_bar['Close'] and
            # Price change is significant
            abs(current_bar['PriceChange']) > threshold
        )
        
        # Check for demand zone (local bottom with strong bounce)
        is_demand = (
            # Lower low than previous bars
            current_bar['Low'] < before_window['Low'].min() and
            # Significant price rise after
            after_window['Close'].iloc[0] > current_bar['Close'] and
            # Overall trend is upward after
            after_window['Close'].mean() > current_bar['Close'] and
            # Price change is significant
            abs(current_bar['PriceChange']) > threshold
        )
        
        # Calculate zone strength (0-100%) based on multiple factors
        strength = 0
        
        if is_supply or is_demand:
            # Base strength on price change magnitude
            strength_base = min(100, (abs(current_bar['PriceChange']) / threshold) * 50)
            
            # Add volume component
            vol_ratio = current_bar['Volume'] / current_bar['Volume_MA']
            vol_component = min(40, (vol_ratio - 1) * 20)
            
            # Add reaction component (how market responded)
            if is_supply:
                reaction = abs(current_bar['Close'] - after_window['Low'].min()) / current_bar['ATR']
            else:
                reaction = abs(current_bar['Close'] - after_window['High'].max()) / current_bar['ATR']
                
            reaction_component = min(10, reaction * 2)
            
            # Calculate final strength
            strength = min(100, strength_base + vol_component + reaction_component)
            
            # Define price level - for supply zones use the top 1/3, for demand use bottom 1/3
            if is_supply:
                zone_price = current_bar['High'] - (current_bar['HL_Range'] * 0.33)
                zone_info = {
                    'level': float(zone_price),
                    'upper': float(current_bar['High']),
                    'lower': float(current_bar['High'] - (current_bar['HL_Range'] * 0.67)),
                    'strength': float(strength),
                    'date': data.index[i].strftime('%Y-%m-%d %H:%M:%S'),
                    'volume': float(current_bar['Volume']), 
                    'avg_volume': float(current_bar['Volume_MA']) if not pd.isna(current_bar['Volume_MA']) else 0,
                    'consolidation': False  # Flag as traditional zone
                }
                zones.append((data.index[i].strftime('%Y-%m-%d %H:%M:%S'), 'Supply', zone_info))
                    
            elif is_demand:
                zone_price = current_bar['Low'] + (current_bar['HL_Range'] * 0.33)
                zone_info = {
                    'level': float(zone_price),
                    'upper': float(current_bar['Low'] + (current_bar['HL_Range'] * 0.67)),
                    'lower': float(current_bar['Low']),
                    'strength': float(strength),
                    'date': data.index[i].strftime('%Y-%m-%d %H:%M:%S'),
                    'volume': float(current_bar['Volume']),
                    'avg_volume': float(current_bar['Volume_MA']) if not pd.isna(current_bar['Volume_MA']) else 0,
                    'consolidation': False  # Flag as traditional zone
                }
                zones.append((data.index[i].strftime('%Y-%m-%d %H:%M:%S'), 'Demand', zone_info))
        
    return zones

def merge_zones(zones):
    """
    Merge overlapping zones of the same type.
    
    Parameters:
    - zones: List of (date, type, info) tuples
    
    Returns:
    - List of merged zones
    """
    if not zones:
        return []
        
    # Sort by date (first element of tuple)
    sorted_zones = sorted(zones, key=lambda z: z[0])
    
    merged = []
    current = sorted_zones[0]
    
    for next_zone in sorted_zones[1:]:
        current_date, current_type, current_info = current
        next_date, next_type, next_info = next_zone
        
        # Check if zones overlap
        current_upper = current_info['upper']
        current_lower = current_info['lower']
        next_upper = next_info['upper']
        next_lower = next_info['lower']
        
        # Zones overlap if upper of one is above lower of the other
        if (current_upper >= next_lower and current_lower <= next_upper):
            # Merge them by using the wider range and higher strength
            merged_lower = min(current_lower, next_lower)
            merged_upper = max(current_upper, next_upper)
            
            # Take the stronger of the two
            if current_info['strength'] >= next_info['strength']:
                stronger_info = current_info
            else:
                stronger_info = next_info
            
            # Create merged zone info
            merged_info = stronger_info.copy()
            merged_info['upper'] = merged_upper
            merged_info['lower'] = merged_lower
            merged_info['level'] = merged_lower + (merged_upper - merged_lower) / 2
            
            # Update current to the merged zone
            current = (current_date, current_type, merged_info)
        else:
            # No overlap, add current to merged list and move to next
            merged.append(current)
            current = next_zone
    
    # Add the last zone
    merged.append(current)
    
    return merged

def create_plotly_chart(title, interval, data, zones, show_settings):
    """Create an interactive Plotly chart with zones and indicators"""
    
    # Get display settings
    show_sma20 = show_settings.get('show_sma20', True)
    show_sma50 = show_settings.get('show_sma50', True)
    show_sma200 = show_settings.get('show_sma200', False)
    show_rsi = show_settings.get('show_rsi', True)
    show_supply = show_settings.get('show_supply', True)
    show_demand = show_settings.get('show_demand', True)
    zone_display = show_settings.get('zone_display', 'Both')
    max_bars = int(show_settings.get('max_bars', 120))
    rsi_period = int(show_settings.get('rsi_period', 14))
    
    # Filter zones
    filtered_zones = []
    current_price = data['Close'].iloc[-1]
    
    for date_str, zone_type, zone_info in zones:
        # Skip if zone type is not enabled
        if (zone_type == 'Supply' and not show_supply) or \
           (zone_type == 'Demand' and not show_demand):
            continue
            
        # Filter supply zones to be above current price
        if zone_type == 'Supply' and zone_info['lower'] > current_price * 0.95:
            filtered_zones.append((date_str, zone_type, zone_info))
            
        # Filter demand zones to be below current price
        elif zone_type == 'Demand' and zone_info['upper'] < current_price * 1.05:
            filtered_zones.append((date_str, zone_type, zone_info))
    
    # Limit data to specified number of bars
    if len(data) > max_bars:
        chart_data = data.tail(max_bars)
    else:
        chart_data = data
    
    # Create subplots: price, volume, and optionally RSI
    if show_rsi:
        fig = make_subplots(rows=3, cols=1, 
                           shared_xaxes=True, 
                           vertical_spacing=0.02, 
                           row_heights=[0.6, 0.2, 0.2])
    else:
        fig = make_subplots(rows=2, cols=1, 
                           shared_xaxes=True, 
                           vertical_spacing=0.02, 
                           row_heights=[0.8, 0.2])
    
    # Add candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=chart_data.index,
            open=chart_data['Open'], 
            high=chart_data['High'],
            low=chart_data['Low'], 
            close=chart_data['Close'],
            increasing=dict(line=dict(color='#26b067')),
            decreasing=dict(line=dict(color='#b02e26')),
            name='Price'
        ),
        row=1, col=1
    )
    
    # Add moving averages
    if show_sma20 and not chart_data['SMA20'].isna().all():
        fig.add_trace(
            go.Scatter(
                x=chart_data.index,
                y=chart_data['SMA20'],
                mode='lines',
                name='SMA 20',
                line=dict(color='#3a81c3', width=1.5)
            ),
            row=1, col=1
        )
    
    if show_sma50 and not chart_data['SMA50'].isna().all():
        fig.add_trace(
            go.Scatter(
                x=chart_data.index,
                y=chart_data['SMA50'],
                mode='lines',
                name='SMA 50',
                line=dict(color='#e5ae38', width=1.5)
            ),
            row=1, col=1
        )
    
    if show_sma200 and not chart_data['SMA200'].isna().all():
        fig.add_trace(
            go.Scatter(
                x=chart_data.index,
                y=chart_data['SMA200'],
                mode='lines',
                name='SMA 200',
                line=dict(color='#e15759', width=1.5)
            ),
            row=1, col=1
        )
    
    # Add volume chart
    colors = ['#26b067' if row['Close'] >= row['Open'] else '#b02e26' for _, row in chart_data.iterrows()]
    
    fig.add_trace(
        go.Bar(
            x=chart_data.index,
            y=chart_data['Volume'],
            marker=dict(color=colors),
            name='Volume'
        ),
        row=2, col=1
    )
    
    # Add RSI if enabled
    if show_rsi:
        fig.add_trace(
            go.Scatter(
                x=chart_data.index,
                y=chart_data['RSI'],
                mode='lines',
                name='RSI',
                line=dict(color='#a379c9', width=1.5)
            ),
            row=3, col=1
        )
        
        # Add overbought/oversold lines
        fig.add_trace(
            go.Scatter(
                x=[chart_data.index[0], chart_data.index[-1]],
                y=[70, 70],
                mode='lines',
                name='Overbought',
                line=dict(color='#666666', width=1, dash='dash')
            ),
            row=3, col=1
        )
        
        fig.add_trace(
            go.Scatter(
                x=[chart_data.index[0], chart_data.index[-1]],
                y=[30, 30],
                mode='lines',
                name='Oversold',
                line=dict(color='#666666', width=1, dash='dash')
            ),
            row=3, col=1
        )
        
        fig.add_trace(
            go.Scatter(
                x=[chart_data.index[0], chart_data.index[-1]],
                y=[50, 50],
                mode='lines',
                name='Neutral',
                line=dict(color='#444444', width=1, dash='dash')
            ),
            row=3, col=1
        )
    
    # Add zone shapes
    for date_str, zone_type, zone_info in filtered_zones:
        zone_color = '#b02e26' if zone_type == 'Supply' else '#26b067'
        alpha = 0.1 + (zone_info['strength'] / 100) * 0.4
        
        # Convert alpha to RGBA
        rgba_color = f'rgba({int(zone_color[1:3], 16)}, {int(zone_color[3:5], 16)}, {int(zone_color[5:7], 16)}, {alpha})'
        
        # Add rectangle shapes for zones
        if zone_display in ['Filled Rectangles', 'Both']:
            fig.add_shape(
                type="rect",
                x0=chart_data.index[0],
                x1=chart_data.index[-1],
                y0=zone_info['lower'],
                y1=zone_info['upper'],
                fillcolor=rgba_color,
                line=dict(color=zone_color, width=1),
                layer="below",
                row=1, col=1
            )
        
        # Add horizontal lines for zone boundaries
        if zone_display in ['Horizontal Lines', 'Both']:
            # Upper boundary
            fig.add_shape(
                type="line",
                x0=chart_data.index[0],
                x1=chart_data.index[-1],
                y0=zone_info['upper'],
                y1=zone_info['upper'],
                line=dict(color=zone_color, width=1, dash="dash"),
                row=1, col=1
            )
            
            # Lower boundary
            fig.add_shape(
                type="line",
                x0=chart_data.index[0],
                x1=chart_data.index[-1],
                y0=zone_info['lower'],
                y1=zone_info['lower'],
                line=dict(color=zone_color, width=1, dash="dash"),
                row=1, col=1
            )
        
        # Add annotations for strongest zones
        if zone_info['strength'] > 70:
            # Find a good x-position (first 1/4 of the chart)
            x_pos = chart_data.index[len(chart_data) // 4]
            
            fig.add_annotation(
                x=x_pos,
                y=zone_info['level'],
                text=f"{zone_type} Zone ({zone_info['strength']:.0f}%)",
                showarrow=False,
                font=dict(color=zone_color, size=10),
                row=1, col=1
            )
    
    # Update layout
    fig.update_layout(
        title=f'{title} - {interval if interval else "Custom"} Timeframe',
        paper_bgcolor='#232323',
        plot_bgcolor='#1a1a1a',
        font=dict(color='#9e9e9e'),
        xaxis=dict(
            rangeslider=dict(visible=False),
            type='date',
            gridcolor='#333333',
            gridwidth=0.5
        ),
        yaxis=dict(
            title='Price',
            gridcolor='#333333',
            gridwidth=0.5
        ),
        xaxis2=dict(
