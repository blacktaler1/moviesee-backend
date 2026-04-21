"""
Video URL Extractor Service

yt-dlp orqali YouTube, uzmovi.tv va boshqa saytlardan
to'g'ridan-to'g'ri stream URL ni chiqarib oladi.

IP-lock muammosi hal etilgan: backend proxy orqali streaming.
Anti-bot himoya: curl_cffi + Chrome impersonation.
"""
import asyncio
import time
import logging
import shutil
import urllib.parse
from typing import Optional
from dataclasses import dataclass, field

# curl_cffi — Chrome impersonation uchun (anti-bot saytlar)
try:
    from curl_cffi import requests as _cffi_requests  # type: ignore
    _CFFI_AVAILABLE = True
except ImportError:
    _CFFI_AVAILABLE = False

# yt-dlp impersonation target
try:
    from yt_dlp.networking.impersonate import ImpersonateTarget as _ImpersonateTarget  # type: ignore
    _YDL_IMPERSONATE = _ImpersonateTarget(client="chrome")
except Exception:
    _YDL_IMPERSONATE = None

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    stream_url: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None  # soniyalarda
    headers: dict = field(default_factory=dict)
    needs_proxy: bool = False  # True bo'lsa backend proxy ishlatish kerak


# In-memory cache: original_url -> (VideoInfo, timestamp)
_cache: dict[str, tuple[VideoInfo, float]] = {}
CACHE_TTL = 7200  # 2 soat


def _clean_url(url: str) -> str:
    """
    URL ni tozalaydi:
    - Bo'shliqlarni %20 ga almashtiradi
    - Unicode harflarni encode qiladi
    - Boshqa xavfli belgilarni saqlaydi
    """
    url = url.strip()
    # Allaqachon encode qilingan bo'lsa — qayta encode qilmaymiz
    try:
        parsed = urllib.parse.urlparse(url)
        # Path qismidagi bo'shliq va unicode belgilarni encode qilamiz
        clean_path = urllib.parse.quote(parsed.path, safe="/:@!$&'()*+,;=")
        clean_query = urllib.parse.quote(parsed.query, safe="=&+%")
        cleaned = urllib.parse.urlunparse(parsed._replace(path=clean_path, query=clean_query))
        return cleaned
    except Exception:
        return url


async def extract_video_url(page_url: str) -> VideoInfo:
    """
    Berilgan sahifa URL'dan video stream URL ni chiqarib oladi.
    YouTube, uzmovi.tv va yt-dlp qo'llab-quvvatlovchi ko'plab saytlar bilan ishlaydi.
    """
    page_url = _clean_url(page_url)
    logger.info(f"[VideoExtractor] URL: {page_url}")

    # To'g'ridan-to'g'ri media fayl bo'lsa — chiqarib olish shart emas
    if _is_direct_media(page_url):
        logger.info(f"[VideoExtractor] To'g'ridan-to'g'ri media URL")
        return VideoInfo(stream_url=page_url, title="Video", needs_proxy=False)

    # Cache'dan tekshirish
    cached = _cache.get(page_url)
    if cached:
        info, ts = cached
        if time.time() - ts < CACHE_TTL:
            logger.info(f"[VideoExtractor] Cache'dan qaytarildi: {info.stream_url[:60]}...")
            return info

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _extract_sync, page_url)
        _cache[page_url] = (result, time.time())
        logger.info(
            f"[VideoExtractor] ✅ Muvaffaqiyatli! "
            f"title='{result.title}', url={result.stream_url[:80]}..."
        )
        return result
    except Exception as e:
        logger.error(f"[VideoExtractor] ❌ XATO: {e}", exc_info=True)
        raise RuntimeError(f"Video URL chiqarib bo'lmadi: {str(e)}")


def _is_direct_media(url: str) -> bool:
    """URL to'g'ridan-to'g'ri media fayl ekanligini tekshiradi."""
    lower = url.lower().split("?")[0]
    return any(lower.endswith(ext) for ext in (
        ".mp4", ".mkv", ".avi", ".mov", ".webm",
        ".m3u8", ".mpd", ".ts", ".flv", ".ogv"
    ))


def _get_ydl_opts() -> dict:
    """yt-dlp parametrlarini qaytaradi."""
    opts: dict = {
        "quiet": True,
        "no_warnings": False,
        "noplaylist": True,
        "extract_flat": False,
        "skip_download": True,
        "no_check_certificate": True,
        # Direct MP4 formatni afzal ko'ramiz (HLS emas) — proxy uchun soddaroq
        "format": (
            "best[ext=mp4][protocol=https][height<=720]"
            "/best[ext=mp4][height<=720]"
            "/best[ext=mp4]"
            "/18"          # YouTube 360p direct MP4 (fallback)
            "/best"
        ),
    }

    # Chrome impersonation — anti-bot saytlar uchun
    if _YDL_IMPERSONATE is not None:
        opts["impersonate"] = _YDL_IMPERSONATE
        logger.info("[VideoExtractor] Chrome impersonation yoqildi")

    # Node.js runtime uchun yo'l (yt-dlp n-challenge hal qilish uchun kerak)
    node_path = shutil.which("node") or shutil.which("node.exe")
    if not node_path:
        import os
        candidate = r"C:\Program Files\nodejs\node.exe"
        if os.path.exists(candidate):
            node_path = candidate

    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}
        opts["remote_components"] = {"ejs:github"}  # n-challenge solver
        logger.info(f"[VideoExtractor] Node.js topildi: {node_path}")
    else:
        logger.warning("[VideoExtractor] Node.js topilmadi — ba'zi YouTube formatlari mavjud bo'lmasligi mumkin")

    # Firefox cookie'lari (YouTube bot detection'dan o'tish uchun)
    try:
        import browser_cookie3  # noqa — mavjudligini tekshiramiz
        opts["cookiesfrombrowser"] = ("firefox",)
        logger.info("[VideoExtractor] Firefox cookie'lari ishlatiladi")
    except ImportError:
        opts["cookiesfrombrowser"] = ("firefox",)
        logger.info("[VideoExtractor] Firefox cookie'lari sinab ko'riladi")

    return opts


def _extract_sync(page_url: str) -> VideoInfo:
    """yt-dlp ni sinxron chaqiradi (executor ichida ishlaydi)."""
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        raise RuntimeError("yt-dlp o'rnatilmagan. `pip install yt-dlp` ni bajaring.")

    ydl_opts = _get_ydl_opts()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
    except Exception as e:
        err_str = str(e)
        # Firefox cookie'larsiz qayta urinib ko'ramiz
        if "firefox" in err_str.lower() or "cookie" in err_str.lower() or "dpapi" in err_str.lower():
            logger.warning(f"[VideoExtractor] Firefox cookie xatosi, cookie'larsiz urinib ko'rilmoqda: {e}")
            opts_no_cookies = {k: v for k, v in ydl_opts.items() if k != "cookiesfrombrowser"}
            with yt_dlp.YoutubeDL(opts_no_cookies) as ydl2:
                info = ydl2.extract_info(page_url, download=False)
        else:
            raise

    if not info:
        raise ValueError("yt-dlp hech narsa topa olmadi")

    logger.info(
        f"[VideoExtractor:sync] info olindi: "
        f"type={info.get('_type')}, title={info.get('title')}, "
        f"extractor={info.get('extractor')}, formats={len(info.get('formats', []))}"
    )

    # Playlist bo'lsa, birinchi entry ni olamiz
    if info.get("_type") == "playlist":
        entries = info.get("entries", [])
        if not entries:
            raise ValueError("Playlist bo'sh")
        info = entries[0]
        if isinstance(info, dict) and info.get("ie_key") and "url" in info:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(info["url"], download=False)

    # Stream URL ni topamiz
    stream_url, http_headers = _pick_best_stream(info)

    # IP-lock tekshiruvi: URL'da IP mavjud bo'lsa proxy kerak
    needs_proxy = _url_needs_proxy(stream_url)
    logger.info(f"[VideoExtractor:sync] needs_proxy={needs_proxy}, url={stream_url[:100]}...")

    return VideoInfo(
        stream_url=stream_url,
        title=info.get("title", "Video") or "Video",
        thumbnail=info.get("thumbnail"),
        duration=info.get("duration"),
        headers=http_headers,
        needs_proxy=needs_proxy,
    )


def _url_needs_proxy(url: str) -> bool:
    """URL IP-locked ekanligini aniqlaydi (proxy kerak)."""
    # YouTube CDN URL'lari har doim proxy kerak
    if "googlevideo.com" in url or "manifest.googlevideo.com" in url:
        return True
    # Boshqa IP-locked CDN'lar
    if "/ip/" in url and "googlevideo" in url:
        return True
    return False


def _pick_best_stream(info: dict) -> tuple[str, dict]:
    """Video ma'lumotlaridan eng yaxshi stream URL ni tanlaydi."""
    formats = info.get("formats", [])
    logger.info(f"[VideoExtractor:pick] {len(formats)} ta format mavjud")

    def get_headers(fmt: dict) -> dict:
        headers = {}
        http_headers = fmt.get("http_headers", {})
        if http_headers:
            # Faqat kerakli headerlarni olamiz
            for key in ("User-Agent", "Accept", "Accept-Language", "Referer"):
                if key in http_headers:
                    headers[key] = http_headers[key]
        return headers

    if formats:
        # 1. Birlashgan MP4 (video+audio, HTTPS) — eng qulay, HLS emas
        merged_mp4 = [
            f for f in formats
            if f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
            and f.get("ext") == "mp4"
            and f.get("protocol") in ("https", "http")
            and f.get("url")
        ]
        if merged_mp4:
            best = max(merged_mp4, key=lambda f: f.get("height") or 0)
            logger.info(f"[pick] ✅ Birlashgan MP4 HTTPS: height={best.get('height')}")
            return best["url"], get_headers(best)

        # 2. Birlashgan istalgan format (HTTPS)
        merged_https = [
            f for f in formats
            if f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
            and f.get("protocol") in ("https", "http")
            and f.get("url")
        ]
        if merged_https:
            best = max(merged_https, key=lambda f: f.get("height") or 0)
            logger.info(f"[pick] ✅ Birlashgan HTTPS: height={best.get('height')}, ext={best.get('ext')}")
            return best["url"], get_headers(best)

        # 3. Birlashgan istalgan format (HLS ham)
        merged_any = [
            f for f in formats
            if f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
            and f.get("url")
        ]
        if merged_any:
            best = max(merged_any, key=lambda f: f.get("height") or 0)
            logger.info(f"[pick] ✅ Birlashgan (HLS): height={best.get('height')}")
            return best["url"], get_headers(best)

        # 4. HLS stream (oxirgi chora)
        hls = [f for f in formats if f.get("protocol") in ("m3u8", "m3u8_native") and f.get("url")]
        if hls:
            best_hls = max(hls, key=lambda f: f.get("height") or 0)
            logger.info(f"[pick] ✅ HLS: height={best_hls.get('height')}")
            return best_hls["url"], get_headers(best_hls)

        # 5. Birinchi URL
        first = formats[0]
        if first.get("url"):
            logger.info(f"[pick] ✅ Birinchi format: ext={first.get('ext')}")
            return first["url"], get_headers(first)

    # To'g'ridan-to'g'ri URL
    direct = info.get("url")
    if direct:
        logger.info(f"[pick] ✅ To'g'ridan-to'g'ri URL")
        return direct, info.get("http_headers") or {}

    raise ValueError(f"Stream URL topilmadi. Formatlar: {[f.get('ext') for f in formats[:5]]}")


def invalidate_cache(url: str) -> None:
    """Cache'dan URL ni o'chiradi."""
    _cache.pop(url, None)


# ── Video Options (saytdagi barcha video variantlari) ────────────

@dataclass
class VideoOption:
    """Sahifadagi bitta video varianti."""
    title: str
    source_url: str       # yt-dlp ga beriladigan URL (YouTube, jwplayer, ...)
    thumbnail: Optional[str] = None
    duration: Optional[int] = None  # soniyalarda


async def extract_video_options(page_url: str) -> list[VideoOption]:
    """
    Sahifadagi BARCHA video variantlarini qaytaradi (stream URL chiqarmasdan).
    Strategiya:
      1. HTML scraping — barcha iframe/video/jwplayer manbalarini topadi (tez)
      2. Agar 2+ topilsa — qaytaramiz
      3. 0-1 topilsa — yt-dlp flat extraction bilan qo'shib qaytaramiz
    """
    page_url = _clean_url(page_url)
    logger.info(f"[VideoExtractor/options] URL: {page_url}")

    if _is_direct_media(page_url):
        logger.info("[VideoExtractor/options] To'g'ridan-to'g'ri media, bitta variant")
        return [VideoOption(title="Video", source_url=page_url)]

    loop = asyncio.get_event_loop()

    # Strategiya 1: HTML scraping
    scraped: list[VideoOption] = []
    try:
        scraped = await loop.run_in_executor(None, _scrape_video_sources_sync, page_url)
        logger.info(f"[VideoExtractor/options] HTML scraping: {len(scraped)} variant — {[o.title for o in scraped]}")
    except Exception as e:
        logger.warning(f"[VideoExtractor/options] Scraping xatosi: {e}")

    if len(scraped) >= 2:
        return scraped

    # Strategiya 2: yt-dlp flat extraction
    ydl_opts: list[VideoOption] = []
    try:
        ydl_opts = await loop.run_in_executor(None, _extract_options_ydl_sync, page_url)
        logger.info(f"[VideoExtractor/options] yt-dlp flat: {len(ydl_opts)} variant — {[o.title for o in ydl_opts]}")
    except Exception as e:
        logger.warning(f"[VideoExtractor/options] yt-dlp flat xatosi: {e}")

    # Ikkalasini birlashtirish (dublikatlar va original URL ni olib tashlash)
    combined = _merge_options(scraped, ydl_opts, page_url=page_url)
    if combined:
        return combined

    # So'nggi fallback — sahifaning o'zini extract-url ga bering
    return [VideoOption(title="Video", source_url=page_url)]


def _scrape_video_sources_sync(page_url: str) -> list[VideoOption]:
    """
    Sahifa HTML'ini yuklab, barcha video manbalarini (iframe, video, jwplayer) topadi.
    curl_cffi (Chrome impersonation) bilan anti-bot himoyasini chetlab o'tadi.
    """
    import re
    page_url = _clean_url(page_url)

    if _CFFI_AVAILABLE:
        # Chrome impersonation — Cloudflare va boshqa bot himoyalarini chetlab o'tadi
        resp = _cffi_requests.get(page_url, impersonate="chrome", timeout=15, allow_redirects=True)
        html = resp.text
    else:
        try:
            import httpx as _httpx
        except ImportError:
            raise RuntimeError("curl_cffi yoki httpx o'rnatilmagan")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
                "Gecko/20100101 Firefox/124.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with _httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(page_url)
            html = resp.text

    options: list[VideoOption] = []
    seen: set[str] = set()
    # Sahifaning o'zi qaytarilmasin (infinite loop)
    page_url_key = page_url.split("?")[0].rstrip("/")

    def _quality_label(url: str, base_title: str) -> str:
        """URL'dan sifat yorlig'ini topadi (480p, 720p, 1080p)."""
        low = url.lower()
        for q in ("2160p", "1080p", "720p", "480p", "360p", "240p"):
            if q in low:
                return f"{base_title} {q}"
        return base_title

    def add(url: str, title: str, thumbnail: str | None = None, duration: int | None = None) -> None:
        url = url.strip()
        if not url:
            return
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            return
        url = _clean_url(url)  # Bo'shliq va unicode belgilarni encode qilish
        key = url.split("?")[0].rstrip("/")
        if key in seen or key == page_url_key:
            return
        seen.add(key)
        # Sifat yorlig'ini URL'dan topamiz
        smart_title = _quality_label(url, title)
        options.append(VideoOption(title=smart_title, source_url=url, thumbnail=thumbnail, duration=duration))

    # ── 1. YouTube embeds ──────────────────────────────────────
    for m in re.finditer(r'(?:youtube\.com/embed|youtu\.be)/([a-zA-Z0-9_-]{11})', html):
        vid = m.group(1)
        add(
            f"https://www.youtube.com/watch?v={vid}",
            "Trailer (YouTube)",
            thumbnail=f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
        )

    # ── 2. iframe src — double va single quote ALOHIDA ─────────
    # Double-quoted src="..."
    for m in re.finditer(r'<iframe[^>]+src="([^"]+)"', html, re.IGNORECASE):
        src = m.group(1)
        if "youtube" in src or "youtu.be" in src:
            continue
        add(src, "Film")
    # Single-quoted src='...'
    for m in re.finditer(r"<iframe[^>]+src='([^']+)'", html, re.IGNORECASE):
        src = m.group(1)
        if "youtube" in src or "youtu.be" in src:
            continue
        add(src, "Film")

    # ── 3. <video> / <source> teglar ──────────────────────────
    for m in re.finditer(r'<source[^>]+src="([^"]+)"', html, re.IGNORECASE):
        add(m.group(1), "Video (to'g'ridan-to'g'ri)")
    for m in re.finditer(r"<source[^>]+src='([^']+)'", html, re.IGNORECASE):
        add(m.group(1), "Video (to'g'ridan-to'g'ri)")

    # ── 4. jwplayer / videojs file konfiguratsiyasi ────────────
    for m in re.finditer(
        r'["\']?file["\']?\s*:\s*"([^"]+\.(?:mp4|m3u8|webm|mkv)[^"]*)"',
        html, re.IGNORECASE
    ):
        add(m.group(1), "Film (Player)")
    for m in re.finditer(
        r"[\"']?file[\"']?\s*:\s*'([^']+\.(?:mp4|m3u8|webm|mkv)[^']*)'",
        html, re.IGNORECASE
    ):
        add(m.group(1), "Film (Player)")

    # ── 5. data-src yoki data-video atributlari ────────────────
    for m in re.finditer(
        r'data-(?:src|video|url|file)\s*=\s*"([^"]+\.(?:mp4|m3u8|webm)[^"]*)"',
        html, re.IGNORECASE
    ):
        add(m.group(1), "Film")

    logger.info(f"[VideoExtractor/scrape] {len(options)} ta manba: {[o.title for o in options]}")
    return options


def _extract_options_ydl_sync(page_url: str) -> list[VideoOption]:
    """yt-dlp extract_flat=True bilan barcha video variantlarini topadi."""
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return []

    opts: dict = {
        "quiet": True,
        "no_warnings": False,
        "skip_download": True,
        "no_check_certificate": True,
        "extract_flat": True,
        "noplaylist": False,
        "cookiesfrombrowser": ("firefox",),
    }
    if _YDL_IMPERSONATE is not None:
        opts["impersonate"] = _YDL_IMPERSONATE

    def _run(o: dict) -> dict | None:
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                return ydl.extract_info(page_url, download=False)
        except Exception as e:
            err = str(e)
            if any(k in err.lower() for k in ("firefox", "cookie", "dpapi")):
                no_cookies = {k: v for k, v in o.items() if k != "cookiesfrombrowser"}
                with yt_dlp.YoutubeDL(no_cookies) as ydl2:
                    return ydl2.extract_info(page_url, download=False)
            raise

    try:
        info = _run(opts)
    except Exception as e:
        logger.warning(f"[VideoExtractor/ydl-flat] {e}")
        return []

    if not info:
        return []

    results: list[VideoOption] = []
    if info.get("_type") == "playlist":
        for entry in (info.get("entries") or []):
            if not entry:
                continue
            entry_url = entry.get("webpage_url") or entry.get("url")
            if not entry_url:
                continue
            results.append(VideoOption(
                title=entry.get("title") or entry.get("id") or "Video",
                source_url=entry_url,
                thumbnail=entry.get("thumbnail"),
                duration=entry.get("duration"),
            ))
    else:
        results.append(VideoOption(
            title=info.get("title") or "Video",
            source_url=info.get("webpage_url") or page_url,
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
        ))

    return results


def _merge_options(
    primary: list[VideoOption],
    secondary: list[VideoOption],
    page_url: str = "",
) -> list[VideoOption]:
    """
    Ikki ro'yxatni birlashtiradi, dublikat URL'larni olib tashlaydi.
    page_url bilan mos keladigan optionlarni filtrlab tashlaydi (infinite loop oldini oladi).
    """
    seen: set[str] = set()
    result: list[VideoOption] = []
    page_key = page_url.split("?")[0].rstrip("/") if page_url else ""

    for opt in primary + secondary:
        key = opt.source_url.split("?")[0].rstrip("/")
        if key in seen or (page_key and key == page_key):
            continue
        seen.add(key)
        result.append(opt)

    return result
