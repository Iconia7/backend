# backend/finance/payhero_utils.py

import os
import requests
from django.utils import timezone
from urllib3.exceptions import InsecureRequestWarning # <-- 1. Import the exception
import urllib3 # <-- 2. Import urllib3

# 3. Suppress the warning
urllib3.disable_warnings(InsecureRequestWarning)

def initiate_payhero_push(phone_number, amount, external_reference):
    """
    Initiates an STK Push request using the PayHero API.
    """
    api_url = "https://backend.payhero.co.ke/api/v2/payments"
    
    auth_header = os.getenv('PAYHERO_BASIC_AUTH')
    channel_id = os.getenv('PAYHERO_CHANNEL_ID')
    
    # Get your deployed URL and build the callback
    base_url = os.getenv('BACKEND_URL')
    callback_url = f"{base_url}/api/finance/payment-callback/"

    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }
    
    payload = {
        "amount": float(amount),
        "phone_number": phone_number,
        "channel_id": int(channel_id),
        "provider": "m-pesa",
        "external_reference": external_reference,
        "callback_url": callback_url,
        "customer_name": "Kampus Koin User"
    }

    try:
        # We use verify=False to match your 'rejectUnauthorized: false'
        # This is a security risk in production, but is often
        # required for these third-party APIs.
        response = requests.post(api_url, json=payload, headers=headers, verify=False)
        response.raise_for_status() # Raise an exception for bad status codes
        
        return response.json()
        
    except requests.exceptions.RequestException as e:
        print(f"PayHero initiation error: {e.response.text if e.response else e}")
        return None