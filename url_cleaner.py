import json
import re
import os
import urllib.request
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

RULES_FILE = "clearurls_rules.json"
RULES_URL = "https://rules2.clearurls.xyz/data.minify.json"

class ClearURLCleaner:
    def __init__(self):
        self.rules_data = self._load_rules()
        self.providers = self.rules_data.get('providers', {})
        
        self.compiled_providers = []
        for provider_name, provider_data in self.providers.items():
            url_pattern = provider_data.get('urlPattern')
            rules = provider_data.get('rules', [])
            
            if url_pattern and rules:
                try:
                    compiled_url_pattern = re.compile(url_pattern)
                    compiled_rules = [re.compile(r) for r in rules]
                    
                    self.compiled_providers.append({
                        'name': provider_name,
                        'url_pattern': compiled_url_pattern,
                        'rules': compiled_rules
                    })
                except re.error:
                    continue

    def _load_rules(self) -> dict:
        if os.path.exists(RULES_FILE):
            try:
                with open(RULES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error reading local rules: {e}")
                
        # Fallback to downloading
        print(f"Downloading ClearURLs rules from {RULES_URL}...")
        try:
            req = urllib.request.Request(RULES_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                with open(RULES_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                return data
        except Exception as e:
            print(f"Failed to load rules: {e}")
            return {}

    def clean(self, url: str) -> str:
        parsed_url = urlparse(url)
        
        if not parsed_url.query:
            return url

        matching_rules = []
        for provider in self.compiled_providers:
            if provider['url_pattern'].search(url):
                matching_rules.extend(provider['rules'])
                
        if not matching_rules:
             return url

        query_params = parse_qsl(parsed_url.query, keep_blank_values=True)
        clean_params = []

        for key, value in query_params:
            is_trash = False
            for rule_regex in matching_rules:
                if rule_regex.search(key) or rule_regex.search(f"{key}={value}"):
                    is_trash = True
                    break
            
            if not is_trash:
                clean_params.append((key, value))

        new_query_string = urlencode(clean_params)
        clean_parsed = parsed_url._replace(query=new_query_string)
        
        return urlunparse(clean_parsed)

# Create a singleton instance to be used across the application
cleaner = ClearURLCleaner()
