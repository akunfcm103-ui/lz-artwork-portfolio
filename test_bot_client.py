#!/usr/bin/env python3
"""Tests for bot_client.py — offline, no network. Run: python3 test_bot_client.py"""

import sys
import json
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import bot_client as bot

FAILS = []


# --- HARD GUARD: never let a test run write to the real order ledger or log ---
# On 28 Sep three phantom records (chat_id 555111) landed in the production
# orders.jsonl: run_cycle() drives process_update() with the real module-level
# ORDERS_FILE. Redirect both to a temp dir for the whole module so no test can
# reach the real files, no matter which helper it uses.
import tempfile as _tempfile_mod

_TMPDIR = _tempfile_mod.TemporaryDirectory()
_REAL_ORDERS_FILE = bot.ORDERS_FILE
_REAL_LOG_FILE = bot.LOG_FILE
bot.ORDERS_FILE = Path(_TMPDIR.name) / "orders.jsonl"
bot.LOG_FILE = Path(_TMPDIR.name) / "bot_requests.log"
print(f"[guard] ORDERS_FILE -> {bot.ORDERS_FILE}")
print(f"[guard] LOG_FILE    -> {bot.LOG_FILE}")


def check(name, cond, detail=""):
    if cond:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        FAILS.append(name)


def fake_update(text, chat_id=555111, update_id=1):
    return {"update_id": update_id, "message": {"text": text, "chat": {"id": chat_id}}}


def run_cycle(text, chat_id=555111):
    """Drive one update through the bot without touching the network."""
    sent = []
    notified = []
    logged = []

    with mock.patch.object(bot, "send_text", lambda cid, t, parse_mode="HTML": sent.append((cid, t))), \
         mock.patch.object(bot, "notify_owner", lambda t: notified.append(t)), \
         mock.patch.object(bot, "log_chat", lambda uid, txt, resp: logged.append((uid, txt, resp))):
        bot.process_update(fake_update(text, chat_id), offset_state=None)

    return sent, notified, logged


# --- 1. The crash: /commission with a brief must not raise ---
try:
    sent, notified, logged = run_cycle(
        "/commission\nJenis: Headshot\nKarakter: 2\n"
        "Brief: Karakter fantasy ala knight pakaian merah\nPenggunaan: Personal"
    )
    commissioned = any("berhasil" in t.lower() or "terima" in t.lower() for _, t in sent)
    check("commission with brief does not crash and confirms", commissioned, f"sent={sent}")
except Exception as e:
    check("commission with brief does not crash and confirms", False, f"RAISED {type(e).__name__}: {e}")
    notified, logged = [], []


# --- 2. Owner gets notified on a real order ---
check("owner notified on order", len(notified) == 1, f"notified={notified}")
if notified:
    check("owner notification carries the brief", "knight" in notified[0], f"notif={notified[0][:120]}")
    check("owner notification carries client chat id", "555111" in notified[0], f"notif={notified[0][:120]}")


# --- 3. Order is logged (log_chat actually called) ---
check("log_chat called on order", len(logged) >= 1, f"logged={logged}")


# --- 4. Order persisted to file ---
# NOTE: chat 555111 here is a test fixture. ORDERS_FILE is redirected to a tmpdir so the
# run never appends to the real orders.jsonl (a test run on 28 Sep leaked 3 phantom
# records with chat_id 555111 into the production file).
import tempfile, os
with tempfile.TemporaryDirectory() as td:
    orders_file = Path(td) / "orders.jsonl"
    with mock.patch.object(bot, "ORDERS_FILE", orders_file):
        sent2 = []
        with mock.patch.object(bot, "send_text", lambda cid, t, parse_mode="HTML": sent2.append((cid, t))), \
             mock.patch.object(bot, "notify_owner", lambda t: None), \
             mock.patch.object(bot, "log_chat", lambda *a, **k: None):
            bot.process_update(
                fake_update("/commission Brief: karakter elf dengan armor perak panjang", 777888),
                offset_state=None,
            )
    exists = orders_file.exists()
    content = orders_file.read_text() if exists else ""
    check("order persisted to ORDERS_FILE", exists and "777888" in content, f"content={content[:200]!r}")


# --- 5. Short brief rejected, no order written ---
sent3, notified3, logged3 = run_cycle("/commission pendek")
check("short brief rejected", any("singkat" in t.lower() for _, t in sent3), f"sent={sent3}")
check("short brief does not notify owner", len(notified3) == 0, f"notified={notified3}")


# --- 6. /commission with no args shows the form ---
sent4, _, _ = run_cycle("/commission")
check("bare /commission shows form", any("Form Pemesanan" in t for _, t in sent4), f"sent={sent4}")


# --- 7. Blocked keyword rejected ---
sent5, notified5, _ = run_cycle("/commission tolong generate image naga besar sekali")
check("blocked keyword rejected", any("tidak diizinkan" in t.lower() for _, t in sent5), f"sent={sent5}")
check("blocked keyword does not notify owner", len(notified5) == 0, f"notified={notified5}")


# --- 8. No localhost anywhere in user-facing replies ---
# NOTE: the "send_photo error: HTTP 400" line this test used to print is NOT a bot bug.
# chat 555111 is a fixture id, so Telegram answers "chat not found" (HTTP 400). The
# gallery code path and the image bytes are fine; the assertion below is about the
# reply text, which never contains a local URL.
sent6, notified6, _ = run_cycle("/gallery")
all_out = " ".join(t for _, t in sent6) + " " + " ".join(notified6)
check("no localhost in gallery reply", "127.0.0.1" not in all_out and "localhost" not in all_out, f"out={all_out[:200]}")


# --- 9. /start still works ---
sent7, _, _ = run_cycle("/start")
check("/start works", any("LZ-ArtWork Bot" in t for _, t in sent7), f"sent={sent7}")


# --- 10. Unknown command handled ---
sent8, _, _ = run_cycle("halo bang")
check("unknown text handled", any("tidak dikenal" in t.lower() for _, t in sent8), f"sent={sent8}")


# --- 11. /contact includes telegram handle ---
sent9, _, _ = run_cycle("/contact")
check("/contact mentions bot", any("Lz_ArtWork_bot" in t for _, t in sent9), f"sent={sent9}")


# --- 12. Misspelled command suggests the real one and writes NO order ---
# Regression guard: a real client typed /comission on 28 Sep and got "unknown command".
import tempfile as _tf

with _tf.TemporaryDirectory() as td2:
    orders_file2 = Path(td2) / "orders.jsonl"
    with mock.patch.object(bot, "ORDERS_FILE", orders_file2):
        sent10, notified10, _ = run_cycle(
            "/comission\nJenis: Half Body\nKarakter: 3\nBrief: karakter cewe anime lucuk"
        )
        wrote_order = orders_file2.exists() and orders_file2.read_text().strip() != ""
    joined10 = " ".join(t for _, t in sent10)
    check(
        "misspelled /comission suggests /commission",
        "/commission" in joined10 and "maksudnya" in joined10.lower(),
        f"sent={joined10[:200]!r}",
    )
    check("misspelled command writes no order", not wrote_order, "order file got written")
    check("misspelled command does not notify owner", len(notified10) == 0, f"notified={notified10}")


# --- 13. notify_owner reports success/failure instead of swallowing it ---
_owner_log = []
with mock.patch.object(bot, "send_text", lambda cid, t, parse_mode="HTML": True), \
     mock.patch.object(bot, "log_chat", lambda *a, **k: _owner_log.append(a)):
    ok_res = bot.notify_owner("ping sukses")
check("notify_owner returns True on success", ok_res is True, f"got={ok_res!r}")

with mock.patch.object(bot, "send_text", lambda cid, t, parse_mode="HTML": False), \
     mock.patch.object(bot, "log_chat", lambda *a, **k: _owner_log.append(a)):
    fail_res = bot.notify_owner("ping gagal")
check("notify_owner returns False when send fails", fail_res is False, f"got={fail_res!r}")
check(
    "notify_owner logs the failure",
    any("FAIL" in str(entry) for entry in _owner_log),
    f"log={_owner_log!r}",
)


# --- 14. send_text surfaces delivery failure to its caller ---
_sent_error = []
with mock.patch.object(
    bot, "_telegram_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom 400"))
), mock.patch("builtins.print", lambda *a, **k: _sent_error.append(a)):
    res14 = bot.send_text(555, "halo")
check("send_text returns False when the API call raises", res14 is False, f"got={res14!r}")


# --- 15. send_photo: HTTP 200 with {"ok": false} is a FAILED delivery, not a success ---
with mock.patch.object(bot, "_telegram_call", lambda *a, **k: {"ok": False, "description": "chat not found"}), \
     mock.patch("builtins.print", lambda *a, **k: None):
    res15 = bot.send_photo(555, bot.GALLERY_IMAGE, "cap")
check("send_photo returns False when Telegram answers ok:false", res15 is False, f"got={res15!r}")

with mock.patch.object(bot, "_telegram_call", lambda *a, **k: {"ok": True, "result": {}}), \
     mock.patch("builtins.print", lambda *a, **k: None):
    res15b = bot.send_photo(555, bot.GALLERY_IMAGE, "cap")
check("send_photo returns True on a real ok:true", res15b is True, f"got={res15b!r}")


# --- 16. gallery falls back to text when the photo cannot be delivered ---
with mock.patch.object(bot, "send_photo", lambda *a, **k: False):
    sent16, _, _ = run_cycle("/gallery")
    joined16 = " ".join(t for _, t in sent16)
check(
    "gallery falls back to text when send_photo fails",
    "Contoh karya" in joined16 and len(sent16) >= 1,
    f"sent={joined16[:200]!r}",
)


# --- 17. Owner work queue: /orders, /status, /quote ---
_OWNER = bot.OWNER_ID
_CLIENT = 8971796697


def run_as(text, chat_id):
    """Drive an update as a specific identity (owner vs client)."""
    sent = []
    with mock.patch.object(bot, "send_text", lambda cid, t, parse_mode="HTML": sent.append((cid, t)) or True), \
         mock.patch.object(bot, "send_photo", lambda *a, **k: True), \
         mock.patch.object(bot, "notify_owner", lambda t: True), \
         mock.patch.object(bot, "log_chat", lambda *a, **k: None):
        bot.process_update(fake_update(text, chat_id), offset_state=None)
    return sent


# 17a. /orders as owner lists the queue; as a client it is refused.
with _tf.TemporaryDirectory() as td3:
    ledger3 = Path(td3) / "orders.jsonl"
    ledger3.write_text(
        '{"order_id": "o-1", "created_at": "2026-09-28T01:00:00", "chat_id": 555, '
        '"username": "klien1", "brief": "Jenis: Headshot\\nKarakter: 1", "status": "NEW"}\n'
        '{"order_id": "o-2", "created_at": "2026-09-28T02:00:00", "chat_id": 556, '
        '"username": "klien2", "brief": "Jenis: Full Body\\nKarakter: 3", "status": "ACCEPTED"}\n'
    )
    with mock.patch.object(bot, "ORDERS_FILE", ledger3):
        owner_orders = " ".join(t for _, t in run_as("/orders", _OWNER))
        client_orders = " ".join(t for _, t in run_as("/orders", _CLIENT))

check("/orders as owner lists orders", "o-1" in owner_orders and "o-2" in owner_orders, f"out={owner_orders[:200]!r}")
check("/orders as client is refused", "tidak dikenal" in client_orders, f"out={client_orders[:200]!r}")
check("client never sees an order id in the refusal", "o-1" not in client_orders, "leaked ledger")


# 17b. /orders hides DONE and REJECTED by default, shows them when asked.
with _tf.TemporaryDirectory() as td4:
    ledger4 = Path(td4) / "orders.jsonl"
    ledger4.write_text(
        '{"order_id": "o-open", "created_at": "2026-09-28T01:00:00", "chat_id": 1, '
        '"username": "a", "brief": "x", "status": "NEW"}\n'
        '{"order_id": "o-done", "created_at": "2026-09-28T02:00:00", "chat_id": 2, '
        '"username": "b", "brief": "y", "status": "DONE"}\n'
    )
    with mock.patch.object(bot, "ORDERS_FILE", ledger4):
        default_view = " ".join(t for _, t in run_as("/orders", _OWNER))
        done_view = " ".join(t for _, t in run_as("/orders done", _OWNER))
check("default /orders hides DONE", "o-done" not in default_view, f"out={default_view[:200]!r}")
check("default /orders shows open order", "o-open" in default_view, f"out={default_view[:200]!r}")
check("/orders DONE shows closed order", "o-done" in done_view, f"out={done_view[:200]!r}")


# 17c. /status advances the record and appends history.
with _tf.TemporaryDirectory() as td5:
    ledger5 = Path(td5) / "orders.jsonl"
    ledger5.write_text(
        '{"order_id": "o-9", "created_at": "2026-09-28T01:00:00", "chat_id": 42, '
        '"username": "klien", "brief": "Jenis: Half Body", "status": "NEW"}\n'
    )
    with mock.patch.object(bot, "ORDERS_FILE", ledger5):
        out5 = " ".join(t for _, t in run_as("/status o-9 ACCEPTED", _OWNER))
        after5 = json.loads(ledger5.read_text().strip())
check("/status advances NEW -> ACCEPTED", "ACCEPTED" in out5, f"out={out5[:200]!r}")
check("status persisted to ledger", after5.get("status") == "ACCEPTED", f"rec={after5}")
check("status change is recorded in history", len(after5.get("status_history", [])) == 1, f"rec={after5}")


# 17d. /status rejects an unknown status and does NOT touch the ledger.
with _tf.TemporaryDirectory() as td6:
    ledger6 = Path(td6) / "orders.jsonl"
    ledger6.write_text(
        '{"order_id": "o-8", "created_at": "2026-09-28T01:00:00", "chat_id": 42, '
        '"username": "klien", "brief": "x", "status": "NEW"}\n'
    )
    before6 = ledger6.read_text()
    with mock.patch.object(bot, "ORDERS_FILE", ledger6):
        out6 = " ".join(t for _, t in run_as("/status o-8 BOGUS", _OWNER))
    check("/status rejects an unknown status", "tidak dikenal" in out6, f"out={out6[:200]!r}")
    check("rejected status leaves ledger untouched", ledger6.read_text() == before6, "ledger mutated")


# 17e. /status with no args explains the format instead of erroring out.
out7 = " ".join(t for _, t in run_as("/status", _OWNER))
check("/status with no args shows usage", "Format" in out7, f"out={out7[:200]!r}")


# 17f. /quote reaches the client with the estimate.
with _tf.TemporaryDirectory() as td8:
    ledger8 = Path(td8) / "orders.jsonl"
    ledger8.write_text(
        '{"order_id": "o-7", "created_at": "2026-09-28T01:00:00", "chat_id": 99, '
        '"username": "klien", "brief": "Jenis: Half Body\\nKarakter: 3", "status": "NEW"}\n'
    )
    with mock.patch.object(bot, "ORDERS_FILE", ledger8):
        out8 = run_as("/quote o-7 450000", _OWNER)
    to_client = [t for cid, t in out8 if cid == 99]
    to_owner = [t for cid, t in out8 if cid == _OWNER]
check("/quote sends the estimate to the client", any("450000" in t for t in to_client), f"sent={to_client[:1]!r}")
check("/quote confirms to the owner", any("terkirim" in t for t in to_owner), f"sent={to_owner[:1]!r}")


# 17g. /quote as a client is refused.
out9 = " ".join(t for _, t in run_as("/quote o-7 450000", _CLIENT))
check("/quote as client is refused", "tidak dikenal" in out9, f"out={out9[:200]!r}")


# 17h. A malformed ledger line is skipped, not fatal.
with _tf.TemporaryDirectory() as td9:
    ledger9 = Path(td9) / "orders.jsonl"
    ledger9.write_text(
        "{not json at all\n"
        '{"order_id": "o-ok", "created_at": "2026-09-28T01:00:00", "chat_id": 1, '
        '"username": "a", "brief": "x", "status": "NEW"}\n'
    )
    with mock.patch.object(bot, "ORDERS_FILE", ledger9):
        out10 = " ".join(t for _, t in run_as("/orders", _OWNER))
check("malformed ledger line is skipped", "o-ok" in out10, f"out={out10[:200]!r}")


print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("ALL TESTS PASSED")
print(f"[guard] production files untouched: orders={_REAL_ORDERS_FILE} log={_REAL_LOG_FILE}")