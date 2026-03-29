#!/usr/bin/env python3
"""BubbleStone.ai — SEO Crawler v2. Deep audit with maillage interne, schema detection,
duplicate content, thin content, redirect chains, and cache-control analysis."""
import csv
import json
import os
import re
import sys
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin, urldefrag
from urllib.robotparser import RobotFileParser

import requests
import xml.etree.ElementTree as ET

USER_AGENT = 'BubbleStone-Crawler/2.0'
MAX_DEPTH = 10
MAX_PAGES = 500
TIMEOUT = 10
RATE_LIMIT = 0.25  # seconds between requests (faster for v2)
WORKERS = 6

SKIP_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp',
    '.css', '.js', '.map', '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.rar', '.gz', '.tar', '.7z',
    '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.ogg', '.wav',
    '.xml', '.json', '.rss', '.atom',
}

# Schema.org types we track
SCHEMA_TYPES_TRACKED = [
    'Organization', 'LocalBusiness', 'JobPosting', 'Article',
    'FAQPage', 'BreadcrumbList', 'Product', 'Event', 'Person',
    'WebSite', 'WebPage', 'BlogPosting', 'NewsArticle', 'HowTo',
    'Recipe', 'Review', 'Service', 'ContactPoint',
]

# Generic anchor texts to flag
GENERIC_ANCHORS = {
    # French
    'cliquez ici', 'cliquer ici', 'en savoir plus', 'lire la suite',
    'plus d\'infos', 'plus d\'informations', 'ici', 'voir plus',
    'découvrir', 'en savoir +', 'suite', 'voir', 'lien',
    # English
    'click here', 'read more', 'learn more', 'here', 'more',
    'find out more', 'see more', 'continue reading', 'link',
    'go', 'this', 'more info',
}

# Rate limiter
_rate_lock = threading.Lock()
_last_request_time = 0.0


def _rate_wait():
    global _last_request_time
    with _rate_lock:
        now = time.time()
        wait = RATE_LIMIT - (now - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.time()


def normalize_url(url, base_domain=None):
    """Normalize URL: remove fragment, consistent trailing slash, lowercase domain."""
    url = urldefrag(url)[0]
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    domain = parsed.netloc.lower()
    path = parsed.path
    # Don't add trailing slash if path has an extension
    if path and not path.endswith('/') and '.' not in path.split('/')[-1]:
        path += '/'
    url = f"{parsed.scheme}://{domain}{path}"
    if parsed.query:
        url += f"?{parsed.query}"
    return url


def is_same_domain(url, base_domain):
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc == base_domain or netloc == f'www.{base_domain}' or base_domain == f'www.{netloc}'
    except Exception:
        return False


def should_skip_url(url):
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = os.path.splitext(path)[1]
    if ext in SKIP_EXTENSIONS:
        return True
    if parsed.scheme not in ('http', 'https'):
        return True
    return False


def _extract_schema_types(html_text):
    """Extract Schema.org types from JSON-LD and microdata."""
    types_found = set()

    # JSON-LD
    for match in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                             html_text, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(match.group(1))
            _collect_schema_types(data, types_found)
        except (json.JSONDecodeError, ValueError):
            pass

    # Microdata itemtype
    for match in re.finditer(r'itemtype=["\']https?://schema\.org/(\w+)["\']',
                             html_text, re.IGNORECASE):
        types_found.add(match.group(1))

    return sorted(types_found)


def _collect_schema_types(data, types_found):
    """Recursively collect @type from JSON-LD data."""
    if isinstance(data, dict):
        t = data.get('@type')
        if t:
            if isinstance(t, list):
                types_found.update(t)
            else:
                types_found.add(t)
        # Check @graph
        for key, val in data.items():
            if isinstance(val, (dict, list)):
                _collect_schema_types(val, types_found)
    elif isinstance(data, list):
        for item in data:
            _collect_schema_types(item, types_found)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ''
        self.meta_desc = ''
        self.canonical = ''
        self.h1 = ''
        self.schema_ld = False
        self.schema_itemtype = False
        self.imgs_total = 0
        self.imgs_no_alt = 0
        self.links = []
        self.link_anchors = []  # list of {href, anchor_text}
        self.images = []  # list of image dicts with attributes
        self._tag = None
        self._in_title = False
        self._in_h1 = False
        self._h1_done = False
        self._in_script = False
        self._script_type = ''
        self._in_a = False
        self._a_href = ''
        self._a_text = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._tag = tag.lower()
        if self._tag == 'title':
            self._in_title = True
        elif self._tag == 'h1' and not self._h1_done:
            self._in_h1 = True
        elif self._tag == 'meta':
            if a.get('name', '').lower() == 'description':
                self.meta_desc = a.get('content', '')
        elif self._tag == 'link' and a.get('rel', '').lower() == 'canonical':
            self.canonical = a.get('href', '')
        elif self._tag == 'a':
            href = a.get('href', '').strip()
            if href and not href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                self.links.append(href)
                self._in_a = True
                self._a_href = href
                self._a_text = ''
        elif self._tag == 'img':
            self.imgs_total += 1
            alt = a.get('alt', '').strip()
            if not alt:
                self.imgs_no_alt += 1
            self.images.append({
                'src': a.get('src', ''),
                'alt': alt,
                'has_dimensions': bool(a.get('width') or a.get('height')),
                'loading': a.get('loading', ''),
                'has_srcset': bool(a.get('srcset', '')),
            })
        elif self._tag == 'script':
            self._in_script = True
            self._script_type = a.get('type', '').lower()
            if self._script_type == 'application/ld+json':
                self.schema_ld = True
        # itemtype on any tag
        if 'itemtype' in a:
            if 'schema.org' in a.get('itemtype', '').lower():
                self.schema_itemtype = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'title':
            self._in_title = False
        elif tag == 'h1':
            self._in_h1 = False
            self._h1_done = True
        elif tag == 'a' and self._in_a:
            self.link_anchors.append({
                'href': self._a_href,
                'anchor_text': self._a_text.strip(),
            })
            self._in_a = False
        elif tag == 'script':
            self._in_script = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_h1 and not self._h1_done:
            self.h1 += data
        if self._in_a:
            self._a_text += data


def fetch_sitemap_urls(base_url, session):
    """Fetch sitemap.xml and nested sitemaps, return set of URLs."""
    urls = set()
    sitemap_url = base_url.rstrip('/') + '/sitemap.xml'
    try:
        _rate_wait()
        r = session.get(sitemap_url, timeout=TIMEOUT)
        if r.status_code != 200:
            return urls
        _parse_sitemap(r.text, urls, session, depth=0)
    except Exception:
        pass
    return urls


def _parse_sitemap(text, urls, session, depth):
    if depth > 5:
        return
    try:
        # Remove namespace for easier parsing
        text = re.sub(r'\sxmlns="[^"]*"', '', text, count=1)
        root = ET.fromstring(text)
    except ET.ParseError:
        return

    # Sitemap index
    for elem in root.iter('sitemap'):
        loc = elem.find('loc')
        if loc is not None and loc.text:
            try:
                _rate_wait()
                r = session.get(loc.text.strip(), timeout=TIMEOUT)
                if r.status_code == 200:
                    _parse_sitemap(r.text, urls, session, depth + 1)
            except Exception:
                pass

    # URL entries
    for elem in root.iter('url'):
        loc = elem.find('loc')
        if loc is not None and loc.text:
            urls.add(loc.text.strip())


def init_robots(base_url, session):
    """Parse robots.txt and return a RobotFileParser."""
    rp = RobotFileParser()
    robots_url = base_url.rstrip('/') + '/robots.txt'
    try:
        _rate_wait()
        r = session.get(robots_url, timeout=TIMEOUT)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        else:
            rp.allow_all = True
    except Exception:
        rp.allow_all = True
    return rp


def fetch_page(url, session):
    """Fetch a page and return its data dict with v2 fields."""
    result = {
        'url': url,
        'status': None,
        'redirect_url': None,
        'redirect_chain': [],
        'title': '',
        'meta_description': '',
        'canonical': '',
        'h1': '',
        'schema': False,
        'schema_types': [],
        'word_count': 0,
        'imgs_total': 0,
        'imgs_no_alt': 0,
        'internal_links': [],
        'external_links': [],
        'internal_link_anchors': [],
        'cache_control': '',
        'error': None,
    }
    try:
        _rate_wait()
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        result['status'] = r.status_code

        # Check redirect chain
        if r.history:
            result['redirect_url'] = r.url
            result['status'] = r.history[0].status_code
            chain = []
            for resp in r.history:
                chain.append({
                    'url': resp.url,
                    'status': resp.status_code,
                })
            chain.append({'url': r.url, 'status': r.status_code})
            result['redirect_chain'] = chain

        # Cache-Control header
        result['cache_control'] = r.headers.get('Cache-Control', '')

        # Only parse HTML
        ct = r.headers.get('Content-Type', '').lower()
        if 'text/html' not in ct:
            return result

        parser = PageParser()
        try:
            parser.feed(r.text)
        except Exception:
            pass

        result['title'] = parser.title.strip()
        result['meta_description'] = parser.meta_desc.strip()
        result['canonical'] = parser.canonical.strip()
        result['h1'] = parser.h1.strip()
        result['schema'] = parser.schema_ld or parser.schema_itemtype
        result['imgs_total'] = parser.imgs_total
        result['imgs_no_alt'] = parser.imgs_no_alt
        result['images_raw'] = parser.images

        # Schema.org type detection
        result['schema_types'] = _extract_schema_types(r.text)

        # Word count from visible text
        text = re.sub(r'<script[^>]*>.*?</script>', '', r.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        words = [w for w in text.split() if len(w) > 1]
        result['word_count'] = len(words)
        result['html'] = r.text

        # Resolve links
        base_domain = urlparse(url).netloc.lower()
        for href in parser.links:
            abs_url = urljoin(r.url, href)
            abs_url = normalize_url(abs_url)
            if not abs_url:
                continue
            if is_same_domain(abs_url, base_domain):
                result['internal_links'].append(abs_url)
            else:
                result['external_links'].append(abs_url)

        # Resolve link anchors
        for la in parser.link_anchors:
            abs_url = urljoin(r.url, la['href'])
            abs_url = normalize_url(abs_url)
            if abs_url and is_same_domain(abs_url, base_domain):
                result['internal_link_anchors'].append({
                    'url': abs_url,
                    'anchor_text': la['anchor_text'],
                })

    except requests.exceptions.Timeout:
        result['error'] = 'timeout'
    except requests.exceptions.SSLError:
        result['error'] = 'ssl_error'
    except requests.exceptions.ConnectionError:
        result['error'] = 'connection_error'
    except Exception as e:
        result['error'] = str(e)[:200]

    return result


# --- Image analysis ---
_img_rate_lock = threading.Lock()
_img_last_time = 0.0
IMG_RATE_LIMIT = 0.2  # 5 per second

FORMAT_MAP = {
    '.jpg': 'jpg', '.jpeg': 'jpg', '.png': 'png', '.gif': 'gif',
    '.webp': 'webp', '.avif': 'avif', '.svg': 'svg', '.bmp': 'bmp',
    '.ico': 'ico', '.tiff': 'tiff', '.tif': 'tiff',
}

def _img_rate_wait():
    global _img_last_time
    with _img_rate_lock:
        now = time.time()
        wait = IMG_RATE_LIMIT - (now - _img_last_time)
        if wait > 0:
            time.sleep(wait)
        _img_last_time = time.time()


def _detect_format(url, content_type=''):
    """Detect image format from URL extension or Content-Type."""
    ext = os.path.splitext(urlparse(url).path)[1].lower().split('?')[0]
    if ext in FORMAT_MAP:
        return FORMAT_MAP[ext]
    # Fallback to content-type
    ct = content_type.lower()
    for fmt in ['webp', 'avif', 'png', 'gif', 'svg', 'jpeg', 'jpg', 'bmp', 'ico']:
        if fmt in ct:
            return 'jpg' if fmt == 'jpeg' else fmt
    return 'unknown'


def _get_image_size(url, session):
    """HEAD request to get image size in KB. Returns None on failure."""
    try:
        _img_rate_wait()
        r = session.head(url, timeout=5, allow_redirects=True)
        cl = r.headers.get('Content-Length')
        if cl:
            return round(int(cl) / 1024, 1)
        return None
    except Exception:
        return None


def analyze_images(pages, session):
    """Analyze images across all crawled pages. Returns (images_list, image_stats)."""
    # Collect all images, deduplicate by URL
    image_map = {}  # url -> {data}
    for page in pages:
        page_url = page.get('url', '')
        for img in page.get('images_raw', []):
            src = img.get('src', '').strip()
            if not src:
                continue
            # Resolve relative URLs
            abs_url = urljoin(page_url, src)
            abs_url = urldefrag(abs_url)[0]
            if abs_url not in image_map:
                image_map[abs_url] = {
                    'url': abs_url,
                    'alt': img.get('alt', ''),
                    'size_kb': None,
                    'format': _detect_format(abs_url),
                    'has_dimensions': img.get('has_dimensions', False),
                    'has_lazy_loading': img.get('loading', '').lower() == 'lazy',
                    'has_srcset': img.get('has_srcset', False),
                    'pages_count': 1,
                }
            else:
                image_map[abs_url]['pages_count'] += 1
                if not image_map[abs_url]['alt'] and img.get('alt'):
                    image_map[abs_url]['alt'] = img['alt']
                if img.get('has_dimensions'):
                    image_map[abs_url]['has_dimensions'] = True
                if img.get('loading', '').lower() == 'lazy':
                    image_map[abs_url]['has_lazy_loading'] = True
                if img.get('has_srcset'):
                    image_map[abs_url]['has_srcset'] = True

    # HEAD requests for sizes (cap at 200)
    urls_to_check = list(image_map.keys())[:200]
    print(f"  [crawler] Checking sizes for {len(urls_to_check)} unique images...")

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_get_image_size, u, session): u for u in urls_to_check}
        for future in as_completed(futures):
            url = futures[future]
            try:
                size = future.result()
                image_map[url]['size_kb'] = size
            except Exception:
                pass

    images_list = list(image_map.values())

    # Build stats
    total_size_kb = sum(i['size_kb'] for i in images_list if i['size_kb'] is not None)
    without_alt = [i for i in images_list if not i['alt']]
    without_lazy = [i for i in images_list if not i['has_lazy_loading']]
    without_srcset = [i for i in images_list if not i['has_srcset']]
    oversized = [i for i in images_list if i['size_kb'] is not None and i['size_kb'] > 200]
    optimized_formats = {'webp', 'avif'}
    not_webp = [i for i in images_list if i['format'] not in optimized_formats and i['format'] != 'svg']
    format_breakdown = defaultdict(int)
    for i in images_list:
        format_breakdown[i['format']] += 1

    image_stats = {
        'total_unique': len(images_list),
        'total_size_mb': round(total_size_kb / 1024, 1),
        'without_alt': len(without_alt),
        'without_lazy': len(without_lazy),
        'without_srcset': len(without_srcset),
        'oversized': sorted(oversized, key=lambda x: x['size_kb'] or 0, reverse=True),
        'not_webp': len(not_webp),
        'format_breakdown': dict(format_breakdown),
    }

    return images_list, image_stats


def _build_maillage_interne(pages, homepage_url):
    """Build internal linking (maillage interne) analysis.
    Returns a dict with per-page link stats and global summary."""

    page_urls = {p['url'] for p in pages if p.get('status') == 200}

    # Count incoming and outgoing internal links per page
    incoming = defaultdict(int)
    outgoing = defaultdict(int)
    incoming_sources = defaultdict(set)  # url -> set of pages linking to it

    for p in pages:
        if p.get('status') != 200:
            continue
        page_url = p['url']
        seen_links = set()
        for link in p.get('internal_links', []):
            if link in page_urls and link != page_url and link not in seen_links:
                seen_links.add(link)
                outgoing[page_url] += 1
                incoming[link] += 1
                incoming_sources[link].add(page_url)

    # Calculate link depth from homepage via BFS
    homepage_norm = normalize_url(homepage_url)
    depth_map = {}
    if homepage_norm:
        depth_map[homepage_norm] = 0
        queue = [homepage_norm]
        visited = {homepage_norm}
        while queue:
            current = queue.pop(0)
            current_depth = depth_map[current]
            if current_depth >= MAX_DEPTH:
                continue
            for p in pages:
                if p['url'] == current and p.get('status') == 200:
                    for link in set(p.get('internal_links', [])):
                        if link in page_urls and link not in visited:
                            visited.add(link)
                            depth_map[link] = current_depth + 1
                            queue.append(link)

    # Build per-page data
    maillage_pages = []
    for p in pages:
        if p.get('status') != 200:
            continue
        url = p['url']
        is_orphan = incoming[url] == 0 and url != homepage_norm
        maillage_pages.append({
            'url': url,
            'incoming': incoming[url],
            'outgoing': outgoing[url],
            'depth': depth_map.get(url),
            'is_orphan': is_orphan,
        })

    # Sort by incoming desc for most/least linked
    maillage_pages.sort(key=lambda x: x['incoming'], reverse=True)

    orphan_count = sum(1 for p in maillage_pages if p['is_orphan'])
    depths = [p['depth'] for p in maillage_pages if p['depth'] is not None]
    avg_depth = round(sum(depths) / len(depths), 1) if depths else 0

    # Most and least linked (top/bottom 10)
    most_linked = maillage_pages[:10]
    least_linked = [p for p in maillage_pages if not p['is_orphan']]
    least_linked.sort(key=lambda x: x['incoming'])
    least_linked = least_linked[:10]

    return {
        'pages': maillage_pages,
        'orphan_count': orphan_count,
        'avg_depth': avg_depth,
        'max_depth': max(depths) if depths else 0,
        'most_linked': most_linked,
        'least_linked': least_linked,
        'total_internal_links': sum(outgoing.values()),
    }


def _detect_duplicate_content(pages):
    """Detect pages with duplicate titles or meta descriptions."""
    # Group by title
    title_map = defaultdict(list)
    desc_map = defaultdict(list)

    for p in pages:
        if p.get('status') != 200:
            continue
        title = p.get('title', '').strip()
        desc = p.get('meta_description', '').strip()
        if title:
            title_map[title].append(p['url'])
        if desc:
            desc_map[desc].append(p['url'])

    duplicate_titles = []
    for title, urls in title_map.items():
        if len(urls) > 1:
            duplicate_titles.append({'title': title, 'urls': urls, 'count': len(urls)})
    duplicate_titles.sort(key=lambda x: x['count'], reverse=True)

    duplicate_descs = []
    for desc, urls in desc_map.items():
        if len(urls) > 1:
            duplicate_descs.append({'description': desc[:100], 'urls': urls, 'count': len(urls)})
    duplicate_descs.sort(key=lambda x: x['count'], reverse=True)

    return {
        'duplicate_titles': duplicate_titles,
        'duplicate_descriptions': duplicate_descs,
        'total_duplicate_titles': sum(d['count'] for d in duplicate_titles),
        'total_duplicate_descs': sum(d['count'] for d in duplicate_descs),
    }


def _detect_thin_content(pages, threshold=300):
    """Detect pages with fewer than `threshold` words."""
    thin = []
    for p in pages:
        if p.get('status') != 200:
            continue
        wc = p.get('word_count', 0)
        if wc < threshold:
            thin.append({
                'url': p['url'],
                'word_count': wc,
                'title': p.get('title', '')[:80],
            })
    thin.sort(key=lambda x: x['word_count'])
    return thin


def _analyze_redirect_chains(pages):
    """Analyze redirect chains, flag chains > 1 hop."""
    redirects = []
    for p in pages:
        chain = p.get('redirect_chain', [])
        if len(chain) >= 2:
            hops = len(chain) - 1
            redirects.append({
                'source': chain[0]['url'],
                'destination': chain[-1]['url'],
                'status': chain[0]['status'],
                'hops': hops,
                'chain': chain,
                'is_long_chain': hops > 1,
            })
    redirects.sort(key=lambda x: x['hops'], reverse=True)
    return redirects


def _build_schema_inventory(pages):
    """Build a site-wide Schema.org inventory."""
    # Which schema types appear on which pages
    type_pages = defaultdict(list)  # type -> [urls]
    pages_with_schema = 0
    pages_without_schema = 0

    for p in pages:
        if p.get('status') != 200:
            continue
        types = p.get('schema_types', [])
        if types:
            pages_with_schema += 1
            for t in types:
                type_pages[t].append(p['url'])
        else:
            pages_without_schema += 1

    # Checklist of important types
    checklist = {}
    for st in SCHEMA_TYPES_TRACKED:
        urls = type_pages.get(st, [])
        checklist[st] = {
            'present': len(urls) > 0,
            'count': len(urls),
            'pages': urls[:5],  # cap at 5 for JSON size
        }

    return {
        'type_pages': {k: {'count': len(v), 'pages': v[:5]} for k, v in type_pages.items()},
        'checklist': checklist,
        'pages_with_schema': pages_with_schema,
        'pages_without_schema': pages_without_schema,
        'all_types_found': sorted(type_pages.keys()),
    }


def _analyze_anchor_texts(pages):
    """Analyze internal link anchor texts. Flag generic/empty anchors."""
    total_anchors = 0
    generic_count = 0
    empty_count = 0
    generic_examples = []

    for p in pages:
        if p.get('status') != 200:
            continue
        source = p['url']
        for la in p.get('internal_link_anchors', []):
            anchor = la.get('anchor_text', '').strip()
            total_anchors += 1
            if not anchor:
                empty_count += 1
            elif anchor.lower() in GENERIC_ANCHORS:
                generic_count += 1
                if len(generic_examples) < 20:
                    generic_examples.append({
                        'source': source,
                        'target': la['url'],
                        'anchor_text': anchor,
                    })

    descriptive_count = total_anchors - generic_count - empty_count
    ratio_generic = round(generic_count / max(total_anchors, 1) * 100)
    ratio_empty = round(empty_count / max(total_anchors, 1) * 100)

    return {
        'total_anchors': total_anchors,
        'generic_count': generic_count,
        'empty_count': empty_count,
        'descriptive_count': descriptive_count,
        'ratio_generic_pct': ratio_generic,
        'ratio_empty_pct': ratio_empty,
        'generic_examples': generic_examples,
    }


def crawl_site(url, output_dir):
    """Main crawl function. Returns a results dict with v2 deep analysis."""
    parsed = urlparse(url)
    base_domain = parsed.netloc.lower()
    base_url = f"{parsed.scheme}://{base_domain}"

    sess = requests.Session()
    sess.headers.update({'User-Agent': USER_AGENT})
    sess.verify = True
    sess.max_redirects = 10

    print(f"  [crawler] Initializing for {base_domain} (v2 — max {MAX_PAGES} pages)")

    # Robots.txt
    robots = init_robots(base_url, sess)

    # Sitemap URLs
    print(f"  [crawler] Fetching sitemap...")
    sitemap_urls = fetch_sitemap_urls(base_url, sess)
    print(f"  [crawler] Sitemap: {len(sitemap_urls)} URLs")

    # Spider from homepage
    print(f"  [crawler] Spidering from homepage...")
    discovered = set()
    to_visit = [(url, 0)]  # (url, depth)
    visited_spider = set()

    while to_visit and len(discovered) < MAX_PAGES:
        current_url, depth = to_visit.pop(0)
        norm = normalize_url(current_url)
        if not norm or norm in visited_spider:
            continue
        if not is_same_domain(norm, base_domain):
            continue
        if should_skip_url(norm):
            continue
        if not robots.can_fetch(USER_AGENT, norm):
            continue
        visited_spider.add(norm)
        discovered.add(norm)

        if depth >= MAX_DEPTH:
            continue

        try:
            _rate_wait()
            r = sess.get(norm, timeout=TIMEOUT)
            ct = r.headers.get('Content-Type', '').lower()
            if 'text/html' not in ct:
                continue
            parser = PageParser()
            parser.feed(r.text)
            for href in parser.links:
                abs_url = urljoin(r.url, href)
                abs_url = normalize_url(abs_url)
                if abs_url and is_same_domain(abs_url, base_domain) and abs_url not in visited_spider and not should_skip_url(abs_url):
                    to_visit.append((abs_url, depth + 1))
        except Exception:
            pass

        if len(discovered) % 50 == 0:
            print(f"  [crawler] Discovered {len(discovered)} URLs so far...")

    # Combine sitemap + spider URLs
    all_urls = set()
    for u in sitemap_urls:
        norm = normalize_url(u)
        if norm and is_same_domain(norm, base_domain) and not should_skip_url(norm):
            all_urls.add(norm)
    all_urls.update(discovered)

    # Filter by robots
    all_urls = {u for u in all_urls if robots.can_fetch(USER_AGENT, u)}

    # Cap at MAX_PAGES
    all_urls = list(all_urls)[:MAX_PAGES]
    print(f"  [crawler] Total unique URLs to fetch: {len(all_urls)}")

    # Fetch all pages
    pages = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_page, u, sess): u for u in all_urls}
        done_count = 0
        for future in as_completed(futures):
            try:
                page = future.result()
                pages.append(page)
            except Exception as e:
                pages.append({'url': futures[future], 'status': None, 'error': str(e)})
            done_count += 1
            if done_count % 25 == 0:
                print(f"  [crawler] Fetched {done_count}/{len(all_urls)} pages")

    print(f"  [crawler] Fetched all {len(pages)} pages. Analyzing...")

    # Build link graph for orphan detection
    sitemap_normalized = set()
    for u in sitemap_urls:
        n = normalize_url(u)
        if n:
            sitemap_normalized.add(n)

    linked_urls = set()
    for p in pages:
        for link in p.get('internal_links', []):
            linked_urls.add(link)

    # Status counts
    status_counts = defaultdict(int)
    for p in pages:
        s = str(p.get('status', 'error'))
        status_counts[s] += 1

    # Broken links (internal links pointing to 404)
    page_status = {p['url']: p.get('status') for p in pages}
    broken_links = []
    for p in pages:
        for link in p.get('internal_links', []):
            if page_status.get(link) in (404, 410):
                broken_links.append({'source': p['url'], 'broken_url': link, 'status': page_status[link]})

    # Orphan pages (in sitemap but no internal link)
    orphan_pages = [u for u in sitemap_normalized if u in {p['url'] for p in pages} and u not in linked_urls]

    # Legacy redirect chains (kept for backward compat)
    redirect_chains = []
    for p in pages:
        if p.get('redirect_url') and p.get('redirect_url') != p['url']:
            redirect_chains.append({
                'source': p['url'],
                'destination': p['redirect_url'],
                'status': p.get('status')
            })

    # Missing SEO elements
    missing_title = [p['url'] for p in pages if not p.get('title') and p.get('status') == 200]
    missing_meta_desc = [p['url'] for p in pages if not p.get('meta_description') and p.get('status') == 200]
    missing_h1 = [p['url'] for p in pages if not p.get('h1') and p.get('status') == 200]
    missing_canonical = [p['url'] for p in pages if not p.get('canonical') and p.get('status') == 200]

    # Image analysis
    print(f"  [crawler] Analyzing images...")
    images_list, image_stats = analyze_images(pages, sess)
    print(f"  [crawler] Found {image_stats['total_unique']} unique images ({image_stats['total_size_mb']} MB)")

    # --- V2: Deep analysis ---
    print(f"  [crawler] Building maillage interne (internal linking)...")
    maillage = _build_maillage_interne(pages, url)
    print(f"  [crawler] Maillage: {maillage['orphan_count']} orphans, avg depth {maillage['avg_depth']}")

    print(f"  [crawler] Detecting duplicate content...")
    duplicates = _detect_duplicate_content(pages)
    print(f"  [crawler] Duplicates: {len(duplicates['duplicate_titles'])} title groups, {len(duplicates['duplicate_descriptions'])} desc groups")

    print(f"  [crawler] Detecting thin content (<300 words)...")
    thin_content = _detect_thin_content(pages)
    print(f"  [crawler] Thin content: {len(thin_content)} pages")

    print(f"  [crawler] Analyzing redirect chains...")
    redirect_analysis = _analyze_redirect_chains(pages)
    long_chains = [r for r in redirect_analysis if r['is_long_chain']]
    print(f"  [crawler] Redirects: {len(redirect_analysis)} total, {len(long_chains)} chains > 1 hop")

    print(f"  [crawler] Building Schema.org inventory...")
    schema_inventory = _build_schema_inventory(pages)
    print(f"  [crawler] Schema: {len(schema_inventory['all_types_found'])} types across {schema_inventory['pages_with_schema']} pages")

    print(f"  [crawler] Analyzing anchor texts...")
    anchor_analysis = _analyze_anchor_texts(pages)
    print(f"  [crawler] Anchors: {anchor_analysis['total_anchors']} total, {anchor_analysis['generic_count']} generic ({anchor_analysis['ratio_generic_pct']}%)")

    # Clean heavy fields from pages to reduce JSON size
    for p in pages:
        p.pop('images_raw', None)
        p.pop('html', None)
        p.pop('internal_link_anchors', None)
        # Keep redirect_chain for redirect analysis but cap it
        chain = p.get('redirect_chain', [])
        if len(chain) > 5:
            p['redirect_chain'] = chain[:5]

    results = {
        'total_pages': len(pages),
        'status_counts': dict(status_counts),
        'pages': pages,
        'broken_links': broken_links,
        'orphan_pages': orphan_pages,
        'redirect_chains': redirect_chains,
        'missing_title': missing_title,
        'missing_meta_desc': missing_meta_desc,
        'missing_h1': missing_h1,
        'missing_canonical': missing_canonical,
        'images': images_list,
        'image_stats': image_stats,
        # V2 fields
        'maillage': maillage,
        'duplicates': duplicates,
        'thin_content': thin_content,
        'redirect_analysis': redirect_analysis,
        'schema_inventory': schema_inventory,
        'anchor_analysis': anchor_analysis,
    }

    # Export
    os.makedirs(output_dir, exist_ok=True)
    domain_clean = base_domain.replace('www.', '').replace('.', '_')

    # JSON
    json_path = os.path.join(output_dir, f'crawl_{domain_clean}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # CSV (UTF-8 BOM, semicolon separator for French Excel) — enhanced with v2 columns
    csv_path = os.path.join(output_dir, f'mapping_{domain_clean}.csv')
    # Build lookup for maillage data
    maillage_lookup = {m['url']: m for m in maillage.get('pages', [])}
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['url_actuelle', 'status_http', 'title', 'meta_description', 'canonical',
                         'h1', 'schema', 'schema_types', 'mots', 'liens_entrants', 'liens_sortants',
                         'profondeur', 'orpheline', 'cache_control', 'nouvelle_url'])
        for p in sorted(pages, key=lambda x: x.get('url', '')):
            m = maillage_lookup.get(p.get('url', ''), {})
            writer.writerow([
                p.get('url', ''),
                p.get('status', ''),
                p.get('title', ''),
                p.get('meta_description', ''),
                p.get('canonical', ''),
                p.get('h1', ''),
                'Oui' if p.get('schema') else 'Non',
                ', '.join(p.get('schema_types', [])),
                p.get('word_count', 0),
                m.get('incoming', 0),
                m.get('outgoing', 0),
                m.get('depth', ''),
                'Oui' if m.get('is_orphan') else 'Non',
                p.get('cache_control', ''),
                '',  # nouvelle_url vide par défaut
            ])

    # Summary
    ok_count = status_counts.get('200', 0)
    redir_count = status_counts.get('301', 0) + status_counts.get('302', 0)
    err_count = status_counts.get('404', 0) + status_counts.get('500', 0)
    print(f"  [crawler] Done! {len(pages)} pages | {ok_count} OK | {redir_count} redirects | {err_count} errors | {maillage['orphan_count']} orphans")
    print(f"  [crawler] JSON: {json_path}")
    print(f"  [crawler] CSV:  {csv_path}")

    return results


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 crawler.py <url> [output_dir]")
        sys.exit(1)
    target_url = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else '/output'
    crawl_site(target_url, out_dir)
