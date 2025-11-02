# finance/mpesa_utils.py

import os
import requests
import base64
from datetime import datetime

def get_mpesa_access_token():
    """
    Requests an access token from the Safaricom Daraja API.
    """
    consumer_key = os.getenv('MPESA_CONSUMER_KEY')
    consumer_secret = os.getenv('MPESA_CONSUMER_SECRET')
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

    # The authorization header requires a base64 encoded string of consumer key and secret
    auth_string = f"{consumer_key}:{consumer_secret}"
    auth_bytes = auth_string.encode('utf-8')
    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')

    headers = {"Authorization": f"Basic {auth_b64}"}

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status() # An exception for bad status codes
        result = response.json()
        return result.get('access_token')
    except requests.exceptions.RequestException as e:
        print(f"Error getting access token: {e}")
        return None
    
def initiate_stk_push(phone_number, amount, access_token, goal_id):
    """
    Initiates an STK Push request to the Safaricom Daraja API.
    """
    stk_push_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

    # Get credentials from environment variables
    business_shortcode = os.getenv('MPESA_BUSINESS_SHORTCODE')
    passkey = os.getenv('MPESA_PASSKEY')
    ngrok_url = os.getenv('NGROK_URL')

    # Generate timestamp and password
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = f"{business_shortcode}{passkey}{timestamp}"
    password_bytes = password_str.encode('utf-8')
    password = base64.b64encode(password_bytes).decode('utf-8')

    # This is the URL Safaricom will call to confirm the transaction
    callback_url = f"{ngrok_url}/api/finance/payment-callback/"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "BusinessShortCode": business_shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount), # Amount must be an integer
        "PartyA": phone_number,
        "PartyB": business_shortcode,
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": str(goal_id),
        "TransactionDesc": "Savings Goal Deposit"
    }

    try:
        response = requests.post(stk_push_url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error initiating STK push: {e}")
        return None 


def register_mpesa_urls():
    """
    Registers the Validation and Confirmation URLs with the M-Pesa API.
    This is a one-time setup step.
    """
    access_token = get_mpesa_access_token()
    if not access_token:
        print("Could not get M-Pesa access token.")
        return

    api_url = "https://sandbox.safaricom.co.ke/mpesa/c2b/v1/registerurl"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "ShortCode": 600995,
        "ResponseType": "Cancelled", # Or "Cancelled" if you want to be notified of cancellations
        "ConfirmationURL": f"{os.getenv('NGROK_URL')}/api/finance/payment-callback/",
        "ValidationURL": f"{os.getenv('NGROK_URL')}/api/finance/payment-callback/"
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers)
        response.raise_for_status()
        print("URLs registered successfully:")
        print(response.json())
    except requests.exceptions.RequestException as e:
        print(f"Error registering URLs: {e}")
        print(f"Response body: {e.response.text if e.response else 'No response'}")