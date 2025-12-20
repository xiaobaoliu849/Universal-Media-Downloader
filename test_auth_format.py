#!/usr/bin/env python3
"""
Test authentication formats for Moonshot AI Anthropic endpoint
"""
import requests
import json
import base64

def test_auth_formats():
    """Test different authentication formats"""
    
    url = "https://api.moonshot.ai/anthropic/v1/messages"
    
    # Different authentication formats to test
    auth_configs = [
        {
            "name": "Anthropic API Key Header",
            "headers": {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": "test-key-123"
            }
        },
        {
            "name": "Bearer Token",
            "headers": {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01", 
                "Authorization": "Bearer test-key-123"
            }
        },
        {
            "name": "Basic Auth",
            "headers": {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "Authorization": f"Basic {base64.b64encode(b'test-key-123:').decode()}"
            }
        }
    ]
    
    test_data = {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Hello, test!"}]
    }
    
    print("Testing Authentication Formats for Moonshot AI Anthropic Endpoint")
    print("=" * 70)
    
    for config in auth_configs:
        print(f"\nTesting: {config['name']}")
        print(f"Headers: {json.dumps(config['headers'], indent=2)}")
        
        try:
            response = requests.post(
                url,
                headers=config['headers'],
                json=test_data,
                timeout=10
            )
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            # Analyze response
            if response.status_code == 401:
                try:
                    error_data = response.json()
                    if 'error' in error_data:
                        error_type = error_data['error'].get('type', 'unknown')
                        error_message = error_data['error'].get('message', 'unknown')
                        print(f"Error Type: {error_type}")
                        print(f"Error Message: {error_message}")
                        
                        # Check if this looks like Anthropic error format
                        if error_type in ['invalid_authentication_error', 'incorrect_api_key_error']:
                            print("CONFIRMED: Response follows Anthropic API error format!")
                            
                except json.JSONDecodeError:
                    print("Response is not JSON format")
            
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
        
        print("-" * 50)

if __name__ == "__main__":
    test_auth_formats()