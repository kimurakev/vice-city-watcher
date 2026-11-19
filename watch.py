#!/usr/bin/env python3
"""
Vice City drop watcher.

Fetches a fixed list of pages, extracts only the parts that matter
(Cactus Jack / Vice City product listings, stock badges, key page text),
compares against the last saved snapshot in state.json, and sends a push
notification through ntfy.sh when anything changes.

Run it on a schedule (GitHub Actions, cron, launchd). Set NTFY_TOPIC in the
environment. Optional: NTFY_SERVER (default https://ntfy.sh).

No third-party packages required. Python 3.9+.
"""

import difflib
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

STATE_FILE = os.environ.get("STATE_FILE", "state.json")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TIMEOUT = 25

KEYWORDS = ["cactus", "vice city", "vicecity", "gta", "travis scott", "swingman"]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Watch list. Each entry has a name, a URL, a type, and an optional "click"
# URL that the phone notification opens (defaults to the url).
#
# Types:
#   shopify  : hits <store>/products.json and lists matching products with
#              availability. Works on any Shopify store.
#   keywords : fetches HTML, strips tags, keeps only lines that contain one of
#              KEYWORDS. Good for server-rendered pages.
#   fulltext : fetches HTML, strips tags, keeps everything (hash of the body).
#              Good for article pages where any edit matters.
# ---------------------------------------------------------------------------
WATCHES = [
    {
        "name": "Heat Store products (Cactus Jack / Vice City)",
        "url": "https://www.miamiheatstore.com",
        "type": "shopify",
        "click": "https://www.miamiheatstore.com/collections/vc",
    },
    {
        "name": "Heat Store search: cactus jack",
        "url": "https://www.miamiheatstore.com/search?q=cactus+jack",
        "type": "keywords",
    },
    {
        "name": "Heat uniform page (nba.com)",
        "url": "https://www.nba.com/heat/uniforms/2627-heat-vice-city-uniform-collection",
        "type": "keywords",
    },
    {
        "name": "Travis Scott shop products",
        "url": "https://shop.travisscott.com",
        "type": "shopify",
    },
    {
        "name": "Nike search: cactus jack heat",
        "url": "https://www.nike.com/w?q=cactus%20jack%20heat",
        "type": "keywords",
    },
    {
        "name": "Nike SNKRS upcoming",
        "url": "https://www.nike.com/launch?s=upcoming",
        "type": "keywords",
    },
    {
        "name": "Fanatics search: cactus jack heat",
        "url": "https://www.fanatics.com/?query=cactus%20jack%20miami%20heat",
        "type": "keywords",
    },
    {
        "name": "NBA Store search: cactus jack heat",
        "url": "https://store.nba.com/?query=cactus%20jack%20miami%20heat",
        "type": "keywords",
    },
    {
        "name": "Resell Calendar: Travis Scott x Heat collection",
        "url": "https://resellcalendar.com/news/news/travis-scott-miami-heat-gta-6-collection-vice-city-jersey/",
        "type": "fulltext",
    },
    {
        "name": "Resell Calendar: Heat GTA 6 jersey details",
        "url": "https://resellcalendar.com/news/news/miami-heat-gta-6-vice-city-jersey-reseller-details/",
        "type": "fulltext",
    },
    {
        "name": "Sole Retriever: Cactus Jack x Heat apparel",
        "url": "https://www.soleretriever.com/news/articles/travis-scott-cactus-jack-nike-miami-heat-gta-6-apparel-collection",
        "type": "fulltext",
    },
]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch(url, accept="text/html,application/json;q=0.9,*/*;q=0.8"):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
            try:
                return r.status, body.decode("utf-8", "replace")
            except Exception:
                return r.status, body.decode("latin-1", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # timeouts, DNS, TLS
        return 0, f"ERROR {type(e).__name__}: {e}"


def strip_html(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article|option)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"[ \t\r\f\v ]+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def dedupe(lines):
    seen, out = set(), []
    for l in lines:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


# ---------------------------------------------------------------------------
# Extractors. Each returns (ok, snapshot_text).
# ---------------------------------------------------------------------------
def extract_shopify(base):
    products = []
    page = 1
    while page <= 8:
        status, body = fetch(f"{base}/products.json?limit=250&page={page}", accept="application/json")
        if status != 200 or not body.strip():
            if page == 1:
                return False, f"HTTP {status} {body[:120]}"
            break
        try:
            batch = json.loads(body).get("products", [])
        except Exception:
            return False, f"non-JSON response ({body[:80]!r})"
        if not batch:
            break
        products.extend(batch)
        if len(batch) < 250:
            break
        page += 1

    lines = []
    for p in products:
        hay = " ".join([
            p.get("title", ""), p.get("handle", ""), p.get("vendor", ""),
            p.get("product_type", ""), " ".join(p.get("tags", []) or []),
        ]).lower()
        if not any(k in hay for k in KEYWORDS):
            continue
        variants = p.get("variants", []) or []
        avail = sum(1 for v in variants if v.get("available"))
        prices = sorted({v.get("price") for v in variants if v.get("price")})
        price = ("$" + prices[0]) if len(prices) == 1 else (f"${prices[0]} to ${prices[-1]}" if prices else "no price")
        lines.append(f"{p.get('title','?')} | {price} | {avail}/{len(variants)} variants in stock | /products/{p.get('handle','')}")
    lines.sort()
    header = f"{len(products)} products in store, {len(lines)} matching"
    return True, "\n".join([header] + lines)


def extract_keywords(url):
    status, body = fetch(url)
    if status != 200:
        return False, f"HTTP {status} {body[:120]}"
    lines = [l for l in strip_html(body) if any(k in l.lower() for k in KEYWORDS)]
    lines = dedupe(lines)
    # Shopify / search pages often echo the query; drop pure boilerplate noise.
    lines = [l for l in lines if len(l) < 400]
    if not lines:
        return True, "(no lines matched keywords)"
    return True, "\n".join(lines)


def extract_fulltext(url):
    status, body = fetch(url)
    if status != 200:
        return False, f"HTTP {status} {body[:120]}"
    lines = dedupe(strip_html(body))
    # Drop things that change on every load (dates, counters, cache busters).
    noise = re.compile(r"\b\d{1,2}:\d{2}\b|\b\d+\s+(seconds?|minutes?|hours?|days?)\s+ago\b|\b\d+\s+(views?|comments?)\b")
    lines = [l for l in lines if not noise.search(l.lower())]
    return True, "\n".join(lines)


EXTRACTORS = {
    "shopify": extract_shopify,
    "keywords": extract_keywords,
    "fulltext": extract_fulltext,
}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def notify(title, message, click=None, priority="high", tags="rotating_light"):
    if not NTFY_TOPIC:
        print("  (NTFY_TOPIC not set; would have sent:)")
        print("  " + title)
        print("  " + message.replace("\n", "\n  "))
        return
    headers = {
        "Title": title.encode("ascii", "ignore").decode(),
        "Priority": priority,
        "Tags": tags,
    }
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{urllib.parse.quote(NTFY_TOPIC)}",
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            print(f"  ntfy -> {r.status}")
    except Exception as e:
        print(f"  ntfy FAILED: {e}")


def short_diff(old, new, limit=1800):
    old_l, new_l = old.splitlines(), new.splitlines()
    added = [l for l in new_l if l not in old_l]
    removed = [l for l in old_l if l not in new_l]
    parts = []
    if added:
        parts.append("NEW:\n" + "\n".join("+ " + l for l in added[:25]))
    if removed:
        parts.append("GONE:\n" + "\n".join("- " + l for l in removed[:15]))
    if not parts:
        d = list(difflib.unified_diff(old_l, new_l, lineterm="", n=0))
        parts.append("\n".join(d[:30]))
    text = "\n\n".join(parts)
    return text[:limit] + ("\n..." if len(text) > limit else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, ensure_ascii=False, sort_keys=True)


def main():
    state = load_state()
    first_run = not state
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    changes = 0
    print(f"Vice City watcher, {now}, {len(WATCHES)} targets, state={'seeded' if first_run else 'loaded'}")

    for w in WATCHES:
        name, url, kind = w["name"], w["url"], w["type"]
        click = w.get("click", url)
        ok, snap = EXTRACTORS[kind](url)
        digest = hashlib.sha256(snap.encode("utf-8")).hexdigest()
        prev = state.get(name, {})
        prev_ok, prev_digest, prev_snap = prev.get("ok"), prev.get("hash"), prev.get("snapshot", "")

        if not ok:
            # A fetch failure only gets reported when it is new, so a page that
            # blocks bots does not spam you every run.
            if prev_ok is None or prev_ok:
                print(f"[fail ] {name}: {snap}")
                if not first_run:
                    notify(f"Watcher: can't read {name}", f"{snap}\n{url}", click, priority="low", tags="warning")
            else:
                print(f"[fail ] {name}: still failing ({snap[:60]})")
            state[name] = {"ok": False, "hash": digest, "snapshot": snap, "checked": now,
                           "changed": prev.get("changed")}
            continue

        if prev_digest == digest:
            print(f"[same ] {name}")
            state[name]["checked"] = now
            continue

        if prev_digest is None or not prev_ok:
            print(f"[seed ] {name} ({len(snap.splitlines())} lines)")
            if not first_run and not prev_ok and prev_ok is not None:
                notify(f"Watcher: {name} readable again", snap[:1500], click, priority="default", tags="eyes")
        else:
            changes += 1
            print(f"[CHANGE] {name}")
            diff = short_diff(prev_snap, snap)
            print("  " + diff.replace("\n", "\n  "))
            notify(f"CHANGE: {name}", f"{diff}\n\n{click}", click)

        state[name] = {"ok": True, "hash": digest, "snapshot": snap, "checked": now, "changed": now}
        time.sleep(0.5)

    save_state(state)
    if first_run:
        print("State seeded. Next run will alert on differences.")
        notify("Vice City watcher is live",
               f"Seeded {len(WATCHES)} targets at {now}. You'll get a push the moment any of them change.",
               priority="default", tags="white_check_mark")
    print(f"Done. {changes} change(s).")


if __name__ == "__main__":
    sys.exit(main())
