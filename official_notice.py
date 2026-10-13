"""Read-only, inert snapshots of public notice pages (no portal interaction)."""
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import re
from urllib.error import HTTPError, URLError


MAX_HTML_BYTES = 2_000_000


class OfficialNoticeError(ValueError):
    """A public page cannot be presented as this notice's details."""


ALLOWED_TAGS = frozenset({
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'section', 'article',
    'strong', 'b', 'em', 'i', 'u', 's', 'small', 'span', 'sub', 'sup',
    'br', 'hr', 'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'blockquote', 'pre', 'code',
    'table', 'caption', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
})
DROP_TAGS = frozenset({
    'head', 'script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed',
    'svg', 'math', 'template', 'noscript', 'canvas', 'audio', 'video',
    'nav', 'header', 'footer', 'aside', 'button', 'select', 'textarea', 'datalist',
})
VOID_TAGS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
    'param', 'source', 'track', 'wbr',
})
CHROME_NAMES = frozenset({
    'nav', 'navbar', 'navigation', 'menu', 'menubar', 'sidebar', 'footer',
    'site-header', 'site-footer', 'site-navigation', 'breadcrumb', 'breadcrumbs',
})
CONTENT_NAMES = frozenset({'page_content', 'page-content', 'main-content', 'maincontent'})


class SnapshotParser(HTMLParser):
    """Build fresh safe elements; never serialize original source markup."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'source': '', 'tag': '', 'attrs': '', 'children': [], 'drop': False}
        self.stack = [self.root]
        self.regions = []
        self.nodes = 0

    def handle_starttag(self, tag, attributes):
        self.nodes += 1
        if self.nodes > 50_000 or len(self.stack) > 128:
            raise OfficialNoticeError('The official page is too complex to preview safely.')
        attrs = dict(attributes)
        names = set((attrs.get('class') or '').lower().split())
        names.add((attrs.get('id') or '').lower())
        hidden = 'hidden' in attrs or attrs.get('aria-hidden', '').lower() == 'true'
        hidden = hidden or bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style') or '', re.I))
        dropped = self.stack[-1]['drop'] or tag in DROP_TAGS or hidden
        dropped = dropped or bool(names & CHROME_NAMES) or attrs.get('role') in ('navigation', 'banner', 'contentinfo')
        kept = tag if tag in ALLOWED_TAGS and not dropped else ''
        safe_attrs = []
        if kept in ('td', 'th'):
            for name in ('colspan', 'rowspan'):
                value = attrs.get(name) or ''
                if len(value) <= 3 and value.isascii() and value.isdigit() and 1 <= int(value) <= 100:
                    safe_attrs.append(f' {name}="{int(value)}"')
        node = {'source': tag, 'tag': kept, 'attrs': ''.join(safe_attrs), 'children': [], 'drop': dropped}
        self.stack[-1]['children'].append(node)
        if not dropped and (names & CONTENT_NAMES or tag == 'main' or attrs.get('role') == 'main'):
            self.regions.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]['source'] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not self.stack[-1]['drop']:
            self.stack[-1]['children'].append(data)

    def render(self, node, text_only=False, unwrap=False):
        if isinstance(node, str):
            return node if text_only else escape(node, quote=True)
        if node['drop']:
            return ''
        inner = ''.join(self.render(child, text_only) for child in node['children'])
        if text_only:
            return ' ' + inner + ' '
        tag = node['tag']
        if unwrap or not tag:
            return inner
        if tag in ('br', 'hr'):
            return f'<{tag}>'
        if not inner.strip():
            return ''
        return f'<{tag}{node["attrs"]}>{inner}</{tag}>'


def sanitize_html(source):
    """Return sanitized content and plain text used to identify portal errors."""
    parser = SnapshotParser()
    parser.feed(source)
    parser.close()
    # GePNIC wraps its actual tables in a form. Keep form contents, never controls.
    # Prefer its content cells to the surrounding portal logo/menu/layout tables.
    regions = parser.regions or [parser.root]
    region_ids = {id(node) for node in regions}
    # Avoid rendering a nested main/page_content region twice.
    selected = []
    def choose(node, inside=False):
        if isinstance(node, str) or node['drop']:
            return
        is_region = id(node) in region_ids
        if is_region and not inside:
            selected.append(node)
        for child in node['children']:
            choose(child, inside or is_region)
    choose(parser.root)
    html = ''.join(parser.render(node, unwrap=True) for node in selected).strip()
    text = re.sub(r'\s+', ' ', parser.render(parser.root, text_only=True)).strip()
    visible = re.sub(r'\s+', ' ', ' '.join(parser.render(node, text_only=True) for node in selected)).strip()
    if len(html.encode('utf-8')) > MAX_HTML_BYTES:
        raise OfficialNoticeError('The official page is too large for an in-app preview.')
    return html, text, visible


def validate_notice_content(text, visible, notice):
    lowered = text.lower()
    if re.search(r'session (?:has )?(?:timed out|expired)|session timeout|invalid (?:session|direct link)|link (?:has )?expired', lowered):
        raise OfficialNoticeError('This official notice link has expired. Refresh the tender feed and try again.')
    if re.search(r'access denied|request (?:was )?(?:rejected|blocked)|\b403 forbidden\b|temporarily unavailable|page (?:not found|cannot be found)|\b404 not found\b', lowered):
        raise OfficialNoticeError('The official portal is blocking or cannot serve this notice right now. Try again later.')
    if re.search(r'verify (?:that )?you are (?:a )?human|(?:enter|complete|solve) (?:the )?captcha|enable javascript and cookies', lowered):
        raise OfficialNoticeError('The official portal requires an interactive verification. Its protected page cannot be previewed here.')
    details = visible.lower()
    labels = ('tender id', 'tender reference number', 'organisation chain', 'bid number', 'bid end date', 'corrigendum title')
    detail_count = sum(label in details for label in labels)
    compact = lambda value: re.sub(r'[^a-z0-9]+', '', str(value).lower())
    reference = compact(notice.get('reference') or '')
    title = compact(notice.get('title') or '')
    reference_matches = len(reference) >= 4 and reference in compact(visible)
    same_notice = reference_matches or (len(title) >= 12 and title in compact(visible))
    detail_heading = any(label in details for label in ('tender details', 'corrigendum details', 'bid details', 'notice details'))
    if len(visible) < 50 or not (detail_count >= 2 or (detail_heading and same_notice)):
        if re.search(r'(?:sign|log)\s*in|username|password|captcha', lowered):
            raise OfficialNoticeError('The official portal requires a login or verification before it can show this notice.')
        raise OfficialNoticeError('The portal returned a general page instead of notice details. Refresh the tender feed and try again.')
    # Strong identifiers prevent an expired direct link from displaying another tender.
    if len(reference) >= 8 and not reference_matches:
        raise OfficialNoticeError('The portal response could not be matched to this notice. Refresh the tender feed and try again.')


def fetch_official_notice(notice, client, allowed_url):
    """Fetch only a stored notice URL through the application's safe HTTP client."""
    url = notice.get('url') or ''
    try:
        if not allowed_url(url):
            raise OfficialNoticeError('This notice does not have a supported official portal URL.')
        body, final_url = client.binary(url, max_bytes=MAX_HTML_BYTES, pdf_header_only=True)
        if not allowed_url(final_url):
            raise OfficialNoticeError('The portal redirected outside the supported official sources.')
    except OfficialNoticeError:
        raise
    except HTTPError as error:
        if error.code in (401, 403, 429):
            raise OfficialNoticeError('The official portal requires verification or is blocking this request. Try again later.') from error
        if error.code in (404, 410):
            raise OfficialNoticeError('The official notice is no longer available at this address. Refresh the tender feed and try again.') from error
        raise OfficialNoticeError('The official portal could not serve this notice. Try again later.') from error
    except (TimeoutError, URLError, OSError) as error:
        raise OfficialNoticeError('The official portal did not respond in time. Try again later.') from error
    except ValueError as error:
        raise OfficialNoticeError('The official response exceeded the preview limit or redirected to an unsupported address.') from error
    fetched = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if body.startswith(b'%PDF-'):
        return {'kind': 'pdf', 'source_url': final_url, 'fetched': fetched}
    html, text, visible = sanitize_html(body.decode('utf-8', errors='replace'))
    validate_notice_content(text, visible, notice)
    return {'kind': 'html', 'html': html, 'source_url': final_url, 'fetched': fetched}
