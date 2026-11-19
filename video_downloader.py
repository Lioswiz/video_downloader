#!/usr/bin/env python3
"""Download a lesson you can play with your own authorized course account.

Install: python -m pip install -U playwright yt-dlp
         python -m playwright install chromium
Also install FFmpeg. Run: python download_tutorials.py
Log in in the opened browser, play ONE lesson, then return to the terminal.
Sessions/cookies are held in memory only. DRM removal is not supported.
"""
import argparse
import asyncio
import hashlib
import http.cookiejar
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_URL = 'https://learn.atfchallenge.org/path-player?courseid=building-llm-based-ai-applications&unit=6add191ead4d2db303067626Unit'


def media_kind(url, content_type):
    path = urlsplit(url).path.lower()
    if path.endswith('.m3u8') or 'mpegurl' in content_type:
        return 'HLS playlist'
    if path.endswith('.mpd') or 'dash+xml' in content_type:
        return 'DASH manifest'
    if path.endswith('.mp4') or content_type.split(';')[0] == 'video/mp4':
        if not re.search(r'(?:segment|fragment|/seg-|/chunk|init\.)', path):
            return 'MP4 (may be a fragment)'
    return None


def download(item, cookies, output, name):
    import yt_dlp
    headers = {k: v for k, v in item['headers'].items()
               if k.lower() in ('user-agent', 'referer', 'origin')}
    suffix = hashlib.sha256(item['url'].encode()).hexdigest()[:10]
    options = {
        'outtmpl': str(output / (name + '-' + suffix + '.%(ext)s')),
        'http_headers': headers,
        'format': 'bv*+ba/b',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'continuedl': True,
        'overwrites': False,
        'retries': 3,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        for c in cookies:
            domain = c['domain']
            expires = int(c['expires']) if c.get('expires', -1) > 0 else None
            ydl.cookiejar.set_cookie(http.cookiejar.Cookie(
                version=0, name=c['name'], value=c['value'],
                port=None, port_specified=False,
                domain=domain, domain_specified=domain.startswith('.'),
                domain_initial_dot=domain.startswith('.'),
                path=c['path'], path_specified=True, secure=c['secure'],
                expires=expires, discard=expires is None,
                comment=None, comment_url=None, rest={}, rfc2109=False))
        return ydl.download([item['url']])


async def main(args):
    from playwright.async_api import async_playwright
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        found = {}

        async def observe(response):
            try:
                kind = media_kind(response.url, response.headers.get('content-type', '').lower())
                if kind and response.status in (200, 206):
                    found[response.url] = {
                        'url': response.url, 'kind': kind,
                        'headers': await response.request.all_headers(),
                    }
            except Exception:
                pass  # A closed page or failed response is not a usable stream.

        context.on('response', observe)
        page = await context.new_page()
        try:
            await page.goto(args.url, wait_until='domcontentloaded', timeout=60000)
            print('\nLog in in the browser and PLAY the lesson you want.')
            while True:
                await asyncio.to_thread(input, '\nAfter playback starts, press Enter here to list streams: ')
                items = sorted(found.values(), key=lambda x: x['kind'].startswith('MP4'))
                if not items:
                    print('No supported stream found. Reload the lesson and play it again.')
                    answer = await asyncio.to_thread(input, 'Enter to retry, or q to quit: ')
                    if answer.strip().lower() == 'q':
                        break
                    continue
                for n, item in enumerate(items, 1):
                    # Hide signed query strings and tokens in the listing.
                    print(f"{n}. {item['kind']} — {urlsplit(item['url']).hostname}")
                choice = (await asyncio.to_thread(input, 'Stream number (prefer a playlist/manifest), r to rescan, q to quit: ')).strip()
                if choice.lower() == 'q':
                    break
                if choice.lower() == 'r':
                    continue
                if not choice.isdigit() or not 1 <= int(choice) <= len(items):
                    print('Please choose a listed number.')
                    continue
                name = await asyncio.to_thread(input, 'Filename/lesson title: ')
                name = re.sub(r'[^\w .-]', '_', name).strip(' .')[:100] or 'lesson'
                cookies = await context.cookies()
                try:
                    result = await asyncio.to_thread(download, items[int(choice) - 1], cookies, output, name)
                    print(f'Saved in {output}' if result == 0 else 'Download did not complete.')
                except Exception as exc:
                    print(f'Download failed ({type(exc).__name__}). Try another manifest or reload and play again.')
                    print('Some players require unsupported authentication or DRM; this tool cannot download those.')
                found.clear()
                print('To download another lesson, open it and press Play in the same browser.')
                answer = await asyncio.to_thread(input, 'Enter to continue, or q to quit: ')
                if answer.strip().lower() == 'q':
                    break
        finally:
            await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--output', default='tutorial_videos')
    args = parser.parse_args()
    if not shutil.which('ffmpeg'):
        parser.exit(1, 'Install FFmpeg first: sudo apt install ffmpeg\n')
    try:
        asyncio.run(main(args))
    except (KeyboardInterrupt, EOFError):
        print('\nStopped.')
    except ImportError:
        parser.exit(1, 'Install dependencies: python -m pip install -U playwright yt-dlp\n')
