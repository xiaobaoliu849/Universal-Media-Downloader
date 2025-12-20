#!/usr/bin/env python3
"""
Test Moonshot AI Anthropic compatible endpoint
"""
import requests
import json

def test_moonshot_anthropic_endpoint():
    """Test Moonshot AI's Anthropic compatible endpoint"""
    
    # Base URL for Moonshot AI Anthropic endpoint
    base_url = "https://api.moonshot.ai/anthropic"
    
    # Test endpoints
    test_configs = [
        {
            "name": "Messages endpoint",
            "url": f"{base_url}/v1/messages",
            "method": "POST",
            "headers": {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": "test-key"
            },
            "data": {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "Hello"}]
            }
        },
        {
            "name": "Models endpoint",
            "url": f"{base_url}/v1/models",
            "method": "GET",
            "headers": {
                "x-api-key": "test-key"
            }
        }
    ]
    
    results = []
    
    for config in test_configs:
        print(f"\nTesting {config['name']}...")
        print(f"URL: {config['url']}")
        
        try:
            if config['method'] == 'POST':
                response = requests.post(
                    config['url'], 
                    headers=config['headers'],
                    json=config.get('data', {}),
                    timeout=10
                )
            else:
                response = requests.get(
                    config['url'],
                    headers=config['headers'],
                    timeout=10
                )
            
            result = {
                'name': config['name'],
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'response_text': response.text,
                'success': response.status_code in [200, 401, 403]  # Accept auth errors as success
            }
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text[:200]}...")
            
            # Check for Anthropic-specific headers or response format
            if 'application/json' in response.headers.get('content-type', ''):
                try:
                    json_data = response.json()
                    result['json_response'] = json_data
                    
                    # Check if response looks like Anthropic format
                    if 'error' in json_data and 'type' in json_data['error']:
                        print("OK Response contains Anthropic-style error format")
                    elif 'content' in json_data:
                        print("OK Response contains Anthropic-style message format")
                        
                except json.JSONDecodeError:
                    print("ERROR Response is not valid JSON")
            
            results.append(result)
            
        except requests.exceptions.RequestException as e:
            print(f"ERROR Request failed: {e}")
            results.append({
                'name': config['name'],
                'error': str(e),
                'success': False
            })
    
    return results

if __name__ == "__main__":
    print("Testing Moonshot AI Anthropic Compatible Endpoint")
    print("=" * 50)
    
    results = test_moonshot_anthropic_endpoint()
    
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    
    working_endpoints = [r for r in results if r.get('success', False)]
    failed_endpoints = [r for r in results if not r.get('success', False)]
    
    print(f"Working endpoints: {len(working_endpoints)}")
    print(f"Failed endpoints: {len(failed_endpoints)}")
    
    if working_endpoints:
        print("\nWorking endpoints:")
        for endpoint in working_endpoints:
            print(f"  OK {endpoint['name']} (Status: {endpoint['status_code']})")
    
    if failed_endpoints:
        print("\nFailed endpoints:")
        for endpoint in failed_endpoints:
            print(f"  ERROR {endpoint['name']}: {endpoint.get('error', 'Unknown error')}")