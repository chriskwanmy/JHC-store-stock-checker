import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import json
import pandas as pd
from datetime import datetime
import re
from bs4 import BeautifulSoup
import os
import time

# Add global variable to store shortage data
shortage_data = []

def get_store_stock_status(product_id):
    """Get store stock status for the specified product ID"""
    
    url = "https://www.jhceshop.com/graphql"
    
    # Define region_id for different areas
    regions = [
        {"id": 1347, "name": "Hong Kong", "country": "HK"},
        {"id": 1350, "name": "Kowloon", "country": "HK"},
        {"id": 1353, "name": "New Territories", "country": "HK"},
        {"id": 1356, "name": "Islands/Remote Areas", "country": "HK"},
        {"id": 1365, "name": "Macau", "country": "MO"}
    ]
    
    all_stores = []
    
    # GraphQL query
    query = """
    query GetStoreStockStatus($productId: Int, $countryId: String, $regionId: Int) {
        storeStockStatus(product_id: $productId, country_id: $countryId, region_id: $regionId) {
            stock_status
            store_code
            store_name
            custom_region
            opening_hour_1
            shop_type
            store_address_street
            store_tel_1
            x_coordinate
            y_coordinate
        }
    }
    """
    
    print(f"🔄 Querying stock status for product ID {product_id}...")
    
    # Query each region
    for region in regions:
        # Prepare GraphQL query parameters
        variables = {
            "productId": product_id,
            "countryId": region["country"],
            "regionId": region["id"]
        }
        
        # Prepare request
        payload = {
            "query": query,
            "variables": variables,
            "operationName": "GetStoreStockStatus"
        }
        
        # Send request with SSL verification disabled
        response = requests.post(url, json=payload, verify=False)
        
        if response.status_code == 200:
            data = response.json()
            if data and 'data' in data and 'storeStockStatus' in data['data']:
                # Add region name to each store data
                for store in data['data']['storeStockStatus']:
                    store['custom_region'] = region['name']
                all_stores.extend(data['data']['storeStockStatus'])
                print(f"✓ {region['name']} query successful")
            else:
                print(f"❌ {region['name']} data format error")
        else:
            print(f"❌ {region['name']} query failed: {response.status_code}")
    
    if all_stores:
        return {"data": {"storeStockStatus": all_stores}}
    else:
        print("❌ All region queries failed")
        return None

def process_stock_data(data, product_id, product_title, sku):
    """Process stock data and convert to DataFrame, while collecting shortage information"""
    global shortage_data
    
    if not data or 'data' not in data or 'storeStockStatus' not in data['data']:
        print("❌ Data format error")
        return None
    
    stores = data['data']['storeStockStatus']
    
    # Prepare data list
    processed_data = []
    for store in stores:
        # Convert stock status to readable format
        stock_status_map = {
            0: "Out of Stock",
            1: "Low Stock",
            2: "In Stock"
        }
        status_text = stock_status_map.get(store['stock_status'], "Unknown")
        
        # Collect shortage and low stock data
        if store['stock_status'] in [0, 1]:
            shortage_data.append({
                'Product Title': product_title,
                'Product ID': product_id,
                'SKU': sku,
                'Region': store['custom_region'],
                'Store Name': store['store_name'],
                'Address': store['store_address_street'],
                'Phone': store['store_tel_1'],
                'Stock Status': status_text
            })
        
        processed_data.append({
            'Region': store['custom_region'],
            'Product Title': product_title,
            'SKU': sku,
            'Address': store['store_address_street'],
            'Phone': store['store_tel_1'],
            'Opening Hours': store['opening_hour_1'],
            'Stock Status': status_text
        })
    
    return pd.DataFrame(processed_data)

def save_stock_status(product_id, product_title=''):
    """Get and save store stock status"""
    
    # Get data
    data = get_store_stock_status(product_id)
    if not data:
        return
    
    # Process data
    df = process_stock_data(data, product_id, product_title)
    if df is None:
        return
        
    # Set product title
    df['Product Title'] = product_title
    
    # Create fixed storage folder
    if not os.path.exists('stock_status'):
        os.makedirs('stock_status')
    
    # Process filename (remove spaces and special characters)
    safe_title = product_title.replace(' ', '').replace('/', '_').replace('\\', '_')[:20]
    filename = os.path.join('stock_status', f'{safe_title}_{product_id}.xlsx')
    
    try:
        # Create Excel writer
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            if df.empty:
                print("❌ No store data found")
                pd.DataFrame().to_excel(writer, sheet_name='No Data')
                return
            
            # Save all data to worksheet
            df.to_excel(writer, sheet_name='All Stores', index=False)
        
        print(f"💾 Stock data saved to file: {filename}")
        
        # Print statistics
        stock_summary = df['Stock Status'].value_counts()
        print("\n📊 Stock Statistics:")
        for status, count in stock_summary.items():
            print(f"{status}: {count} stores")
            
    except Exception as e:
        print(f"❌ Error saving file: {str(e)}")

def get_product_info_from_page(url):
    """Get product ID and title from the product page"""
    try:
        print(f"🔍 Getting product information from page: {url}")
        
        # Extract SKU from URL
        sku = url.split('/')[-1].replace('.html', '')
        
        # Get page content with SSL verification disabled
        response = requests.get(url, verify=False)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Find script tags containing INLINED_PAGE_TYPE
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'INLINED_PAGE_TYPE' in str(script.string):
                    match = re.search(r'JSON\.parse\([\'"]({.*?})[\'"]\.replace', str(script.string))
                    if match:
                        json_str = match.group(1).replace('&quot;', '"')
                        try:
                            data = json.loads(json_str)
                            if 'id' in data:
                                product_id = data['id']
                                print(f"Product ID found: {product_id}")
                                
                                # Use obtained product_id for GraphQL query
                                url = "https://www.jhceshop.com/graphql"
                                
                                # Define region_id for different areas
                                regions = [
                                    {"id": 1347, "name": "Hong Kong", "country": "HK"},
                                    {"id": 1350, "name": "Kowloon", "country": "HK"},
                                    {"id": 1353, "name": "New Territories", "country": "HK"},
                                    {"id": 1356, "name": "Islands/Remote Areas", "country": "HK"},
                                    {"id": 1365, "name": "Macau", "country": "MO"}
                                ]
                                
                                # GraphQL query
                                query = """
                                query GetStoreStockStatus($productId: Int, $countryId: String, $regionId: Int) {
                                    storeStockStatus(product_id: $productId, country_id: $countryId, region_id: $regionId) {
                                        stock_status
                                        store_code
                                        store_name
                                        custom_region
                                        opening_hour_1
                                        shop_type
                                        store_address_street
                                        store_tel_1
                                        x_coordinate
                                        y_coordinate
                                    }
                                }
                                """
                                
                                # Test each region
                                for region in regions:
                                    # Prepare GraphQL query parameters
                                    variables = {
                                        "productId": product_id,
                                        "countryId": region["country"],
                                        "regionId": region["id"]
                                    }
                                    
                                    # Prepare request
                                    payload = {
                                        "query": query,
                                        "variables": variables,
                                        "operationName": "GetStoreStockStatus"
                                    }
                                    
                                    # Send request with SSL verification disabled
                                    response = requests.post(url, json=payload, verify=False)
                                    
                                    print(f"Testing region: {region['name']}")
                                    print(f"HTTP Status Code: {response.status_code}")
                                    print("Response JSON:")
                                    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
                                    print("\n" + "="*50 + "\n")

                                    if response.status_code == 200:
                                        data = response.json()
                                        if data.get('data', {}).get('storeStockStatus'):
                                            # Assuming you want to return the first store's name as product title
                                            product_title = data['data']['storeStockStatus'][0]['store_name']
                                            print(f"✅ Success! Product ID: {product_id}, Product Name: {product_title}, SKU: {sku}")
                                            return int(product_id), product_title, sku
                                        else:
                                            print("⚠️ API returned incorrect data format")
                                    else:
                                        print(f"❌ API request failed, HTTP status code: {response.status_code}")
                        except json.JSONDecodeError:
                            print("❌ JSON decode error")
                            continue
                    else:
                        print("❌ JSON parse match not found")
        
        print("❌ Unable to get product information from page")
        return None, None, None
        
    except Exception as e:
        print(f"❌ Error while getting product information: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        print("Detailed error information:")
        print(traceback.format_exc())
        return None, None, None


def save_stock_status_from_url(url):
    """Get and save stock status from product URL"""
    product_id, product_title, sku = get_product_info_from_page(url)
    if product_id:
        # Get data
        data = get_store_stock_status(product_id)
        if data:
            # Process and save data
            df = process_stock_data(data, product_id, product_title, sku)
            if df is not None:
                # Create fixed storage folder
                if not os.path.exists('stock_status'):
                    os.makedirs('stock_status')
                
                # Process filename (remove spaces and special characters)
                safe_title = product_title.replace(' ', '').replace('/', '_').replace('\\', '_')[:20]
                filename = os.path.join('stock_status', f'{safe_title}_{sku}.xlsx')
                
                try:
                    # Create Excel writer
                    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                        if df.empty:
                            print("❌ No store data found")
                            pd.DataFrame().to_excel(writer, sheet_name='No Data')
                            return
                        
                        # Save all data to worksheet
                        df.to_excel(writer, sheet_name='All Stores', index=False)
                    
                    print(f"💾 Stock data saved to file: {filename}")
                    
                    # Print statistics
                    stock_summary = df['Stock Status'].value_counts()
                    print("\n📊 Stock Statistics:")
                    for status, count in stock_summary.items():
                        print(f"{status}: {count} stores")
                        
                except Exception as e:
                    print(f"❌ Error saving file: {str(e)}")
    else:
        print("❌ Unable to process this product")

def save_shortage_report():
    """Save shortage report"""
    global shortage_data
    
    if shortage_data:
        # Create DataFrame and save to Excel
        df = pd.DataFrame(shortage_data)
        
        # Create folder (if it doesn't exist)
        if not os.path.exists('stock_status'):
            os.makedirs('stock_status')
            
        # Use current time as filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join('stock_status', f'shortage_report_{timestamp}.xlsx')
        
        # Save to Excel
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Shortage Report', index=False)
            
        print(f"💾 Shortage report saved to file: {filename}")
        print(f"📊 Total {len(shortage_data)} shortage records")
    else:
        print("✨ No shortage or low stock situations found")

def process_multiple_urls(urls):
    """Process multiple product URLs"""
    global shortage_data
    shortage_data = []  # Reset shortage data
    
    print(f"🔄 Starting to process {len(urls)} products...")
    
    for i, url in enumerate(urls, 1):
        print(f"\n📦 Processing product {i}/{len(urls)}")
        print(f"🔗 URL: {url}")
        save_stock_status_from_url(url)
        
        if i < len(urls):
            time.sleep(2)
    
    # Save shortage report
    save_shortage_report()

def read_urls_from_file(filename):
    """Read URL list from text file"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            # Read all lines and remove whitespace
            urls = [line.strip() for line in f if line.strip()]
        return urls
    except Exception as e:
        print(f"❌ Error reading file: {str(e)}")
        return []

def test_api_response(product_id):
    """Test the API response for a given product ID"""
    url = "https://www.jhceshop.com/graphql"
    
    # Define region_id for different areas
    regions = [
        {"id": 1347, "name": "Hong Kong", "country": "HK"},
        {"id": 1350, "name": "Kowloon", "country": "HK"},
        {"id": 1353, "name": "New Territories", "country": "HK"},
        {"id": 1356, "name": "Islands/Remote Areas", "country": "HK"},
        {"id": 1365, "name": "Macau", "country": "MO"}
    ]
    
    # GraphQL query
    query = """
    query GetStoreStockStatus($productId: Int, $countryId: String, $regionId: Int) {
        storeStockStatus(product_id: $productId, country_id: $countryId, region_id: $regionId) {
            stock_status
            store_code
            store_name
            custom_region
            opening_hour_1
            shop_type
            store_address_street
            store_tel_1
            x_coordinate
            y_coordinate
        }
    }
    """
    
    # Test each region
    for region in regions:
        # Prepare GraphQL query parameters
        variables = {
            "productId": product_id,
            "countryId": region["country"],
            "regionId": region["id"]
        }
        
        # Prepare request
        payload = {
            "query": query,
            "variables": variables,
            "operationName": "GetStoreStockStatus"
        }
        
        # Send request with SSL verification disabled
        response = requests.post(url, json=payload, verify=False)
        
        print(f"Testing region: {region['name']}")
        print(f"HTTP Status Code: {response.status_code}")
        print("Response JSON:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        print("\n" + "="*50 + "\n")

# Example usage
if __name__ == "__main__":
    test_product_id = 173874  # Replace with a valid product ID for testing
    #test_api_response(test_product_id)

    # Method 1: Read URLs from file
    urls = read_urls_from_file('urls.txt')
    
    # Method 2: Define URL list directly in code
    # urls = [...]
    
    if urls:
        process_multiple_urls(urls)
    else:
        print("❌ No URLs found to process") 