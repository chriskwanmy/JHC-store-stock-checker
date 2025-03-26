import requests
import pandas as pd
import os
from datetime import datetime
from bs4 import BeautifulSoup
import re
import json
import time

# Disable SSL warnings
requests.packages.urllib3.disable_warnings()

# Global variable to store shortage data
shortage_summary = []

def fetch_product_info(url):
    """Fetch Product ID, Title, and SKU from the product page"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        response.raise_for_status()
        
        sku = url.split('/')[-1].replace('.html', '')
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tags = soup.find_all('script')

        for script in script_tags:
            if script.string and 'INLINED_PAGE_TYPE' in script.string:
                match = re.search(r'JSON\.parse\([\'"]({.*?})[\'"]\.replace', str(script.string))
                if match:
                    json_str = match.group(1).replace('&quot;', '"')
                    print(f"📋 Extracted JSON string: {json_str}")
                    
                    try:
                        data = json.loads(json_str)
                        if 'id' not in data:
                            print("❌ 'id' field missing in JSON")
                            continue
                        product_id = int(data['id'])
                        product_title = get_product_title(product_id)
                        if product_title:
                            print(f"✅ Found product: ID={product_id}, Title={product_title}, SKU={sku}")
                            return product_id, product_title, sku
                    except json.JSONDecodeError as e:
                        print(f"❌ JSON parsing error: {e}")
                        print(f"Problematic JSON: {json_str}")
                        continue
        
        print(f"❌ Unable to extract product information from {url}")
        return None, None, None
    
    except requests.RequestException as e:
        print(f"❌ Failed to request page: {e}")
        return None, None, None

def get_product_title(product_id):
    """Query product name using GraphQL"""
    graphql_url = "https://www.jhceshop.com/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0"
    }
    query = """
    query getProductDetailForProductById($id: String!) {
        products(filter: { product_id: { eq: $id } }) {
            items {
                name
            }
        }
    }
    """
    payload = {
        "query": query,
        "variables": {"id": str(product_id)},
        "operationName": "getProductDetailForProductById"
    }
    
    try:
        response = requests.post(graphql_url, json=payload, headers=headers, verify=False, timeout=10)
        response.raise_for_status()
        data = response.json()
        items = data.get('data', {}).get('products', {}).get('items', [])
        if items:
            return items[0]['name']
        print(f"❌ GraphQL did not return product name")
        return None
    except requests.RequestException as e:
        print(f"❌ Failed to query product name via GraphQL: {e}")
        return None

def get_stock_status(product_id):
    """Query stock status for all regions"""
    graphql_url = "https://www.jhceshop.com/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0"
    }
    query = """
    query GetStoreStockStatus($productId: Int, $countryId: String, $regionId: Int) {
        storeStockStatus(product_id: $productId, country_id: $countryId, region_id: $regionId) {
            stock_status
            store_name
            store_address_street
            store_tel_1
            opening_hour_1
        }
    }
    """
    
    regions = [
        {"id": 1347, "name": "Hong Kong", "country": "HK"},
        {"id": 1350, "name": "Kowloon", "country": "HK"},
        {"id": 1353, "name": "New Territories", "country": "HK"},
        {"id": 1356, "name": "Islands/Remote Areas", "country": "HK"},
        {"id": 1365, "name": "Macau", "country": "MO"}
    ]
    
    all_stores = []
    for region in regions:
        payload = {
            "query": query,
            "variables": {
                "productId": product_id,
                "countryId": region["country"],
                "regionId": region["id"]
            },
            "operationName": "GetStoreStockStatus"
        }
        
        try:
            response = requests.post(graphql_url, json=payload, headers=headers, verify=False, timeout=10)
            response.raise_for_status()
            data = response.json()
            stores = data.get('data', {}).get('storeStockStatus', [])
            for store in stores:
                store['region'] = region['name']
            all_stores.extend(stores)
            print(f"✓ {region['name']} query successful")
        except requests.RequestException as e:
            print(f"❌ {region['name']} query failed: {e}")
    
    return all_stores if all_stores else None

def process_and_save(product_id, product_title, sku):
    """Process stock data and save to Excel, while collecting shortage information"""
    global shortage_summary
    
    stock_data = get_stock_status(product_id)
    if not stock_data:
        print("❌ Unable to fetch stock data")
        return
    
    stock_status_map = {0: "Out of Stock", 1: "Low Stock", 2: "In Stock"}
    processed_data = []
    
    for store in stock_data:
        status = stock_status_map.get(store['stock_status'], 'Unknown')
        store_data = {
            'Region': store['region'],
            'Product Title': product_title,
            'SKU': sku,
            'Address': store.get('store_address_street', ''),
            'Phone': store.get('store_tel_1', ''),
            'Opening Hours': store.get('opening_hour_1', ''),
            'Stock Status': status
        }
        processed_data.append(store_data)
        
        # Collect shortage and low stock information
        if status in ["Out of Stock", "Low Stock"]:
            shortage_summary.append({
                'Product Title': product_title,
                'SKU': sku,
                'Store Name': store['store_name'],
                'Region': store['region'],
                'Stock Status': status
            })
    
    df = pd.DataFrame(processed_data)
    
    os.makedirs('stock_status', exist_ok=True)
    safe_title = ''.join(c for c in product_title if c.isalnum())[:20]
    filename = os.path.join('stock_status', f'{safe_title}_{sku}.xlsx')
    
    try:
        df.to_excel(filename, index=False, engine='openpyxl')
        print(f"💾 Saved to: {filename}")
        print("\n📊 Stock Statistics:")
        print(df['Stock Status'].value_counts())
    except Exception as e:
        print(f"❌ Failed to save file: {e}")

def generate_shortage_report():
    """Generate shortage summary report"""
    global shortage_summary
    
    if not shortage_summary:
        print("✅ All products have sufficient stock in all stores")
        return
    
    df = pd.DataFrame(shortage_summary)
    
    # Save summary report
    os.makedirs('stock_status', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join('stock_status', f'shortage_summary_{timestamp}.xlsx')
    
    try:
        df.to_excel(filename, index=False, engine='openpyxl')
        print(f"📊 Shortage summary report saved to: {filename}")
        
        # Print simple statistics
        print("\n📈 Shortage Statistics:")
        out_of_stock = df[df['Stock Status'] == 'Out of Stock']
        low_stock = df[df['Stock Status'] == 'Low Stock']
        
        print(f"Number of out-of-stock products: {len(out_of_stock.groupby(['Product Title', 'SKU']))}")
        print(f"Number of low-stock products: {len(low_stock.groupby(['Product Title', 'SKU']))}")
        print(f"Total shortage records: {len(df)}")
        
    except Exception as e:
        print(f"❌ Failed to generate shortage report: {e}")

def main():
    """Main function: process multiple URLs and generate summary"""
    global shortage_summary
    shortage_summary = []  # Reset shortage data
    
    try:
        with open('urls.txt', 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("❌ 'urls.txt' file not found")
        return
    
    if not urls:
        print("❌ 'urls.txt' file is empty")
        return
    
    for i, url in enumerate(urls, 1):
        print(f"\n📦 Processing {i}/{len(urls)}: {url}")
        product_id, product_title, sku = fetch_product_info(url)
        if product_id and product_title and sku:
            process_and_save(product_id, product_title, sku)
        time.sleep(2)
    
    # Generate shortage summary report
    generate_shortage_report()

if __name__ == "__main__":
    print(f"📅 Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    main()
    print(f"🏁 End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
