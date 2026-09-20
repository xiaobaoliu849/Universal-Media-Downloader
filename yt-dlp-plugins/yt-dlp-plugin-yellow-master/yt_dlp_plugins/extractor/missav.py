import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError


class MissAVIE(InfoExtractor):
    IE_NAME = 'missav'
    _WORKING = True
    _IMPERSONATE = 'chrome'
    _VALID_URL = r'https?://(?:www\.)?missav[a-zA-Z0-9\-]*\.[a-z]+/(?:[a-z]{2}/)?(?P<id>[\w-]+)'
    _TESTS = [{
        'url': 'https://missav.com/en/blk-470-uncensored-leak',
        'md5': 'f1537283a9bc073c31ff86ca35d9b2a6',
        'info_dict': {
            'id': 'blk-470-uncensored-leak',
            'ext': 'mp4',
            'title': 'BLK-470 A Bitch Gal Who Seduces Her Best Friend\'s Boyfriend With A Micro Mini One Piece Dress - Eimi Fukada',
            'description': '',
            'thumbnail': r're:^https?://.*\.jpg$',

        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        if 'window._cf_chl_opt' in webpage or 'Just a moment...' in webpage or 'Enable JavaScript and cookies to continue' in webpage:
            raise ExtractorError(
                'MissAV returned a Cloudflare challenge page. Refresh MissAV site cookies or enable browser cookies, then try again',
                expected=True)

        formatted_url = self._search_regex([
            r'''var\s+hlsUrl\s*=\s*['"]([^'"]+\.m3u8[^'"]*)''',
            r'''["'](https?://[^"' ]+\.m3u8(?:\?[^"' ]*)?)["']''',
        ], webpage, 'm3u8 URL', default=None, fatal=False)

        import base64
        if not formatted_url:
            m = re.search(r'(aHR0cHM6Ly9[a-zA-Z0-9+/=]+)', webpage)
            if m:
                decoded = base64.b64decode(m.group(1) + '=' * (-len(m.group(1)) % 4)).decode('utf-8')
                formatted_url = decoded.split('|')[0]

        if not formatted_url:
            raise ExtractorError('Could not extract m3u8 URL from webpage')

        self.to_screen('URL "%s" successfully captured' % formatted_url)

        formats = self._extract_m3u8_formats(formatted_url, video_id, 'mp4', m3u8_id='hls')
        
        
        return {
            'id': video_id,
            'title': self._og_search_title(webpage),
            'description': self._og_search_description(webpage, default=''),
            'thumbnail': self._og_search_thumbnail(webpage, default=None),
            'formats': formats,
            'age_limit': 18,
        }
