import os
import random
import logging

logger = logging.getLogger(__name__)

class SiteConfig:
    """Base configuration for site-specific settings"""
    def __init__(self, url: str):
        self.url = url
        self.lower_url = url.lower()

    @property
    def is_missav(self) -> bool:
        return 'missav' in self.lower_url

    @property
    def is_twitter(self) -> bool:
        return 'twitter.com' in self.lower_url or 'x.com' in self.lower_url

    @property
    def is_youtube(self) -> bool:
        return 'youtube.com' in self.lower_url or 'youtu.be' in self.lower_url

    @property
    def is_adult_site(self) -> bool:
        return any(domain in self.lower_url for domain in ['pornhub.com', 'xvideos.com', 'xnxx.com', 'youporn.com'])

    def get_download_args(self, fast_mode: bool = False, extended: bool = False, primary: bool = False) -> dict:
        """
        Returns a dictionary of arguments for yt-dlp:
        {
            'impersonate': str,
            'headers': list[str],
            'timeout': int,
            'retries': int,
            'chunk_size': str,
            'socket_timeout': int,
            # ... other specific args
        }
        """
        settings = {
            'args': [],
            'concurrency': 4, # Default concurrency
            'chunk_size': '4M',
            'use_aria2c': None, # None = Auto/Default logic
        }

        # Default fast mode settings
        if fast_mode:
            settings['timeout'] = 15
            settings['retries'] = 2
        else:
            settings['timeout'] = 30
            settings['retries'] = 5

        # --- MissAV Configuration ---
        if self.is_missav:
            # Impersonate Chrome to bypass Cloudflare
            settings['impersonate'] = 'chrome'
            settings['timeout'] = 15 if fast_mode else 90
            settings['retries'] = 2 if fast_mode else 8
            settings['chunk_size'] = '10M'
            settings['concurrency'] = 16 # High concurrency for HLS
            settings['use_aria2c'] = False # Explicitly disable Aria2c for MissAV to avoid 403

            # Headers
            settings['args'] += [
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--add-header', 'Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                '--add-header', 'Accept-Language:en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                '--add-header', 'Referer:https://missav.ws/', # Keep .ws as default for now, or make dynamic?
                '--add-header', 'Sec-Ch-Ua:"Chromium";v="120", "Google Chrome";v="120"',
                '--add-header', 'Sec-Ch-Ua-Mobile:?0',
                '--add-header', 'Sec-Fetch-Dest:document',
                '--add-header', 'Sec-Fetch-Mode:navigate',
                '--add-header', 'Sec-Fetch-Site:same-origin',
                '--add-header', 'Upgrade-Insecure-Requests:1',
                '--sleep-interval', '5',
                '--max-sleep-interval', '15'
            ]
            if extended:
                ext_timeout = 45 if fast_mode else 120
                ext_retries = 7 if fast_mode else 10
                settings['timeout'] = ext_timeout
                settings['retries'] = ext_retries
                settings['args'] += ['--sleep-interval', '8', '--max-sleep-interval', '20']

        # --- Adult Sites Configuration ---
        elif self.is_adult_site:
            settings['chunk_size'] = '1M'
            settings['args'] += [
                '--force-ipv4',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--sleep-interval', '2',
                '--max-sleep-interval', '5',
                '--referer', 'https://www.google.com/',
                '--add-header', 'Accept-Language:en-US,en;q=0.9'
            ]

        # --- Twitter/X Configuration ---
        elif self.is_twitter:
            settings['timeout'] = 20 if fast_mode else 40
            settings['retries'] = 2 if fast_mode else 4
            settings['args'] += [
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0',
                '--add-header', 'Referer:https://x.com/',
                '--add-header', 'Accept-Language:en-US,en;q=0.9'
            ]
            if extended:
                settings['timeout'] = 55
                settings['retries'] = 6
                settings['args'] += [
                    '--add-header', 'Accept:*/*',
                    '--add-header', 'Origin:https://x.com'
                ]
            
            # Jitter for primary request
            if primary:
                pass # Jitter handled by caller usually, but could be config here

        # --- YouTube Configuration ---
        elif self.is_youtube:
            settings['timeout'] = 30
            settings['fragment_retries'] = 5 if fast_mode else 10
            settings['args'] += [
                '--retry-sleep', '3',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                '--add-header', 'Accept-Language:en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                '--add-header', 'Referer:https://www.youtube.com/'
            ]
            
            if extended:
                 settings['timeout'] = 40 if fast_mode else 60
                 settings['retries'] = 7 if fast_mode else 8
                 settings['fragment_retries'] = 8 if fast_mode else 15
                 settings['args'] += [
                     '--retry-sleep', '5',
                     '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
                     '--add-header', 'Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                     '--add-header', 'Accept-Encoding:gzip, deflate, br',
                     '--add-header', 'Cache-Control:max-age=0',
                     '--add-header', 'DNT:1',
                     '--add-header', 'Origin:https://www.youtube.com',
                     '--sleep-interval', '3', '--max-sleep-interval', '7'
                 ]

        return settings

def get_site_config(url: str) -> SiteConfig:
    return SiteConfig(url)
