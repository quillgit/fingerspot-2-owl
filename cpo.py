import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return jsonify({
        'name': 'CPO Price API',
        'version': '1.0',
        'endpoints': {
            'latest_price': {
                'url': '/api/cpo/latest',
                'method': 'GET',
                'description': 'Get latest CPO price with USD and IDR conversion'
            },
            'historical_data': {
                'url': '/api/cpo/historical',
                'method': 'GET',
                'description': 'Get historical CPO price data'
            }
        }
    })

def get_cpo_data(url, rate_type):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        
        scripts = soup.find_all("script")
        data_series = []
        
        for script in scripts:
            if 'config' in script.text and 'labels' in script.text:
                labels_match = re.search(r'labels:\s*\[(.*?)\]', script.text, re.DOTALL)
                data_match = re.search(r'data:\s*\[(.*?)\],\s*},\s*\]', script.text, re.DOTALL)
                
                if labels_match and data_match:
                    dates = [d.strip("'") for d in labels_match.group(1).split(',') if d.strip()]
                    prices = [float(p.strip()) for p in data_match.group(1).split(',') if p.strip()]
                    
                    if len(dates) == len(prices):
                        data_series = list(zip(dates, prices))
                        break
        
        return data_series
    except Exception as e:
        print(f"Error fetching {rate_type} CPO data:", e)
        return None

def get_currency_rate(from_currency):
    try:
        response = requests.get(f'https://api.exchangerate-api.com/v4/latest/{from_currency}')
        data = response.json()
        return {
            'USD': data['rates']['USD'],
            'IDR': data['rates']['IDR']
        }
    except Exception as e:
        print(f"Error fetching {from_currency} exchange rate:", e)
        return None

@app.route('/api/cpo/latest', methods=['GET'])
def get_latest_price():
    rotterdam_data = get_cpo_data("https://www.bpdp.or.id/CPO_rotterdam.php", "Rotterdam")
    malaysia_data = get_cpo_data("https://www.bpdp.or.id/CPO_MBOP_malaysia.php", "Malaysia MBOP")
    
    if not rotterdam_data or not malaysia_data:
        return jsonify({
            'error': 'Failed to fetch CPO data'
        }), 500

    rotterdam_date, rotterdam_price = rotterdam_data[-1]
    malaysia_date, malaysia_price = malaysia_data[-1]
    
    # Get exchange rates
    usd_rates = get_currency_rate('USD')
    myr_rates = get_currency_rate('MYR')
    
    if not usd_rates or not myr_rates:
        return jsonify({
            'error': 'Failed to fetch exchange rates'
        }), 500

    # Convert prices
    rotterdam_idr_price = rotterdam_price * usd_rates['IDR']
    malaysia_usd_price = malaysia_price * myr_rates['USD']
    malaysia_idr_price = malaysia_price * myr_rates['IDR']
    
    return jsonify({
        'rotterdam': {
            'date': rotterdam_date,
            'price_usd_per_ton': rotterdam_price,
            'price_idr_per_ton': rotterdam_idr_price,
            'price_idr_per_kg': rotterdam_idr_price / 1000,
        },
        'malaysia_mbop': {
            'date': malaysia_date,
            'price_myr_per_ton': malaysia_price,
            'price_usd_per_ton': malaysia_usd_price,
            'price_idr_per_ton': malaysia_idr_price,
            'price_idr_per_kg': malaysia_idr_price / 1000,
        },
        'exchange_rates': {
            'USD_to_IDR': usd_rates['IDR'],
            'MYR_to_USD': myr_rates['USD'],
            'MYR_to_IDR': myr_rates['IDR']
        },
        'source': 'bpdp.or.id',
        'last_updated': datetime.now().isoformat()
    })

@app.route('/api/cpo/historical', methods=['GET'])
def get_historical_prices():
    rotterdam_data = get_cpo_data("https://www.bpdp.or.id/CPO_rotterdam.php", "Rotterdam")
    malaysia_data = get_cpo_data("https://www.bpdp.or.id/CPO_MBOP_malaysia.php", "Malaysia MBOP")
    
    if not rotterdam_data or not malaysia_data:
        return jsonify({
            'error': 'Failed to fetch CPO data'
        }), 500
    
    return jsonify({
        'rotterdam': [
            {
                'date': date,
                'price_usd_per_ton': price
            } for date, price in rotterdam_data
        ],
        'malaysia_mbop': [
            {
                'date': date,
                'price_usd_per_ton': price
            } for date, price in malaysia_data
        ],
        'source': 'bpdp.or.id',
        'last_updated': datetime.now().isoformat()
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
