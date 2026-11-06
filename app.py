import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests, io, time, datetime, re
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title='NASDAQ Top 1000 + NSE HHLL(44) Screener', layout='wide', initial_sidebar_state='collapsed')

# Compact, single-screen dashboard styling. Scan logic and signal rules are unchanged.
st.markdown('''
<style>
    .block-container {max-width: 100% !important; padding-top: 3.2rem !important; padding-bottom: 1rem !important; padding-left: 2.2rem !important; padding-right: 2.2rem !important;}
    h1 {font-size: 1.8rem !important; line-height: 1.4 !important; text-align: center; margin-top: .35rem !important; margin-bottom: .5rem !important; padding-top: .15rem !important; padding-bottom: .15rem !important; overflow: visible !important;}
    [data-testid="stCaptionContainer"] {text-align: center;}
    [data-testid="stMetric"] {padding: .35rem .7rem; border: 1px solid rgba(128,128,128,.25); border-radius: 8px; background: rgba(128,128,128,.04);}
    [data-testid="stMetricValue"] {font-size: 1.55rem !important;}
    div.stButton {display:flex; justify-content:center; margin-top:-.2rem; margin-bottom:.3rem;}
    div.stButton > button {min-width: 125px; padding:.45rem 1.2rem; font-weight:600;}
    h2 {font-size:1.25rem !important; text-align:center; padding:.35rem .2rem; border:1px solid rgba(128,128,128,.25); border-radius:6px; margin:.35rem 0 .45rem !important;}
    h3 {font-size:1.05rem !important; text-align:center; margin:.2rem 0 .3rem !important;}
    [data-testid="stDataFrame"] {border:1px solid rgba(128,128,128,.2); border-radius:6px;}
    [data-testid="stVerticalBlock"] {gap:.55rem;}
    .market-buy h3 {color:#16a34a !important;}
    .market-sell h3 {color:#ef4444 !important;}
    footer {visibility:hidden;}
</style>
''', unsafe_allow_html=True)
st.title('NASDAQ & NSE — HHLL(44) Weekly Buy-Sell Alerts')
st.caption('NASDAQ: top 1,000 by market capitalisation  •  NSE: all listed equities  •  Latest weekly HHLL(44) alerts only')

@st.cache_data(ttl=86400, show_spinner=False)
def load_universes():
    """
    NASDAQ universe: top 1,000 NASDAQ-listed stocks by market capitalization.
    NSE universe: all equity symbols from the official NSE equity directory.
    """
    nasdaq=[]; nse=[]; notes=[]
    try:
        # Nasdaq screener returns exchange-listed securities with market-cap data.
        url='https://api.nasdaq.com/api/screener/stocks'
        params={'tableonly':'true','limit':'5000','exchange':'nasdaq'}
        headers={
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
            'Accept':'application/json, text/plain, */*',
            'Origin':'https://www.nasdaq.com',
            'Referer':'https://www.nasdaq.com/'
        }
        response=requests.get(url,params=params,headers=headers,timeout=30)
        response.raise_for_status()
        payload=response.json()
        rows=payload.get('data',{}).get('table',{}).get('rows',[]) or []
        ranked=[]
        for row in rows:
            symbol=str(row.get('symbol','')).strip().upper()
            # Exclude ETFs/funds and invalid ticker formats; retain ordinary listed stocks.
            if not re.fullmatch(r'[A-Z0-9.\\-]+',symbol):
                continue
            if str(row.get('isETF','')).strip().lower() in ('true','1','yes'):
                continue
            raw=str(row.get('marketCap','')).strip().upper().replace(',','').replace('$','')
            multiplier=1.0
            if raw.endswith('T'):
                multiplier=1_000_000_000_000; raw=raw[:-1]
            elif raw.endswith('B'):
                multiplier=1_000_000_000; raw=raw[:-1]
            elif raw.endswith('M'):
                multiplier=1_000_000; raw=raw[:-1]
            elif raw.endswith('K'):
                multiplier=1_000; raw=raw[:-1]
            cleaned=re.sub(r'[^0-9.]','',raw)
            try:
                market_cap=float(cleaned)*multiplier if cleaned else 0.0
            except ValueError:
                market_cap=0.0
            if market_cap>0:
                ranked.append((symbol,market_cap))
        # Deduplicate and rank descending by market capitalization.
        best={}
        for symbol,market_cap in ranked:
            best[symbol]=max(market_cap,best.get(symbol,0))
        nasdaq=[s for s,_ in sorted(best.items(),key=lambda item:item[1],reverse=True)[:1000]]
        if len(nasdaq)<1000:
            notes.append(f'NASDAQ screener returned only {len(nasdaq):,} eligible stocks with market-cap data.')
    except Exception as e:
        notes.append('NASDAQ top-1,000 market-cap list unavailable; NASDAQ scan skipped to avoid scanning an incorrect universe: '+str(e))
    try:
        url='https://archives.nseindia.com/content/equities/EQUITY_L.csv'
        r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=20); r.raise_for_status()
        d=pd.read_csv(io.BytesIO(r.content))
        col=next(c for c in d.columns if c.strip().upper()=='SYMBOL')
        nse=d[col].dropna().astype(str).str.strip().tolist()
        nse=[x for x in nse if re.fullmatch(r'[A-Z0-9&\\-]+',x)]
        nse=sorted(set(nse))
    except Exception as e:
        notes.append('NSE equity directory unavailable: '+str(e))
    return nasdaq, nse, notes

def yahoo_symbol(sym, market):
    return sym if market=='NASDAQ' else sym+'.NS'

def hhll_signal(df, period=44):
    # Pine source: highestbars(high,44)==0 / lowestbars(low,44)==0;
    # maintain direction, append on direction change, update current pivot on extension.
    if df is None or len(df)<period+5: return None
    h=df['High'].astype(float).to_numpy(); l=df['Low'].astype(float).to_numpy()
    idx=[]; vals=[]; dirs=[]; direction=0; events=[]
    for i in range(period-1,len(df)):
        ph=h[i] if h[i] >= np.nanmax(h[i-period+1:i+1]) else np.nan
        pl=l[i] if l[i] <= np.nanmin(l[i-period+1:i+1]) else np.nan
        newdir = 1 if not np.isnan(ph) and np.isnan(pl) else (-1 if not np.isnan(pl) and np.isnan(ph) else direction)
        changed = newdir != direction
        direction=newdir
        if not np.isnan(ph) or not np.isnan(pl):
            value=ph if direction==1 else pl
            if changed:
                vals.insert(0,float(value)); idx.insert(0,i)
                if len(vals)>5: vals.pop(); idx.pop()
                if len(vals)>=3:
                    # Pine label compares newest pivot with pivot two positions back.
                    if direction==1:
                        label='Strong Sell' if vals[0]>vals[2] else 'Sell'
                    else:
                        label='Strong Buy' if vals[0]<vals[2] else 'Buy'
                    events.append((i,label,float(value)))
            elif vals and ((direction==1 and value>vals[0]) or (direction==-1 and value<vals[0])):
                vals[0]=float(value); idx[0]=i
                if len(vals)>=3:
                    label=('Strong Sell' if vals[0]>vals[2] else 'Sell') if direction==1 else ('Strong Buy' if vals[0]<vals[2] else 'Buy')
                    if events and events[-1][0] == idx[0]: events[-1]=(i,label,float(value))
    # Return a stock ONLY when a new HHLL(44) label/alert is generated
    # on the latest available weekly candle. Do not carry forward older signals.
    if not events: return None
    i,label,pivot=events[-1]
    latest_i=len(df)-1
    if i != latest_i:
        return None
    return {'Signal':label,'Alert Date':pd.Timestamp(df.index[latest_i]).strftime('%Y-%m-%d'),'Pivot Price':pivot,'Last Close':float(df['Close'].iloc[-1]),'Week':pd.Timestamp(df.index[-1]).strftime('%Y-%m-%d')}

def scan_one(sym, market):
    ticker=yahoo_symbol(sym,market)
    try:
        data=yf.download(ticker, period='5y', interval='1wk', auto_adjust=False, progress=False, threads=False)
        if data is None or data.empty: return None
        if isinstance(data.columns,pd.MultiIndex): data.columns=data.columns.get_level_values(0)
        result=hhll_signal(data,44)
        if not result: return None
        result.update({'Symbol':sym,'Market':market,'Yahoo Symbol':ticker})
        return result
    except Exception: return None

nasdaq,nse,notes=load_universes()
with st.sidebar:
    st.header('Scan settings')
    markets=st.multiselect('Markets', ['NASDAQ','NSE'], default=['NASDAQ','NSE'])
    refresh=st.number_input('Auto-refresh (minutes)',min_value=0,max_value=1440,value=60,step=5,help='0 disables automatic refresh.')
    batch=st.slider('Concurrent downloads',1,12,5)
    st.caption('Only symbols with a newly generated HHLL(44) Buy/Sell alert on the latest weekly candle are displayed. Older signals are excluded.')

# Compact header: universe counts and scan action stay above the four live alert panels.
u1,u2,u3=st.columns([1,1,.8], vertical_alignment='center')
u1.metric('NASDAQ top-1,000 universe',f'{len(nasdaq):,}')
u2.metric('NSE all listed equities',f'{len(nse):,}')
with u3:
    st.write('')
    scan_clicked=st.button('Scan Now',type='primary',use_container_width=True)

for n in notes: st.warning(n)
if 'results' not in st.session_state: st.session_state.results=None
if scan_clicked or st.session_state.results is None:
    universe=[]
    if 'NASDAQ' in markets: universe += [(s,'NASDAQ') for s in nasdaq]
    if 'NSE' in markets: universe += [(s,'NSE') for s in nse]
    if not universe:
        st.warning('No symbols available for the selected market(s). Check the exchange universe download and try again.')
    rows=[]; failures=0
    progress=st.progress(0); status=st.empty()
    with ThreadPoolExecutor(max_workers=batch) as ex:
        futs={ex.submit(scan_one,s,m):(s,m) for s,m in universe}
        total=len(futs)
        for k,f in enumerate(as_completed(futs),1):
            try:
                x=f.result()
                if x: rows.append(x)
            except Exception: failures+=1
            if k%10==0 or k==total:
                progress.progress(k/max(total,1)); status.write(f'Scanned {k:,} / {total:,} symbols • New weekly alerts: {len(rows):,}')
    st.session_state.results=pd.DataFrame(rows)
    st.session_state.scan_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.failures=failures

res=st.session_state.results
if res is not None:
    scan_meta=st.columns([1,1,1])
    scan_meta[0].caption(f"Last scan: {st.session_state.get('scan_time','Not scanned yet')}")
    scan_meta[1].caption(f"New alerts: {len(res):,}")
    scan_meta[2].caption(f"Download/data errors: {st.session_state.get('failures',0):,}")
    if not res.empty:
        res=res.sort_values(['Market','Symbol'])

    # Four side-by-side panels, matching the supplied reference image.
    panel_defs=[
        ('NASDAQ','BUY STOCKS',['Buy','Strong Buy'],'market-buy'),
        ('NASDAQ','SELL STOCKS',['Sell','Strong Sell'],'market-sell'),
        ('NSE','BUY STOCKS',['Buy','Strong Buy'],'market-buy'),
        ('NSE','SELL STOCKS',['Sell','Strong Sell'],'market-sell')
    ]
    cols=st.columns(4, gap='small')
    for col,(market,label,signals,style) in zip(cols,panel_defs):
        market_df=res[res['Market']==market] if not res.empty else pd.DataFrame()
        subset=market_df[market_df['Signal'].isin(signals)] if not market_df.empty else pd.DataFrame(columns=['Symbol','Signal'])
        with col:
            st.markdown(f'<div class="{style}"><h3>{market} · {label}</h3></div>',unsafe_allow_html=True)
            st.metric('Stocks',len(subset))
            view=subset[['Symbol','Signal']].reset_index(drop=True) if not subset.empty else pd.DataFrame(columns=['Symbol','Signal'])
            st.dataframe(view,use_container_width=True,hide_index=True,height=300)

    if not res.empty:
        st.download_button('Download all signals CSV',res.to_csv(index=False).encode(),file_name='nasdaq_nse_hhll44_weekly_signals.csv',mime='text/csv')

st.caption('Only stocks with a newly generated HHLL(44) alert on the latest weekly candle are listed. Older signals are excluded.')

if refresh>0:
    st.info(f'Automatic refresh is set to {refresh} minutes. Use Scan Now for an immediate scan. Keep this page open.')
    st.markdown(f'<meta http-equiv="refresh" content="{int(refresh*60)}">',unsafe_allow_html=True)
