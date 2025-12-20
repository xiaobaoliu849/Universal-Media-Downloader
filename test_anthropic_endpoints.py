#!/usr/bin/env python3
"""
Test various Anthropic API endpoints on Moonshot AI
"""
import requests
import json

def test_anthropic_endpoints():
    """Test various Anthropic API endpoints"""
    
    base_url = "https://api.moonshot.ai/anthropic"
    
    # Various Anthropic API endpoints to test
    endpoints_to_test = [
        "v1/messages",
        "v1/models", 
        "v1/complete",
        "v1/chat/completions",
        "v1/completions",
        "health",
        "v1/health"
    ]
    
    print("Testing various Anthropic API endpoints on Moonshot AI")
    print("=" * 60)
    
    working_endpoints = []
    
    for endpoint in endpoints_to_test:
        url = f"{base_url}/{endpoint}"
        print(f"\nTesting: {url}")
        
        try:
            # Test GET request
            response = requests.get(url, timeout=10)
            print(f"GET Status: {response.status_code}")
            
            if response.status_code != 404:
                working_endpoints.append({
                    'endpoint': endpoint,
                    'method': 'GET',
                    'status': response.status_code,
                    'response': response.text[:100]
                })
            
            # Test POST request with basic data
            post_response = requests.post(
                url, 
                headers={"Content-Type": "application/json"},
                json={"test": "data"},
                timeout=10
            )
            print(f"POST Status: {post_response.status_code}")
            
            if post_response.status_code != 404:
                working_endpoints.append({
                    'endpoint': endpoint,
                    'method': 'POST',
                    'status': post_response.status_code,
                    'response': post_response.text[:100]
                })
                
        except requests.exceptions.RequestException as e:
            print(f"ERROR: {e}")
    
    print("\n" + "=" * 60)
    print("WORKING ENDPOINTS SUMMARY")
    print("=" * 60)
    
    if working_endpoints:
        for endpoint in working_endpoints:
            print(f"Endpoint: {endpoint['endpoint']}")
            print(f"Method: {endpoint['method']}")
            print(f"Status: {endpoint['status']}")
            print(f"Response: {endpoint['response']}")
            print("-" * 40)
    else:
        print("No working endpoints found other than messages endpoint")
    
    return working_endpoints

if __name__ == "__main__":
    test_anthropic_endpoints()