"""Web search, page reading, weather and news. No API keys needed."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import CITY, NEWS_REGION
from . import clip, string, tool

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}


def _get(url: str, **kw) -> httpx.Response:
    return httpx.get(url, headers=UA, timeout=15, follow_redirects=True, **kw)


def _ddg(query: str) -> list[tuple[str, str, str]]:
    r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=UA, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select(".result"):
        if "result--ad" in res.get("class", []):
            continue
        a, snip = res.select_one("a.result__a"), res.select_one(".result__snippet")
        if not a:
            continue
        href = a.get("href", "")
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        out.append((a.get_text(" ", strip=True), href, snip.get_text(" ", strip=True) if snip else ""))
    return out


def _bing(query: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(_get(f"https://www.bing.com/search?q={quote_plus(query)}").text, "html.parser")
    out = []
    for li in soup.select("li.b_algo"):
        a, p = li.select_one("h2 a"), li.select_one(".b_caption p, p")
        if a:
            out.append((a.get_text(" ", strip=True), a.get("href", ""), p.get_text(" ", strip=True) if p else ""))
    return out


@tool("Search the web. Returns titles, URLs and snippets; use read_webpage for detail.",
      {"query": string("Search query")})
def web_search(query: str) -> str:
    results = []
    for engine in (_ddg, _bing):
        try:
            results = engine(query)
        except httpx.HTTPError:
            continue
        if results:
            break
    if not results:
        return "No results (search engines unreachable?)"
    return "\n\n".join(f"{t}\n{u}\n{s}" for t, u, s in results[:6])


@tool("Fetch a web page and return its readable text.", {"url": string("Page URL")})
def read_webpage(url: str) -> str:
    try:
        r = _get(url if "://" in url else "https://" + url)
    except httpx.HTTPError as e:
        return f"Could not fetch: {e}"
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        t.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\n\s*\n+", "\n\n", main.get_text("\n", strip=True))
    title = soup.title.get_text(strip=True) if soup.title else url
    return clip(f"{title}\n\n{text}", 6000)


@tool("Current weather and today's forecast.",
      {"location": string("City name; omit for the user's current location")}, required=[])
def weather(location: str = "") -> str:
    loc = (location or CITY).strip()
    try:
        d = _get(f"https://wttr.in/{quote_plus(loc)}?format=j1").json()
    except (httpx.HTTPError, ValueError) as e:
        return f"Weather service unavailable: {e}"
    c, today = d["current_condition"][0], d["weather"][0]
    area = d.get("nearest_area", [{}])[0]
    place = ", ".join(x[0]["value"] for x in (area.get("areaName"), area.get("country")) if x) or loc
    rain = max(int(h.get("chanceofrain", 0)) for h in today.get("hourly", [{"chanceofrain": 0}]))
    return (f"{place}: {c['weatherDesc'][0]['value']}, {c['temp_C']}°C (feels {c['FeelsLikeC']}°C), "
            f"humidity {c['humidity']}%, wind {c['windspeedKmph']} km/h. Today {today['mintempC']}–"
            f"{today['maxtempC']}°C, max chance of rain {rain}%.")


@tool("Latest news headlines, optionally about a topic.",
      {"topic": string("Topic to search; omit for top headlines")}, required=[])
def news(topic: str = "") -> str:
    country, lang = (NEWS_REGION.split(":") + ["en"])[:2]
    params = f"hl={lang}-{country}&gl={country}&ceid={country}:{lang}"
    url = (f"https://news.google.com/rss/search?q={quote_plus(topic)}&{params}" if topic
           else f"https://news.google.com/rss?{params}")
    try:
        root = ET.fromstring(_get(url).content)
    except (httpx.HTTPError, ET.ParseError) as e:
        return f"News unavailable: {e}"
    items = root.findall(".//item")[:8]
    return "\n".join(f"- {i.findtext('title')} ({i.findtext('pubDate', '')[:16]})" for i in items) or "No news found"
