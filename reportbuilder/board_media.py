"""Allow only raster images and known video embed origins in board HTML."""
import base64
import io
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from PIL import Image


def video_url(value):
    value = 'https:' + value if value.startswith('//') else value
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            return None
        if url.hostname in {'www.youtube.com', 'www.youtube-nocookie.com'}:
            return value if re.fullmatch(r'/embed/[A-Za-z0-9_-]+', url.path) else None
        if url.hostname == 'player.vimeo.com':
            return value if re.fullmatch(r'/video/[0-9]+', url.path) else None
    except ValueError:
        pass
    return None


def image_url(value):
    if value.startswith('data:'):
        match = re.fullmatch(r'data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)', value)
        if not match or len(value) > 90000:
            return None
        try:
            content = base64.b64decode(match[2], validate=True)
            with Image.open(io.BytesIO(content)) as image:
                if image.format != {'png': 'PNG', 'jpeg': 'JPEG', 'gif': 'GIF', 'webp': 'WEBP'}[match[1]]:
                    return None
                if image.width * image.height > 16000000:
                    return None
                image.verify()
            return value
        except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
            return None
    try:
        url = urlsplit(value)
        if url.scheme == 'https' and url.hostname and not url.username and not url.password:
            return value
    except ValueError:
        pass
    return None


class BoardMediaHTML(HTMLParser):
    """Normalize media after Bleach has removed unsafe tags/attributes."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.video_open = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {'img', 'iframe'}:
            src = (image_url if tag == 'img' else video_url)(values.get('src') or '')
            if not src:
                return
            values['src'] = src
            values['loading'] = 'lazy'
            values['referrerpolicy'] = 'no-referrer'
            if tag == 'iframe':
                values['sandbox'] = 'allow-scripts allow-same-origin allow-presentation'
                values['allowfullscreen'] = ''
                values['title'] = values.get('title') or '동영상'
                self.video_open = True
        text = ''.join(f' {name}="{escape(value or "", quote=True)}"' for name, value in values.items())
        self.parts.append(f'<{tag}{text}>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {'img', 'br', 'hr'}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'iframe':
            if not self.video_open:
                return
            self.video_open = False
        self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f'&{name};')

    def handle_charref(self, name):
        self.parts.append(f'&#{name};')


def normalize_board_media(value):
    parser = BoardMediaHTML()
    parser.feed(value)
    parser.close()
    return ''.join(parser.parts)
