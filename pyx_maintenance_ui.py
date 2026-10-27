"""Lightweight public/preview HTML for PYX Mission Control (no JS, no assets)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from html import escape
import math
from pyx_maintenance import MaintenanceStatus

WIB = timezone(timedelta(hours=7))


def _clock(seconds: float) -> str:
    total = max(0, math.ceil(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, sec = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{sec:02}"


def render_maintenance_html(state: MaintenanceStatus, *, now: float, preview: bool = False) -> str:
    """Escapes all public messages. Fragments refresh countdown without reloading engine."""
    active = state.phase == 'active'
    target = state.until_ts if active else state.starts_ts
    countdown = _clock(target - now)
    title = 'Sampai Jumpa Lagi.' if active else 'Pemeliharaan Segera Dimulai'
    eyebrow = 'PLANNED MAINTENANCE' if active else 'MAINTENANCE NOTICE'
    intro = ('AutoTimestamp sedang ditingkatkan untuk pengalaman yang lebih stabil.' if active
             else 'Simpan pekerjaan dan selesaikan proses yang sedang berjalan sebelum waktu pemeliharaan.')
    date_str = datetime.fromtimestamp(target, tz=WIB).strftime('%d %b %Y · %H:%M WIB')
    safe_message = escape(state.message, quote=True)
    mode = 'preview' if preview else 'public'
    return f"""
<style>
.pyx-mission-page {{ position:relative; isolation:isolate; overflow:hidden; border-radius:26px;
  background: radial-gradient(circle at 15% 16%,#183566 0,transparent 42%),
              radial-gradient(circle at 96% 90%,#0a4463 0,transparent 34%), #071122;
  border:1px solid #223c61; color:#eef5ff; font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif;
  box-shadow:0 20px 65px rgba(2,8,23,.25); padding:clamp(22px,5vw,52px); }}
.pyx-mission-page * {{box-sizing:border-box;}}
.pyx-mission-header {{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;}}
.pyx-mission-mark {{display:flex;align-items:center;gap:12px;}}
.pyx-mission-logo {{display:grid;place-items:center;width:43px;height:43px;border-radius:14px;
  color:#aee6ff;font-size:23px;background:linear-gradient(130deg,#214b88,#102740);
  border:1px solid #3b75b6;}}
.pyx-mission-brand {{font-size:14px;font-weight:850;letter-spacing:.06em;}}
.pyx-mission-sub {{font-size:11px;color:#97acc9;letter-spacing:.08em;margin-top:3px;}}
.pyx-mission-badge {{padding:8px 13px;border:1px solid #88653a;color:#ffdda0;
  background:#45331b88;border-radius:40px;font-size:11px;font-weight:800;letter-spacing:.1em;}}
.pyx-mission-center {{text-align:center;max-width:810px;margin:40px auto 31px;}}
.pyx-mission-symbol {{display:grid;place-items:center;margin:0 auto 20px;width:76px;height:76px;
  background:linear-gradient(145deg,#1e4875,#0b1b34);border-radius:24px;border:1px solid #3d80b9;
  font-size:38px;box-shadow:0 15px 45px #040e22;}}
.pyx-mission-eyebrow {{font-weight:850;letter-spacing:.2em;color:#6ed6ff;font-size:11px;}}
.pyx-mission-title {{font-size:clamp(29px,5vw,50px);font-weight:900;letter-spacing:-.055em;
  line-height:1.08;margin:12px auto 12px;color:#f8fbff;}}
.pyx-mission-intro {{font-size:clamp(14px,2vw,17px);line-height:1.7;color:#acc3e0;margin:0 auto 14px;}}
.pyx-mission-message {{font-size:14px;line-height:1.7;color:#dce8f8;overflow-wrap:anywhere;white-space:normal;}}
.pyx-mission-panel {{max-width:650px;margin:0 auto;padding:24px;border-radius:20px;background:#13233aaf;
 border:1px solid #355073;text-align:center;}}
.pyx-mission-countlabel {{font-size:11px;letter-spacing:.18em;color:#92accb;font-weight:800;}}
.pyx-mission-count {{font-variant-numeric:tabular-nums;font-weight:900;font-size:clamp(37px,7vw,65px);
 letter-spacing:.09em;line-height:1.5;color:#f3f8ff;}}
.pyx-mission-date {{font-size:13px;color:#b8d4f3;}}
.pyx-mission-rule {{height:4px;margin-top:19px;border-radius:8px;background:linear-gradient(90deg,#1e78c4,#4bbdf0,#a2e7ff);opacity:.8;}}
.pyx-mission-footer {{display:flex;justify-content:center;align-items:center;gap:8px;text-align:center;
 margin-top:27px;font-size:12px;line-height:1.6;color:#9fb6d3;}}
.pyx-mission-dot {{display:inline-block;width:8px;height:8px;background:#38d5b3;border-radius:50%;box-shadow:0 0 12px #38d5b36e;}}
.pyx-mission-page.pyx-preview {{padding:22px;border-radius:18px;}}
.pyx-preview .pyx-mission-center {{margin:21px auto 19px;}}
.pyx-preview .pyx-mission-symbol {{width:45px;height:45px;font-size:23px;border-radius:13px;margin-bottom:10px;}}
.pyx-preview .pyx-mission-title {{font-size:27px;}}
.pyx-preview .pyx-mission-panel {{padding:12px;}}
.pyx-preview .pyx-mission-count {{font-size:33px;}}
@media(max-width:600px){{ .pyx-mission-page {{padding:20px 16px;border-radius:18px;}}
 .pyx-mission-badge {{font-size:9px;}} .pyx-mission-center {{margin:26px auto 20px;}} }}
</style>
<section class="pyx-mission-page pyx-{mode}" aria-label="Status pemeliharaan AutoTimestamp">
 <div class="pyx-mission-header">
  <div class="pyx-mission-mark"><div class="pyx-mission-logo">✦</div>
   <div><div class="pyx-mission-brand">PYX SOLUSI TEKNOLOGI</div>
    <div class="pyx-mission-sub">AUTOTIMESTAMP STUDIO</div></div></div>
  <div class="pyx-mission-badge">● {eyebrow}</div>
 </div>
 <div class="pyx-mission-center"><div class="pyx-mission-symbol">⚙</div>
  <div class="pyx-mission-eyebrow">SYSTEM EXPERIENCE UPGRADE</div>
  <div class="pyx-mission-title">{title}</div>
  <p class="pyx-mission-intro">{intro}</p>
  <div class="pyx-mission-message">{safe_message}</div>
 </div>
 <div class="pyx-mission-panel">
  <div class="pyx-mission-countlabel">{'PERKIRAAN AKSES DIBUKA' if active else 'MAINTENANCE DIMULAI DALAM'}</div>
  <div class="pyx-mission-count" role="timer" aria-label="Hitung mundur">{countdown}</div>
  <div class="pyx-mission-date">{date_str}</div>
  <div class="pyx-mission-rule"></div>
 </div>
 <div class="pyx-mission-footer"><span class="pyx-mission-dot"></span>
  Status diperiksa otomatis selama browser terhubung · Tidak perlu refresh manual</div>
</section>
"""
