import sys
from datetime import datetime, timedelta
import pytz
import swisseph as swe

# --- Configuration ---
IST = pytz.timezone("Asia/Kolkata")
swe.set_sid_mode(swe.SIDM_LAHIRI)
FLAGS = swe.FLG_SIDEREAL | swe.FLG_SPEED

RASHIS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta",
    "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

PLANETS = [
    ("Sun", swe.SUN),
    ("Moon", swe.MOON),
    ("Mars", swe.MARS),
    ("Mercury", swe.MERCURY),
    ("Jupiter", swe.JUPITER),
    ("Venus", swe.VENUS),
    ("Saturn", swe.SATURN),
    ("Rahu", swe.TRUE_NODE),
]

ASPECTS = [
    ("Conjunction", 0, 3.0),
    ("Semi-sextile", 30, 1.5),
    ("Semi-square", 45, 1.5),
    ("Sextile", 60, 2.5),
    ("Square", 90, 3.0),
    ("Trine", 120, 3.0),
    ("Quincunx", 150, 1.5),
    ("Opposition", 180, 3.0),
]

# Planetary drivers mapped to your tracked instruments
INSTRUMENT_PLANETS = {
    "NIFTY": {"Sun", "Moon", "Mercury", "Jupiter", "Saturn", "Rahu", "Ketu"},
    "HAL": {"Sun", "Mars", "Saturn", "Rahu", "Ketu", "Mercury"},
    "CRUDEOIL": {"Mars", "Saturn", "Rahu", "Ketu", "Moon", "Venus"},
}


def to_jd(dt_ist: datetime) -> float:
    dt_utc = dt_ist.astimezone(pytz.UTC)
    return swe.julday(
        dt_utc.year, dt_utc.month, dt_utc.day,
        dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    )


def get_positions(jd: float) -> dict:
    pos = {}
    for name, pid in PLANETS:
        xx, _ = swe.calc_ut(jd, pid, FLAGS)
        pos[name] = (xx[0] % 360.0, xx[3])
    rahu_lon, rahu_spd = pos["Rahu"]
    pos["Ketu"] = ((rahu_lon + 180.0) % 360.0, rahu_spd)
    return pos


def zodiac_details(lon: float) -> dict:
    rashi_idx = int(lon // 30)
    deg_in_sign = lon % 30.0
    d9_idx = int((lon // (30.0 / 9.0)) % 12)
    nak_span = 360.0 / 27.0
    nak_idx = int(lon // nak_span)
    pada = int((lon % nak_span) // (nak_span / 4.0)) + 1
    return {
        "rashi": RASHIS[rashi_idx],
        "deg": deg_in_sign,
        "d9": RASHIS[d9_idx],
        "nak": NAKSHATRAS[nak_idx],
        "pada": pada,
    }


def ang_diff(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def next_nse_trading_day(now_ist: datetime) -> datetime:
    target = now_ist.date() + timedelta(days=1)
    while target.weekday() >= 5:  # Skip Saturday (5) & Sunday (6)
        target += timedelta(days=1)
    return IST.localize(datetime(target.year, target.month, target.day, 9, 15))


def analyze_session(session_start: datetime) -> str:
    jd_open = to_jd(session_start)
    jd_open_next = jd_open + (1.0 / 1440.0)
    pos_open = get_positions(jd_open)
    pos_next = get_positions(jd_open_next)
    planet_names = list(pos_open.keys())

    # 1. Minute-by-minute scan (09:15 to 15:30 IST = 375 mins) for ingresses & exact aspect peaks
    ingresses = []
    exact_peaks = {}
    prev_pos = pos_open
    prev_det = {p: zodiac_details(pos_open[p][0]) for p in planet_names}

    for minute in range(1, 376):
        t = session_start + timedelta(minutes=minute)
        jd_t = to_jd(t)
        curr_pos = get_positions(jd_t)
        curr_det = {p: zodiac_details(curr_pos[p][0]) for p in planet_names}
        ts = t.strftime("%H:%M IST")

        for p in planet_names:
            if curr_det[p]["rashi"] != prev_det[p]["rashi"]:
                ingresses.append((ts, p, "D1 Rashi", f"{prev_det[p]['rashi']} -> {curr_det[p]['rashi']}"))
            if curr_det[p]["d9"] != prev_det[p]["d9"]:
                ingresses.append((ts, p, "D9 Navamsa", f"{prev_det[p]['d9']} -> {curr_det[p]['d9']}"))
            if curr_det[p]["nak"] != prev_det[p]["nak"]:
                ingresses.append((ts, p, "Nakshatra", f"{prev_det[p]['nak']} -> {curr_det[p]['nak']}"))
            elif curr_det[p]["pada"] != prev_det[p]["pada"]:
                ingresses.append((ts, p, "Pada", f"{curr_det[p]['nak']} P{prev_det[p]['pada']} -> P{curr_det[p]['pada']}"))

        # Track intraday exact aspect crossings
        for i in range(len(planet_names)):
            for j in range(i + 1, len(planet_names)):
                p1, p2 = planet_names[i], planet_names[j]
                if {p1, p2} == {"Rahu", "Ketu"}:
                    continue
                d_prev = ang_diff(prev_pos[p1][0], prev_pos[p2][0])
                d_curr = ang_diff(curr_pos[p1][0], curr_pos[p2][0])
                for asp_name, angle, _ in ASPECTS:
                    if (d_prev - angle) * (d_curr - angle) <= 0 and abs(d_curr - angle) < 0.25:
                        exact_peaks[(p1, p2, asp_name)] = ts

        prev_pos, prev_det = curr_pos, curr_det

    # 2. Evaluate aspects at 09:15 IST open
    active_aspects = []
    for i in range(len(planet_names)):
        for j in range(i + 1, len(planet_names)):
            p1, p2 = planet_names[i], planet_names[j]
            if {p1, p2} == {"Rahu", "Ketu"}:
                continue
            d0 = ang_diff(pos_open[p1][0], pos_open[p2][0])
            d1 = ang_diff(pos_next[p1][0], pos_next[p2][0])
            for asp_name, angle, max_orb in ASPECTS:
                orb0 = abs(d0 - angle)
                orb1 = abs(d1 - angle)
                if orb0 <= max_orb or (p1, p2, asp_name) in exact_peaks:
                    peak_ts = exact_peaks.get((p1, p2, asp_name), "—")
                    if orb0 <= 0.05 or peak_ts != "—":
                        phase = "EXACT"
                    elif orb1 < orb0:
                        phase = "APPLYING"
                    else:
                        phase = "SEPARATING"
                    active_aspects.append({
                        "pair": f"{p1} - {p2}",
                        "p1": p1,
                        "p2": p2,
                        "aspect": f"{asp_name} ({angle}°)",
                        "orb": orb0,
                        "phase": phase,
                        "peak": peak_ts,
                    })

    active_aspects.sort(key=lambda x: (x["phase"] == "SEPARATING", x["orb"]))

    # 3. Build Markdown output
    date_str = session_start.strftime("%Y-%m-%d (%A)")
    lines = [
        f"# Swiss Ephemeris NSE Pre-Market Data — {date_str}",
        "",
        "- **Calculation Basis:** Swiss Ephemeris | Sidereal Lahiri (Chitrapaksha) | True Nodes (Rahu/Ketu)",
        "- **Location & Window:** NSE Mumbai (19.0760° N, 72.8777° E) | 09:15 IST to 15:30 IST",
        f"- **Generated At:** {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}",
        "",
        "## 1. Instrument Aspect Summary (Applying & Exact Only)",
        "",
        "| Instrument | Planetary Pair | Aspect | 09:15 Orb | Phase (Effect) | Intraday Exact Peak |",
        "|---|---|---|---:|---|---|",
    ]

    for inst, drivers in INSTRUMENT_PLANETS.items():
        matches = [
            a for a in active_aspects
            if a["phase"] in ("APPLYING", "EXACT")
            and (a["p1"] in drivers and a["p2"] in drivers)
        ]
        if not matches:
            lines.append(f"| **{inst}** | None within orb | — | — | — | — |")
        for a in matches:
            eff = "EXACT (Peak)" if a["phase"] == "EXACT" else "APPLYING (Increasing)"
            lines.append(
                f"| **{inst}** | {a['pair']} | {a['aspect']} | {a['orb']:.2f}° | {eff} | {a['peak']} |"
            )

    lines += [
        "",
        "## 2. Planetary Positions at NSE Open (09:15 IST)",
        "",
        "| Planet | Sidereal Lon | D1 Rashi & Deg | D9 Navamsa | Nakshatra (Pada) | Daily Speed | Motion |",
        "|---|---:|---|---|---|---:|---|",
    ]
    for p in planet_names:
        lon, spd = pos_open[p]
        d = zodiac_details(lon)
        motion = "Retrograde (R)" if spd < 0 else "Direct"
        lines.append(
            f"| **{p}** | {lon:.4f}° | {d['rashi']} {d['deg']:.2f}° | {d['d9']} | {d['nak']} (P{d['pada']}) | {spd:+.4f}°/d | {motion} |"
        )

    lines += [
        "",
        "## 3. Intraday Ingresses & Transitions (09:15–15:30 IST)",
        "",
    ]
    if ingresses:
        lines += ["| Time (IST) | Planet | Transition Type | Change |", "|---|---|---|---|"]
        for ts, p, kind, chg in ingresses:
            lines.append(f"| {ts} | **{p}** | {kind} | {chg} |")
    else:
        lines.append("No planetary D1, D9, or Nakshatra/Pada changes during market hours.")

    lines += [
        "",
        "## 4. Full Active Planetary Aspects (All Phases)",
        "",
        "| Pair | Aspect | 09:15 Orb | Phase | Intraday Exact Peak |",
        "|---|---|---:|---|---|",
    ]
    for a in active_aspects:
        lines.append(
            f"| {a['pair']} | {a['aspect']} | {a['orb']:.2f}° | **{a['phase']}** | {a['peak']} |"
        )

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        dt = datetime.strptime(sys.argv[1], "%Y-%m-%d")
        session_start = IST.localize(datetime(dt.year, dt.month, dt.day, 9, 15))
    else:
        session_start = next_nse_trading_day(datetime.now(IST))

    report = analyze_session(session_start)
    with open("daily_ephemeris.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Generated daily_ephemeris.md for {session_start.strftime('%Y-%m-%d')}")
