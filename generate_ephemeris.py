import sys
from datetime import date, datetime, timedelta
import pytz
import swisseph as swe

# --- Configuration ---
IST = pytz.timezone("Asia/Kolkata")
swe.set_sid_mode(swe.SIDM_LAHIRI)
FLAGS = swe.FLG_SIDEREAL | swe.FLG_SPEED

DEFAULT_START = date(2026, 11, 25)
DEFAULT_END = date(2027, 11, 30)
OUTPUT_FILE = "nse_ephemeris_2026_2027.md"

RASHIS = [
    "Ari", "Tau", "Gem", "Can", "Leo", "Vir",
    "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"
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
    ("Conj", 0, 3.0),
    ("Semi-sext", 30, 1.5),
    ("Semi-sq", 45, 1.5),
    ("Sextile", 60, 2.5),
    ("Square", 90, 3.0),
    ("Trine", 120, 3.0),
    ("Quincunx", 150, 1.5),
    ("Opp", 180, 3.0),
]

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


def analyze_session(session_start: datetime) -> str:
    jd_open = to_jd(session_start)
    jd_open_next = jd_open + (1.0 / 1440.0)
    pos_open = get_positions(jd_open)
    pos_next = get_positions(jd_open_next)
    planet_names = list(pos_open.keys())

    # Track minute-by-minute ingresses and exact aspect peaks (09:15 to 15:30 IST)
    ingresses = []
    min_orb_tracker = {}  # (p1, p2, asp_name) -> (min_orb, timestamp_str)

    # Pre-filter candidate pairs within 5 degrees at open to keep 1-year run fast
    candidate_pairs = []
    for i in range(len(planet_names)):
        for j in range(i + 1, len(planet_names)):
            p1, p2 = planet_names[i], planet_names[j]
            if {p1, p2} == {"Rahu", "Ketu"}:
                continue
            d0 = ang_diff(pos_open[p1][0], pos_open[p2][0])
            for asp_name, angle, max_orb in ASPECTS:
                orb0 = abs(d0 - angle)
                if orb0 <= max(max_orb, 4.5):
                    candidate_pairs.append((p1, p2, asp_name, angle, max_orb))
                    min_orb_tracker[(p1, p2, asp_name)] = (orb0, "09:15 IST")

    prev_det = {p: zodiac_details(pos_open[p][0]) for p in planet_names}

    for minute in range(1, 376):
        t = session_start + timedelta(minutes=minute)
        jd_t = to_jd(t)
        curr_pos = get_positions(jd_t)
        curr_det = {p: zodiac_details(curr_pos[p][0]) for p in planet_names}
        ts = t.strftime("%H:%M IST")

        for p in planet_names:
            if curr_det[p]["rashi"] != prev_det[p]["rashi"]:
                ingresses.append(f"{ts} {p} D1 {prev_det[p]['rashi']}->{curr_det[p]['rashi']}")
            if curr_det[p]["d9"] != prev_det[p]["d9"]:
                ingresses.append(f"{ts} {p} D9 {prev_det[p]['d9']}->{curr_det[p]['d9']}")
            if curr_det[p]["nak"] != prev_det[p]["nak"]:
                ingresses.append(f"{ts} {p} Nak {prev_det[p]['nak']}->{curr_det[p]['nak']}")
            elif curr_det[p]["pada"] != prev_det[p]["pada"]:
                ingresses.append(f"{ts} {p} Pada {curr_det[p]['nak']} P{prev_det[p]['pada']}->P{curr_det[p]['pada']}")

        for p1, p2, asp_name, angle, _ in candidate_pairs:
            orb = abs(ang_diff(curr_pos[p1][0], curr_pos[p2][0]) - angle)
            key = (p1, p2, asp_name)
            if orb < min_orb_tracker[key][0]:
                min_orb_tracker[key] = (orb, ts)

        prev_det = curr_det

    # Evaluate aspects at 09:15 IST open
    active_aspects = []
    for p1, p2, asp_name, angle, max_orb in candidate_pairs:
        d0 = ang_diff(pos_open[p1][0], pos_open[p2][0])
        d1 = ang_diff(pos_next[p1][0], pos_next[p2][0])
        orb0 = abs(d0 - angle)
        orb1 = abs(d1 - angle)
        min_orb, peak_ts = min_orb_tracker[(p1, p2, asp_name)]
        hits_exact = min_orb <= 0.02

        if orb0 <= max_orb or hits_exact:
            if hits_exact:
                phase = "EXACT"
                peak_str = peak_ts
            elif orb1 < orb0:
                phase = "APPLYING"
                peak_str = "—"
            else:
                phase = "SEPARATING"
                peak_str = "—"
            active_aspects.append({
                "pair": f"{p1}-{p2}",
                "p1": p1,
                "p2": p2,
                "aspect": f"{asp_name} {angle}°",
                "orb": orb0,
                "phase": phase,
                "peak": peak_str,
            })

    active_aspects.sort(key=lambda x: (x["phase"] == "SEPARATING", x["orb"]))

    # Compact per-day Markdown block
    date_str = session_start.strftime("%Y-%m-%d (%a)")
    lines = [f"## {date_str}"]

    # 1. Instrument Aspect Summary (Applying & Exact only)
    inst_lines = []
    for inst, drivers in INSTRUMENT_PLANETS.items():
        matches = [
            f"{a['pair']} {a['aspect']} ({a['orb']:.2f}°, {a['phase']}"
            + (f" @{a['peak']})" if a["peak"] != "—" else ")")
            for a in active_aspects
            if a["phase"] in ("APPLYING", "EXACT")
            and (a["p1"] in drivers and a["p2"] in drivers)
        ]
        inst_lines.append(f"**{inst}:** " + ("; ".join(matches) if matches else "None"))
    lines.append("- **Instrument Summary (Applying/Exact):** " + " | ".join(inst_lines))

    # 2. Planetary Positions (09:15 IST)
    lines.append("| Planet | Lon | D1 | D9 | Nakshatra | Speed |")
    lines.append("|---|---:|---|---|---|---:|")
    for p in planet_names:
        lon, spd = pos_open[p]
        d = zodiac_details(lon)
        r_tag = " (R)" if spd < 0 else ""
        lines.append(
            f"| {p} | {lon:.2f}° | {d['rashi']} {d['deg']:.2f}° | {d['d9']} | {d['nak']} P{d['pada']} | {spd:+.3f}°{r_tag} |"
        )

    # 3. Intraday Ingresses
    lines.append("- **Intraday Ingresses (09:15–15:30 IST):** " + ("; ".join(ingresses) if ingresses else "None"))

    # 4. All Active Aspects
    all_asp = [
        f"{a['pair']} {a['aspect']} ({a['orb']:.2f}°, {a['phase']}"
        + (f" @{a['peak']})" if a["peak"] != "—" else ")")
        for a in active_aspects
    ]
    lines.append("- **All Aspects:** " + ("; ".join(all_asp) if all_asp else "None"))
    lines.append("")
    return "\n".join(lines)


def main():
    if len(sys.argv) >= 3:
        start_d = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        end_d = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    else:
        start_d, end_d = DEFAULT_START, DEFAULT_END

    header = [
        f"# Swiss Ephemeris NSE 1-Year Master Calendar ({start_d} to {end_d})",
        "",
        "- **Basis:** Swiss Ephemeris | Sidereal Lahiri (Chitrapaksha) | True Nodes (Rahu/Ketu)",
        "- **Location & Window:** NSE Mumbai (19.0760° N, 72.8777° E) | 09:15–15:30 IST (Mon–Fri)",
        "- **Aspect Phase Rule:** APPLYING = Increasing effect | EXACT = Peak effect | SEPARATING = Decreasing effect",
        f"- **Generated At:** {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}",
        "",
    ]

    blocks = ["\n".join(header)]
    curr = start_d
    day_count = 0
    while curr <= end_d:
        if curr.weekday() < 5:  # Mon-Fri
            session_start = IST.localize(datetime(curr.year, curr.month, curr.day, 9, 15))
            blocks.append(analyze_session(session_start))
            day_count += 1
        curr += timedelta(days=1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    print(f"Generated {OUTPUT_FILE} with {day_count} NSE trading days ({start_d} to {end_d}).")


if __name__ == "__main__":
    main()
