#!/usr/bin/env python3
"""
LZ-ArtWork Client Bot — Telegram Bot API polling (no external deps).

Usage: python3 bot_client.py

Policy:
- AI used ONLY for commission validation, email draft generation.
- Request outside scope (creative help, image gen, etc.) -> auto-reject.
- Owner approval required before any public-facing action.
"""

import html
import json
import urllib.request
import urllib.parse
import uuid
from pathlib import Path
from datetime import datetime

# --- CONFIG (owner-controlled) ---
# Token baca dari .env manual karena Termux tidak selalu load env untuk semua proses
_token_raw = Path.home() / ".hermes/.env"
BOT_TOKEN = ""
if _token_raw.exists():
    for _line in _token_raw.read_text().splitlines():
        if _line.startswith("LZARTWORK_BOT_TOKEN="):
            BOT_TOKEN = _line.split("=", 1)[1].strip()
            break

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_DIR = Path.home() / "proyek/freelance-commission-business"
LOG_FILE = BASE_DIR / "bot_requests.log"
ORDERS_FILE = BASE_DIR / "orders.jsonl"
GALLERY_IMAGE = BASE_DIR / "assets/rya-character-portrait-01.jpg"

# Owner: Rya. Order masuk dikabari ke sini.
OWNER_ID = 7842025802
BOT_HANDLE = "Lz_ArtWork_bot"

PRICE_INFO = """
📊 <b>LZ-ArtWork — Harga Commission</b>

• Headshot — Rp100.000/karakter
• Half Body — Rp150.000/karakter
• Full Body — Rp200.000/karakter
• Detailed Background +Rp50.000

❗ Simple Background Gratis
❗ Revisi #1–#2 Gratis

Kirim /commission untuk permintaan pemesanan.
"""

# --- HELPERS ---


def log_chat(user_id, text, resp):
    def one_line(v):
        return " ".join(str(v).split())[:120]

    try:
        with open(LOG_FILE, "a") as f:
            f.write(
                f"{datetime.now().isoformat()} | {user_id} | "
                f"{one_line(text)} | {one_line(resp)}\n"
            )
    except Exception as e:
        print(f"log_chat error: {e}", flush=True)


def _telegram_call(method, fields, files=None):
    """Raw Telegram API call. Without files -> GET query. With files -> multipart POST."""
    if not files:
        url = f"{API_BASE}/{method}?{urllib.parse.urlencode(fields)}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())

    boundary = "----LZArtWork" + uuid.uuid4().hex
    body = b""
    for key, value in fields.items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n"
            f"{value}\r\n"
        ).encode()
    for key, (filename, blob) in files.items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body += blob + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{API_BASE}/{method}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


def send_text(chat_id, text, parse_mode="HTML"):
    """Send a message. Returns True on delivery, False on failure.

    Never raises: the polling loop treats a failed reply as a lost message, and an
    exception here would kill the whole bot. Callers that care (notify_owner) get the
    False back and log it.
    """
    try:
        resp = _telegram_call(
            "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )
    except Exception as e:
        print(f"send_text error: {e}", flush=True)
        return False
    if not resp.get("ok"):
        print(f"send_text not ok: {resp.get('description')}", flush=True)
        return False
    return True


def send_photo(chat_id, photo_path, caption=""):
    """Send a photo. Returns True on delivery, False on failure.

    Same contract as send_text: an HTTP 200 carrying {"ok": false} is a failed
    delivery, not a success. Telegram answers 400 for an unknown chat_id, which
    would otherwise read as a delivered gallery.
    """
    try:
        blob = Path(photo_path).read_bytes()
        resp = _telegram_call(
            "sendPhoto",
            {"chat_id": chat_id, "caption": caption},
            files={"photo": (Path(photo_path).name, blob)},
        )
    except Exception as e:
        print(f"send_photo error: {e}", flush=True)
        return False
    if not resp.get("ok"):
        print(f"send_photo not ok: {resp.get('description')}", flush=True)
        return False
    return True


def notify_owner(text):
    """Ping Rya. Returns delivery status and ALWAYS writes a receipt line.

    An order that reaches orders.jsonl but whose alert never lands leaves Rya with a
    silent queue — the 28 Sep order proved the notification path was unobservable.
    """
    ok = send_text(OWNER_ID, text)
    log_chat(OWNER_ID, "notify_owner", "OK sent" if ok else "FAIL not delivered")
    return ok


def append_order(chat_id, brief, username=""):
    """Persist an incoming order. Returns the order id."""
    order_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    record = {
        "order_id": order_id,
        "created_at": datetime.now().isoformat(),
        "chat_id": chat_id,
        "username": username,
        "brief": brief,
        "status": "NEW",  # NEW -> REVIEWED -> QUOTED -> ACCEPTED -> PAID -> DONE / REJECTED
    }
    with open(ORDERS_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return order_id


# --- ORDER LEDGER READ/WRITE (owner commands) ---

def load_orders():
    """Read the whole ledger. A malformed line is skipped, not fatal — a single bad
    byte must not make Rya's entire queue invisible."""
    if not ORDERS_FILE.exists():
        return []
    out = []
    for line in ORDERS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def save_orders(records):
    """Rewrite the ledger atomically — a crash mid-write must not truncate the queue."""
    tmp = ORDERS_FILE.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    tmp.replace(ORDERS_FILE)


def find_order(records, needle):
    """Match on full order id, or on a unique prefix. Telegram makes copy-pasting a
    24-char id awkward, so a distinctive prefix is the normal way this gets used."""
    needle = needle.strip()
    for rec in records:
        if rec.get("order_id") == needle:
            return rec
    hits = [r for r in records if str(r.get("order_id", "")).startswith(needle)]
    return hits[0] if len(hits) == 1 else None


# --- POLICY ENGINE ---
ALLOWED_INTENTS = ["commission", "price", "gallery", "contact", "terms"]

BLOCKED_KEYWORDS = [
    "generate image", "create art", "draw", "illustrate", "ai art",
    "model", "weights", "gguf", "huggingface", "api key", "api_key",
    "discord", "tiktok post", "schedule", "bot approval",
]


def check_blocked(text):
    t = text.lower()
    return any(kw in t for kw in BLOCKED_KEYWORDS)


def extract_intent(text):
    t = text.lower().strip()
    if t.startswith("/start"):
        return "start"
    if t.startswith("/price"):
        return "price"
    if t.startswith("/gallery"):
        return "gallery"
    if t.startswith("/contact"):
        return "contact"
    if t.startswith("/terms"):
        return "terms"
    if t.startswith("/commission"):
        return "commission"
    if t.startswith("/orders"):
        return "orders"
    if t.startswith("/status"):
        return "status"
    if t.startswith("/quote"):
        return "quote"
    return "unknown"


# Owner-only commands. A client typing /orders gets the generic "unknown command" reply —
# these are Rya's work queue, not a menu item for the public. Guarded on chat_id, not on
# the command name, so a leaked alias still can't reach another person's orders.
OWNER_COMMANDS = ("orders", "status", "quote")

# Order lifecycle. append_order() writes NEW; /status is the only writer of the rest.
VALID_STATUSES = ("REVIEWED", "QUOTED", "ACCEPTED", "REJECTED", "PAID", "DONE")


# Command names a client is most likely to fumble. On a real order (28 Sep) someone
# typed /comission and got a flat "unknown command" — one dropped character, and the
# brief that followed it was lost. Map the near-miss to the real command so the client
# gets told the right spelling instead of silence.
TYPO_HINTS = {
    "/comission": "/commission",
    "/comisson": "/commission",
    "/commision": "/commission",
    "/commisson": "/commission",
    "/commissions": "/commission",
    "/pesanan": "/commission",
    "/order": "/commission",
    "/harga": "/price",
    "/pricea": "/price",
    "/galeri": "/gallery",
    "/galleri": "/gallery",
    "/kontak": "/contact",
}


def suggest_command(text):
    """Return the intended command for a near-miss, else None."""
    first = text.lower().strip().split()[0] if text.strip() else ""
    if not first.startswith("/"):
        return None
    return TYPO_HINTS.get(first.rstrip(",.!?"))


# --- COMMAND HANDLERS ---
def handle_start(chat_id):
    return """
🎨 <b>LZ-ArtWork Bot</b>

Halo! Aku asisten commission digital character portrait dari LZ-ArtWork.

📌 Perintah yang tersedia:
• /price — lihat harga
• /commission — buat permintaan pemesanan
• /gallery — lihat contoh karya
• /contact — cara menghubungi
• /terms — syarat & ketentuan

❗ Pemesanan lewat /commission. Brief kamu masuk ke antrean review Rya.

Kirim pesan lain → auto-reject untuk menjaga privasi & fokus.
"""


def handle_price():
    return PRICE_INFO


def handle_gallery():
    # Portfolio host-nya lokal (localhost), tidak bisa dibuka klien dari Telegram.
    # Jadi kirim langsung contoh karyanya sebagai foto.
    return None


def handle_contact():
    return (
        "📩 <b>Kontak LZ-ArtWork</b>\n"
        f"• Telegram: @{BOT_HANDLE}\n"
        "• Email: aryaxx12@gmail.com\n"
        "• TikTok: @ryaa_xx1"
    )


def handle_terms():
    return """
✅ <b>Terms &amp; FAQ</b>

• Setiap commission dimulai dari brief yang jelas.
• Revisi #1–#2 gratis (perubahan besar = kuotasi baru).
• DP 50% setelah scope disetujui, sisanya setelah selesai.
• NSFW tidak diterima.
• Pembayaran: QRIS / DANA saja.

Untuk info lebih detail, kirim /commission.
"""


def handle_commission():
    return """
📝 <b>Form Pemesanan Commission</b>

Kirim dalam satu pesan, format:

<code>/commission
Jenis: Headshot / Half Body / Full Body
Karakter: jumlah
Brief: deskripsi karakter, mood, pose
Deadline: tanggal atau "fleksibel"
Penggunaan: Personal / Commercial / Social Media</code>

Contoh:
<code>/commission
Jenis: Headshot
Karakter: 2
Brief: Karakter fantasy ala knight, pakaian merah, senyum ceria
Deadline: minggu depan
Penggunaan: Personal</code>

Brief lengkap lebih cepat diproses. Minimal 10 karakter.
"""


def validate_commission(text):
    if len(text) < 10:
        return False, "❗ Brief terlalu singkat (minimal 10 karakter). Kirim /commission untuk formatnya."
    if check_blocked(text):
        return False, "❌ Request ini tidak diizinkan. Silakan kirim brief ke email langsung."
    return True, None


def fmt_order_confirmation(order_id, brief):
    return (
        "✅ <b>Brief kamu sudah masuk antrean.</b>\n\n"
        f"🆔 Order ID: <code>{html.escape(order_id)}</code>\n\n"
        f"📄 Ringkasan brief:\n<i>{html.escape(brief[:600])}</i>\n\n"
        "Rya akan meninjau dan membalas dengan quotation serta langkah berikutnya. "
        "Mengirim brief belum berarti commission diterima — harga dan scope final "
        "dikonfirmasi setelah review."
    )


def fmt_owner_alert(order_id, chat_id, username, brief):
    who = f"@{username}" if username else "(tanpa username)"
    return (
        "🔔 <b>ORDER BARU — LZ-ArtWork</b>\n\n"
        f"🆔 <code>{html.escape(order_id)}</code>\n"
        f"👤 chat_id: <code>{chat_id}</code> {html.escape(who)}\n"
        f"🕒 {datetime.now().strftime('%d %b %Y %H:%M')}\n\n"
        f"📄 Brief:\n<i>{html.escape(brief[:900])}</i>\n\n"
        "Balas klien: kirim pesan ke chat_id di atas."
    )


# --- OWNER WORK QUEUE (/orders, /status, /quote) ---

STATUS_ICONS = {
    "NEW": "🆕", "REVIEWED": "👀", "QUOTED": "💰", "ACCEPTED": "✅",
    "REJECTED": "❌", "PAID": "💳", "DONE": "🎉",
}


def _brief_headline(brief):
    """One short line out of the multi-line brief, for the queue list."""
    first = ""
    for line in str(brief).splitlines():
        if line.strip():
            first = line.strip()
            break
    return first[:60]


def handle_orders(arg=""):
    """/orders [STATUS] — Rya's queue. Default: everything still open, newest first."""
    records = load_orders()
    if not records:
        return "📋 <b>Antrean kosong.</b>\n\nBelum ada order masuk."

    want = (arg or "").strip().upper()
    if want:
        records = [r for r in records if str(r.get("status", "")).upper() == want]
        if not records:
            return f"📋 Tidak ada order berstatus <code>{html.escape(want)}</code>."

    closed = {"DONE", "REJECTED"}
    if not want:
        records = [r for r in records if str(r.get("status", "")).upper() not in closed]

    records.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)

    lines = [
        f"📋 <b>Antrean LZ-ArtWork</b> — {len(records)} order"
        + (f" berstatus {html.escape(want)}" if want else " belum selesai")
        + "\n"
    ]
    for rec in records[:15]:
        st = str(rec.get("status", "NEW")).upper()
        who = f"@{rec['username']}" if rec.get("username") else f"chat {rec.get('chat_id')}"
        lines.append(
            f"{STATUS_ICONS.get(st, '•')} <code>{html.escape(str(rec['order_id']))}</code>\n"
            f"   {st} · {html.escape(who)} · {html.escape(_brief_headline(rec.get('brief', '')))}"
        )
    if len(records) > 15:
        lines.append(f"\n… {len(records) - 15} order lagi. Pakai /orders STATUS untuk filter.")
    lines.append(
        "\nUbah status: <code>/status ORDER_ID STATUS</code>\n"
        "Kirim ke klien: <code>/quote ORDER_ID</code> atau balas "
        f"<code>{OWNER_ID}#CHAT_ID|pesan</code>"
    )
    return "\n".join(lines)


def handle_status(arg=""):
    """/status ORDER_ID STATUS [pesan ke klien] — advance the order, notify the client."""
    parts = arg.split(None, 2)
    if not parts:
        return (
            "⚠️ Format: <code>/status ORDER_ID STATUS</code>\n\n"
            f"Status valid: {', '.join(VALID_STATUSES)}\n"
            "Contoh: <code>/status 20260928-0356 ACCEPTED</code>"
        )

    needle = parts[0]
    new_status = parts[1].strip().upper() if len(parts) > 1 else ""
    note = parts[2] if len(parts) > 2 else ""

    if new_status not in VALID_STATUSES:
        return (
            f"❌ Status <code>{html.escape(new_status or 'kosong')}</code> tidak dikenal.\n"
            f"Status valid: {', '.join(VALID_STATUSES)}"
        )

    records = load_orders()
    rec = find_order(records, needle)
    if rec is None:
        hits = len([r for r in records if str(r.get("order_id", "")).startswith(needle.strip())])
        if hits > 1:
            return f"❌ <code>{html.escape(needle)}</code> cocok dengan {hits} order. Pakai id lengkap."
        return f"❌ Order <code>{html.escape(needle)}</code> tidak ditemukan."

    old = str(rec.get("status", "NEW")).upper()
    rec["status"] = new_status
    rec["status_history"] = list(rec.get("status_history", [])) + [
        {"from": old, "to": new_status, "at": datetime.now().isoformat(), "by": str(OWNER_ID)}
    ]
    save_orders(records)

    who = f"@{rec['username']}" if rec.get("username") else f"chat {rec.get('chat_id')}"
    client_sent = False
    if note.strip():
        body = f"📌 <b>Update order</b> <code>{html.escape(str(rec['order_id']))}</code>\n\n{note.strip()}"
        client_sent = send_text(rec.get("chat_id"), f"💬 <b>LZ-ArtWork</b>\n\n{html.escape(note.strip())}")
        log_chat(rec.get("chat_id"), note.strip(), "owner-status" if client_sent else "FAIL owner-status")

    confirm = (
        f"✅ <b>{html.escape(old)} → {html.escape(new_status)}</b>\n"
        f"🆔 <code>{html.escape(str(rec['order_id']))}</code>\n"
        f"👤 {html.escape(who)}"
    )
    if note.strip():
        confirm += f"\n📨 Klien: {'dikabari' if client_sent else 'GAGAL terkirim'}"
    return confirm


def handle_quote(arg=""):
    """/quote ORDER_ID [harga] — send the client their order summary + estimate."""
    parts = arg.split(None, 1)
    if not parts:
        return (
            "⚠️ Format: <code>/quote ORDER_ID [harga]</code>\n"
            "Contoh: <code>/quote 20260928-0356 450000</code>"
        )

    rec = find_order(load_orders(), parts[0])
    if rec is None:
        return f"❌ Order <code>{html.escape(parts[0])}</code> tidak ditemukan."

    price = parts[1].strip() if len(parts) > 1 else ""
    body = (
        f"📋 <b>Ringkasan order kamu</b>\n\n"
        f"🆔 <code>{html.escape(str(rec['order_id']))}</code>\n"
        f"📄 {html.escape(str(rec.get('brief', ''))[:600])}\n\n"
    )
    if price:
        body += (
            f"💰 Estimasi: <b>Rp{html.escape(price)}</b>\n\n"
            "Harga final dikonfirmasi setelah scope disepakati. "
            "DP 50% setelah scope disetujui, sisanya setelah selesai.\n\n"
            "Setuju? Balas pesan ini ya."
        )
    else:
        body += "Rya akan kirim estimasi harga shortly. Sabar ya 🙏"

    sent = send_text(rec.get("chat_id"), body)
    log_chat(rec.get("chat_id"), "quote", "OK sent" if sent else "FAIL not delivered")
    who = f"@{rec['username']}" if rec.get("username") else f"chat {rec.get('chat_id')}"
    return (
        f"{'✅' if sent else '❌'} Quote ke {html.escape(who)} — "
        f"{'terkirim' if sent else 'GAGAL'}"
        + (f" (Rp{html.escape(price)})" if price else "")
    )


# --- DISPATCH ---
def process_update(update, offset_state=None):
    """Handle one Telegram update. All side effects go through module-level
    send_text / notify_owner / log_chat so tests can patch them."""
    msg = update.get("message", {})
    text = msg.get("text", "")
    chat_id = msg.get("chat", {}).get("id")
    username = msg.get("from", {}).get("username", "")

    if not text or not chat_id:
        return

    # Owner replies to clients: owner_id#12345|<pesan>
    if chat_id == OWNER_ID and text.startswith(f"{OWNER_ID}#"):
        try:
            target_raw, body = text.split("|", 1)
            target = int(target_raw.split("#", 1)[1])
        except Exception:
            send_text(OWNER_ID, "❌ Format salah. Pakai: <code>7842025802#CHAT_ID|pesan</code>")
            return
        send_text(target, f"💬 <b>LZ-ArtWork</b>\n\n{html.escape(body.strip())}")
        log_chat(chat_id, text, "owner-reply")
        send_text(OWNER_ID, f"✅ Terkirim ke <code>{target}</code>.")
        return

    if check_blocked(text):
        reply = "❌ Maaf, permintaan ini tidak diizinkan. Silakan hubungi lewat email langsung."
        send_text(chat_id, reply)
        log_chat(chat_id, text, reply)
        return

    intent = extract_intent(text)

    if intent == "commission":
        rest = text[len("/commission"):].strip()
        if not rest:
            reply = handle_commission()
            send_text(chat_id, reply)
            log_chat(chat_id, text, "form")
            return

        ok, err = validate_commission(rest)
        if not ok:
            send_text(chat_id, err)
            log_chat(chat_id, text, err)
            return

        order_id = append_order(chat_id, rest, username)
        reply = fmt_order_confirmation(order_id, rest)
        send_text(chat_id, reply)
        notify_owner(fmt_owner_alert(order_id, chat_id, username, rest))
        log_chat(chat_id, text, f"ORDER {order_id}")
        return

    if intent == "gallery":
        caption = "🖼️ <b>Contoh karya — LZ-ArtWork</b>\n\nCommission open. Kirim /commission untuk memesan."
        if not send_photo(chat_id, GALLERY_IMAGE, caption):
            send_text(chat_id, caption)
        log_chat(chat_id, text, "gallery")
        return

    # Owner work queue — Rya only. A client hitting /orders or /status falls through to
    # the generic unknown-command reply below, so this queue is never advertised.
    if intent in OWNER_COMMANDS:
        if chat_id != OWNER_ID:
            send_text(
                chat_id,
                "❓ Perintah tidak dikenal. Kirim /start untuk melihat menu utama.",
            )
            log_chat(chat_id, text, "owner-command denied")
            return
        arg = text.strip().split(None, 1)
        arg = arg[1] if len(arg) > 1 else ""
        owner_handlers = {
            "orders": handle_orders,
            "status": handle_status,
            "quote": handle_quote,
        }
        reply = owner_handlers[intent](arg)
        send_text(chat_id, reply)
        log_chat(chat_id, text, reply)
        return

    handlers = {
        "start": handle_start,
        "price": lambda *_: handle_price(),
        "contact": lambda *_: handle_contact(),
        "terms": lambda *_: handle_terms(),
    }

    if intent in handlers:
        reply = handlers[intent](chat_id)
    else:
        intended = suggest_command(text)
        if intended:
            reply = (
                f"❓ Ketik <code>{html.escape(intended)}</code> ya — "
                f"maksudnya <code>{html.escape(intended)}</code>.\n\n"
                "Kirim ulang pakai ejaan yang benar, brief kamu belum masuk antrean."
            )
        else:
            reply = "❓ Perintah tidak dikenal. Kirim /start untuk melihat menu utama."

    send_text(chat_id, reply)
    log_chat(chat_id, text, reply)


# --- MAIN POLLING LOOP ---
def main():
    offset = 0
    print("Bot started, polling...", flush=True)

    while True:
        try:
            url = (
                f"{API_BASE}/getUpdates?offset={offset}&timeout=30"
                '&allowed_updates=["message"]'
            )
            with urllib.request.urlopen(url, timeout=35) as resp:
                data = json.loads(resp.read().decode())

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                process_update(update)

        except KeyboardInterrupt:
            print("Bot stopped.", flush=True)
            return
        except Exception as e:
            print(f"Polling error: {e}", flush=True)


if __name__ == "__main__":
    main()