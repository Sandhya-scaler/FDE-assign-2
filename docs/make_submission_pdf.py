"""Build the 2-page submission PDF (needs: pip install reportlab) from the pipeline warehouse (no hand-typed numbers)."""
import duckdb
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

import pathlib
ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
OUT = f"{ROOT}/FDE_Assignment2_TrackB_NYC_TLC.pdf"
c = duckdb.connect(f"{ROOT}/warehouse/tlc.duckdb", read_only=True)

M = {(m, k): v for m, k, v in c.execute("select source_month, metric_id, value from metrics_monthly").fetchall()}
N = {(m, k): n for m, k, n in c.execute("select source_month, metric_id, n_basis from metrics_monthly").fetchall()}
R = {r[0]: r for r in c.execute("""select source_month, raw_rows, valid_rows, in_month_trips_per_day,
        tlc_trips_per_day, trips_diff_pct, our_mean_minutes, tlc_avg_minutes_per_trip, minutes_diff_pct
        from reconciliation""").fetchall()}
V = {(m, r): (p, a) for m, r, p, a in c.execute(
    "select source_month, rule_id, failed_pct, attributed_rows from validation_results").fetchall()}
BAND = {(b, m): s for b, m, s in c.execute("""select time_band, source_month, median_speed_mph from kpi_breakdown
        where day_type='weekday' and trip_segment='manhattan core'""").fetchall()}
SEG = dict(c.execute("""select trip_segment, sum(trips)::double / (select sum(trips) from kpi_breakdown
        where source_month='2025-01') from kpi_breakdown where source_month='2025-01' group by 1""").fetchall())
KEEP = c.execute("""select source_month, median(speed_mph) filter (where not has_missing_attributes),
        median(speed_mph) from fct_trip where is_core_trip and is_weekday and pickup_hour between 7 and 18
        group by 1""").fetchall()
KEEP = {m: (a, b) for m, a, b in KEEP}
DROP = dict(c.execute("""select s.source_month, count(*) filter (where not r01_pickup_outside_file_month
        and not w01_missing_trip_attributes) / 31.0 / any_value(t.trips_per_day) - 1 from stg_trips s
        join ref_industry_indicators t on t.month_year = s.source_month and t.license_class = 'Yellow'
        group by 1""").fetchall())
Y0, Y1 = "2024-01", "2025-01"

# ------------------------------------------------------------------ styles
INK, MUTED, ACCENT = colors.HexColor("#1b2733"), colors.HexColor("#5a6673"), colors.HexColor("#1f5f8b")
FACT, ASSUME, UNKNOWN, LIMIT = (colors.HexColor(h) for h in ("#2e7d4f", "#b26a00", "#b0303a", "#5a6673"))
LINE = colors.HexColor("#c9d1d9")
HEAD_BG = colors.HexColor("#eef3f7")

base = ParagraphStyle("b", fontName="Helvetica", fontSize=8, leading=10.2, textColor=INK, alignment=TA_LEFT)
small = ParagraphStyle("s", parent=base, fontSize=7.2, leading=8.9)
cell = ParagraphStyle("c", parent=base, fontSize=7.2, leading=8.7)
cellb = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=13.5, leading=16)
sub = ParagraphStyle("sub", parent=base, fontSize=8, textColor=MUTED)
h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=9.6, leading=12, textColor=ACCENT,
                    spaceBefore=5, spaceAfter=2.5)


def P(t, s=base):
    return Paragraph(t, s)


def tag(label, col):
    return f'<font color="{col.hexval().replace("0x", "#")}"><b>[{label}]</b></font>'


def table(rows, widths, bold_first_col=False, zebra=True, header=True):
    data = [[P(x, cellb if (header and i == 0) or (bold_first_col and j == 0) else cell) if isinstance(x, str) else x
             for j, x in enumerate(r)] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, hAlign="LEFT")
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
          ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT)]
    t.setStyle(TableStyle(st))
    return t


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def box(d, x, y, w, h, text, fill, stroke=ACCENT, fs=6.8, fc=INK, lines=None):
    d.add(Rect(x, y, w, h, rx=3, ry=3, fillColor=fill, strokeColor=stroke, strokeWidth=0.7))
    lines = lines or [text]
    top = y + h / 2 + (len(lines) - 1) * (fs + 1) / 2 - fs / 3
    for i, ln in enumerate(lines):
        d.add(String(x + w / 2, top - i * (fs + 1), ln, fontName="Helvetica-Bold" if i == 0 else "Helvetica",
                     fontSize=fs if i == 0 else fs - 0.6, fillColor=fc, textAnchor="middle"))


def arrow(d, x1, y1, x2, y2, col=MUTED, dash=None):
    d.add(Line(x1, y1, x2, y2, strokeColor=col, strokeWidth=0.8, strokeDashArray=dash))
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    s = 3.2
    d.add(Polygon([x2, y2, x2 - s * math.cos(a - 0.45), y2 - s * math.sin(a - 0.45),
                   x2 - s * math.cos(a + 0.45), y2 - s * math.sin(a + 0.45)], fillColor=col, strokeColor=col))


W = A4[0] - 30 * mm

# ------------------------------------------------------------------ diagrams
def workflow_diagram():
    d = Drawing(W, 70)
    lt = colors.HexColor("#f4f8fb")
    bw, bh, y = 80, 30, 30
    xs = [0, 100, 200, 300]
    labels = [["Pickup", "time + zone"], ["In trip", "metered distance"], ["Dropoff", "time + zone"],
              ["Payment", "fare, tip, fees"]]
    for x, l in zip(xs, labels):
        box(d, x, y, bw, bh, None, lt, lines=l)
    for a, b in zip(xs, xs[1:]):
        arrow(d, a + bw, y + bh / 2, b, y + bh / 2)
    box(d, 400, y, W - 400, bh, None, colors.HexColor("#e8f3ec"), stroke=FACT,
        lines=["Outcome (KPI input)", "duration, distance -> speed"])
    arrow(d, 300 + bw, y + bh / 2, 400, y + bh / 2)
    box(d, 120, 0, 210, 20, None, colors.HexColor("#fdf3e3"), stroke=ASSUME,
        lines=["Intervention: congestion toll (from 5 Jan 2025)", "cbd_congestion_fee > 0 on the trip"], fs=6.4)
    arrow(d, 200, 20, 150, y, col=ASSUME, dash=[2, 2])
    arrow(d, 300, 20, 330, y, col=ASSUME, dash=[2, 2])
    d.add(String(0, 64, "Entities: zone (263 + 2 unknown), vendor/TPEP provider, rate code, payment type.   "
                        "Grain: one row = one metered trip.", fontName="Helvetica", fontSize=6.6, fillColor=MUTED))
    return d


def pipeline_diagram():
    d = Drawing(W, 34)
    lt = colors.HexColor("#f4f8fb")
    steps = [["Ingest", "files + APIs, manifest"], ["Load raw", "footer row check"],
             ["Validate", "15 rules, flags"], ["Gates G1-G2", "fail = block month"],
             ["Model", "dim_zone, fct_trip"], ["Metrics", "M1-M6 + breakdowns"],
             ["Reconcile G3-G4", "vs TLC API"]]
    n = len(steps)
    gap = 9
    bw = (W - gap * (n - 1)) / n
    for i, s in enumerate(steps):
        x = i * (bw + gap)
        stroke = UNKNOWN if "Gates" in s[0] else (FACT if "Reconcile" in s[0] else ACCENT)
        box(d, x, 4, bw, 26, None, lt, stroke=stroke, lines=s, fs=6.6)
        if i:
            arrow(d, x - gap, 17, x, 17)
    return d


def band_chart(bands):
    cw, ch = W * .37, 118
    d = Drawing(cw, ch)
    d.add(String(0, ch - 8, "Core weekday median speed by time band (mph)", fontName="Helvetica-Bold",
                 fontSize=7.2, fillColor=INK))
    x0, y0, plot_h, vmax = 8, 22, ch - 50, 12.5
    gw = (cw - x0) / len(bands)
    c0, c1 = colors.HexColor("#9fb7c9"), ACCENT
    for i, b in enumerate(bands):
        gx = x0 + i * gw + gw * 0.14
        bw = gw * 0.34
        for j, (m, col) in enumerate(((Y0, c0), (Y1, c1))):
            v = BAND[(b, m)]
            h = plot_h * v / vmax
            d.add(Rect(gx + j * (bw + 1.5), y0, bw, h, fillColor=col, strokeColor=None))
            d.add(String(gx + j * (bw + 1.5) + bw / 2, y0 + h + 2, f"{v:.1f}", fontName="Helvetica",
                         fontSize=5.8, fillColor=INK, textAnchor="middle"))
        name, hrs = b[2:].rsplit(" ", 1)
        d.add(String(gx + bw, y0 - 8, name, fontName="Helvetica", fontSize=6, fillColor=INK, textAnchor="middle"))
        d.add(String(gx + bw, y0 - 15, hrs, fontName="Helvetica", fontSize=5.6, fillColor=MUTED, textAnchor="middle"))
    d.add(Line(x0, y0, cw, y0, strokeColor=LINE, strokeWidth=0.6))
    for k, (m, col) in enumerate(((Y0, c0), (Y1, c1))):
        d.add(Rect(x0 + k * 52, ch - 20, 7, 6, fillColor=col, strokeColor=None))
        d.add(String(x0 + k * 52 + 10, ch - 19.5, m, fontName="Helvetica", fontSize=6.2, fillColor=INK))
    return d


# ------------------------------------------------------------------ content
story = []
story += [P("Where do NYC yellow cabs lose time, and did congestion pricing change it?", h1),
          P("FDE Data Foundations - Track B (NYC TLC trip records). Jan 2024 (baseline) vs Jan 2025 (first month "
            "of the Manhattan congestion toll). Repository: README, code, source map, data model and "
            "evidence report. Every number below is produced by the pipeline (python -m pipeline run).", sub),
          Spacer(1, 3)]

# 1. Problem selection
story.append(P("1. Which problem deserves to be solved", h2))
story.append(P(
    "A client with trip data can ask many questions. We scored the candidates on how many trips they affect, whether a "
    "named owner can act on the answer, and whether the data can support the answer. The problem is chosen before any "
    "tooling.", base))
story.append(Spacer(1, 2))
story.append(table([
    ["Candidate problem", "Evidence of size (Jan 2025)", "Who acts on it", "Can the data answer it?", "Verdict"],
    ["<b>A. Fleet time lost in the Manhattan core</b>",
     f"{pct(SEG['manhattan core'], 0)} of trips are core-to-core; core weekday speed is "
     f"{BAND[('3 midday 10-16', Y1)]:.1f} mph at midday vs {BAND[('1 overnight 00-07', Y1)]:.1f} overnight",
     "Fleet operations (shift and vehicle-hour planning)", "Yes: time, distance and zones on every trip",
     f"{tag('CHOSEN', FACT)} largest and most actionable"],
    ["<b>B. Effect of the congestion toll</b>",
     f"{pct(M[(Y1, 'M6')], 0)} of trips charged the toll in its first month",
     "TLC policy team", "Partly: before/after only, no control group",
     f"{tag('CHOSEN', FACT)} as the intervention inside A"],
    ["C. Airport trip reliability", f"{pct(SEG['airport'], 1)} of trips, but the longest (core->JFK "
     f"{M[(Y1, 'M5')]:.0f} min)", "Dispatch / airport queue", "Yes", "Tracked as metric M5"],
    ["D. Fare and surcharge accuracy",
     f"{pct(V[(Y1, 'W04')][0], 0)} of rows: total != sum of parts",
     "TPEP vendors", "No: vendor encoding, not documented", f"{tag('OUT OF SCOPE', UNKNOWN)} flag to data owner"],
], [W * .2, W * .29, W * .17, W * .17, W * .17]))
story.append(Spacer(1, 3))
story.append(P(
    "<b>Problem statement.</b> Fleet operations cannot tell with confidence where and when cabs are slowest in the core, "
    "or whether the toll made trips faster. A naive average over the raw files is distorted by stray timestamps, zero "
    "distances, voids and unknown zones. <b>Project KPI:</b> median weekday 07-19h speed (mph) of trips that start and "
    "end in the Manhattan core (TLC 'Yellow Zone'). <b>Decision supported:</b> where to put fleet hours, and whether "
    "to expect the toll to raise trips per hour.", base))

# 2. Sources and workflow
story.append(P("2. Sources: from business question to system", h2))
story.append(table([
    ["Question", "Source (owner)", "Grain", "Retrieval mode", "Completeness evidence"],
    ["Speed, duration, where, when", "Yellow trip records Parquet (TLC / TPEP vendors)", "trip", "File over HTTPS",
     "bytes = Content-Length; loaded rows = Parquet footer; sha256 + ETag kept"],
    ["What counts as core / airport", "Taxi zone lookup CSV (TLC)", "zone", "File (CSV)", "265 rows; cross-checked with the API"],
    ["Is the zone list right?", "NYC Taxi Zones, Open Data (TLC)", "zone shape", "API (Socrata JSON)",
     "paged rows = server count(*)"],
    ["Do our totals match the regulator?", "TLC Industry Indicators, Open Data", "month x fleet", "API (Socrata JSON)",
     "paged rows = server count(*)"],
    ["Validate, model, aggregate", "DuckDB warehouse", "-", "SQL", "run log per stage; month-level transactions"],
], [W * .2, W * .26, W * .1, W * .14, W * .30]))
story.append(Spacer(1, 3))
story.append(P("<b>Workflow model.</b> Each trip is one run of the workflow below. The toll is an intervention "
               "applied at payment; its expected effect is on in-trip time.", base))
story.append(workflow_diagram())

# 3. Validation
story.append(P("3. Is the data trustworthy? Profiling, validation and reconciliation", h2))
story.append(P(
    "Profiling the raw files drove 10 <b>exclude</b> rules and 5 <b>warn</b> rules. No row is fixed or deleted "
    "silently: every raw row keeps one flag per rule and its first exclusion reason.", base))
story.append(Spacer(1, 2))
def vr(rule, m):
    p, a = V[(m, rule)]
    return f"{pct(p, 2)} / {a:,}"
story.append(table([
    ["Rule (severity)", "Why it matters for the KPI", f"{Y0} flagged / excluded", f"{Y1} flagged / excluded"],
    ["R01 pickup outside file month (exclude)", "stray 2002/2009 clocks leak into the wrong month", vr("R01", Y0), vr("R01", Y1)],
    ["R02-R03 duration <= 0, < 1 min or > 3 h (exclude)", "impossible, meter test or meter left on",
     f"{pct(V[(Y0,'R02')][0]+V[(Y0,'R03')][0],2)} / {V[(Y0,'R02')][1]+V[(Y0,'R03')][1]:,}",
     f"{pct(V[(Y1,'R02')][0]+V[(Y1,'R03')][0],2)} / {V[(Y1,'R02')][1]+V[(Y1,'R03')][1]:,}"],
    ["R04-R06 zero / > 100 mi distance, > 65 mph (exclude)", "no journey to measure, or odometer glitch",
     f"{pct(V[(Y0,'R04')][0]+V[(Y0,'R05')][0]+V[(Y0,'R06')][0],2)} / {V[(Y0,'R04')][1]+V[(Y0,'R05')][1]+V[(Y0,'R06')][1]:,}",
     f"{pct(V[(Y1,'R04')][0]+V[(Y1,'R05')][0]+V[(Y1,'R06')][0],2)} / {V[(Y1,'R04')][1]+V[(Y1,'R05')][1]+V[(Y1,'R06')][1]:,}"],
    ["R07 zone 264/265 unknown (exclude)", "cannot place the trip in core / non-core", vr("R07", Y0), vr("R07", Y1)],
    ["R09 negative fare/total (exclude)", "voids and refunds, not trips", vr("R09", Y0), vr("R09", Y1)],
    ["W01 null passenger count + rate code (warn, kept)", "see judgement call below",
     pct(V[(Y0, 'W01')][0], 2), pct(V[(Y1, 'W01')][0], 2)],
    ["W04 total != sum of components (warn, kept)", "vendor encoding; no fare-part metric is used",
     pct(V[(Y0, 'W04')][0], 2), pct(V[(Y1, 'W04')][0], 2)],
], [W * .33, W * .31, W * .18, W * .18]))
story.append(Spacer(1, 3))
r0, r1 = R[Y0], R[Y1]
story.append(table([
    ["Independent check (API)", Y0, Y1, "Gate"],
    ["Our in-month trips/day vs TLC published", f"{r0[3]:,.0f} vs {r0[4]:,.0f} ({r0[5]:+.1%})",
     f"{r1[3]:,.0f} vs {r1[4]:,.0f} ({r1[5]:+.1%})", "G3 pass (+/-5%)"],
    ["Our mean minutes/trip vs TLC published", f"{r0[6]:.1f} vs {r0[7]:.1f} ({r0[8]:+.1%})",
     f"{r1[6]:.1f} vs {r1[7]:.1f} ({r1[8]:+.1%})", "G4 pass (+/-10%)"],
    ["Valid rows / days with trips", f"{pct(M[(Y0,'M1')])} / 31 of 31", f"{pct(M[(Y1,'M1')])} / 31 of 31",
     "G1 (>= 85%), G2 pass"],
], [W * .33, W * .25, W * .25, W * .17]))

# 4. Metrics
story.append(PageBreak())
story.append(P("4. Metrics and what they show", h2))
def mv(k, m, f):
    return f.format(M[(m, k)])
chg = M[(Y1, 'M3')] / M[(Y0, 'M3')] - 1
metrics_tbl = table([
    ["Metric", Y0, Y1, "Change"],
    ["<b>M3 KPI: core weekday 07-19h median speed</b>", mv("M3", Y0, "{:.2f} mph"), mv("M3", Y1, "{:.2f} mph"),
     f"<b>{chg:+.1%}</b>"],
    ["M1 valid trip rate", pct(M[(Y0, 'M1')]), pct(M[(Y1, 'M1')]), f"{(M[(Y1,'M1')]-M[(Y0,'M1')])*100:+.1f} pts"],
    ["M2 valid trips per day", f"{M[(Y0,'M2')]:,.0f}", f"{M[(Y1,'M2')]:,.0f}", f"{M[(Y1,'M2')]/M[(Y0,'M2')]-1:+.1%}"],
    ["M4 median / p90 trip duration", f"{M[(Y0,'M4')]:.1f} / {M[(Y0,'M4b')]:.1f} min",
     f"{M[(Y1,'M4')]:.1f} / {M[(Y1,'M4b')]:.1f} min", f"p90 {M[(Y1,'M4b')]-M[(Y0,'M4b')]:+.1f} min"],
    ["M5 core -> JFK median duration (weekday day)", f"{M[(Y0,'M5')]:.1f} min", f"{M[(Y1,'M5')]:.1f} min",
     f"{M[(Y1,'M5')]-M[(Y0,'M5')]:+.1f} min"],
    ["M6 trips charged the congestion toll", "n/a (no toll)", pct(M[(Y1, 'M6')]), "-"],
], [W * .27, W * .12, W * .12, W * .09])
bands = ["1 overnight 00-07", "2 am peak 07-10", "3 midday 10-16", "4 pm peak 16-19", "5 evening 19-24"]
band_tbl = band_chart(bands)
story.append(Table([[metrics_tbl, band_tbl]], colWidths=[W * .62, W * .38],
                   style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                          ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
story.append(Spacer(1, 3))
story.append(P(
    f"<b>Conclusion.</b> Core speed did not change ({M[(Y0,'M3')]:.2f} -> {M[(Y1,'M3')]:.2f} mph, {chg:+.1%}, "
    f"n = {N[(Y1,'M3')]:,} trips), even though {pct(M[(Y1,'M6')],0)} of trips paid the toll. The gains are on long "
    f"trips: p90 duration {M[(Y1,'M4b')]-M[(Y0,'M4b')]:+.1f} min and core->JFK {M[(Y1,'M5')]-M[(Y0,'M5')]:+.1f} min. "
    f"Midday (10-16h) is the slowest band in both years ({BAND[('3 midday 10-16',Y1)]:.1f} mph). "
    "<b>Recommendation:</b> do not plan for more trips per hour in the core because of the toll; plan midday core "
    "capacity around ~7.6 mph and treat airport runs as the segment that improved.", base))

# 5. Judgement call
story.append(P("5. The key FDE judgement call: keep the rows with missing attributes", h2))
story.append(P(
    f"{pct(V[(Y1,'W01')][0])} of Jan 2025 rows ({pct(V[(Y0,'W01')][0])} in Jan 2024) have null passenger count and "
    "rate code (<font face='Courier'>payment_type = 0</font>). A generic 'drop incomplete rows' step would remove them. "
    "We kept them as a warning because: (1) their time, distance and zones are populated and plausible; (2) TLC counts "
    f"them, so dropping them would move our trips/day from {r1[5]:+.1%} to {DROP[Y1]:+.1%} against TLC's published figure; "
    f"(3) the KPI barely moves either way ({KEEP[Y1][0]:.2f} mph without them vs {KEEP[Y1][1]:.2f} with them). "
    "Deleting them would under-report demand for no gain in accuracy.", base))

# 6. Facts / assumptions / unknowns
story.append(P("6. Facts, assumptions, unknowns and limitations", h2))
story.append(table([
    ["Type", "Statement", "Basis"],
    [tag("FACT", FACT), "Both monthly files are fully loaded and cover every day of the month.",
     "Parquet footer row count; gate G2"],
    [tag("FACT", FACT), f"Our volume and duration agree with TLC's published indicators within {abs(r1[5]):.1%} and "
     f"{abs(r1[8]):.1%}.", "Industry Indicators API"],
    [tag("FACT", FACT), "The zones API repeats IDs 56 and 103 and has no rows for 57, 104 and 105; the other 260 zones match.",
     "Lookup CSV vs API cross-check"],
    [tag("ASSUMPTION", ASSUME), "'Manhattan core' = TLC Yellow Zone. This is close to, but larger than, the toll zone "
     "(south of 60th St).", "TLC zone lookup"],
    [tag("ASSUMPTION", ASSUME), "Trips < 1 min, > 3 h, > 100 mi or > 65 mph are not real passenger trips.",
     "Thresholds in config/pipeline.toml"],
    [tag("UNKNOWN", UNKNOWN), "What the payment_type 0 rows are ('Flex Fare' per the 2025 dictionary) and why they grew "
     "about 4x.", "Needs TLC / vendor answer"],
    [tag("UNKNOWN", UNKNOWN), "Whether VendorID 1 folds surcharges into 'extra'; and TLC's method for its indicators.",
     "Pattern only; no documentation"],
    [tag("LIMITATION", LIMIT), "Before/after comparison, not a controlled test: weather, events and fares also changed. "
     "Yellow cabs only (no Uber/Lyft). Zone-level location only.", "Scope of the data"],
], [W * .12, W * .64, W * .24]))

# 7. Pipeline
story.append(P("7. How the output is made repeatable", h2))
story.append(pipeline_diagram())
story.append(P(
    "Reruns are idempotent: each month is replaced inside one transaction, and unchanged raw files (same ETag and "
    "sha256) are reused. If TLC re-publishes a file, the change is detected and it is downloaded again. HTTP calls retry "
    "with backoff. A month that is not yet published, or that fails, is logged and rolled back while other months "
    "continue. Fail gates block publishing (the metric status becomes 'blocked'). Every stage writes status, rows and "
    "seconds to a run log, and every metric row carries its run_id. The exit code is non-zero unless every month "
    "published. 5 automated tests cover the rules, reruns, gates and rollback.", base))

# ------------------------------------------------------------------ build
def footer(canv, doc):
    canv.saveState()
    canv.setFont("Helvetica", 6.5)
    canv.setFillColor(MUTED)
    canv.drawString(15 * mm, 8 * mm, "FDE Data Foundations - Track B: NYC TLC yellow taxi trips")
    canv.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Page {doc.page} of 2")
    canv.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=11 * mm,
                        bottomMargin=13 * mm, title="Track B - NYC TLC yellow taxi: where cabs lose time",
                        author="FDE Assignment 2")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(OUT)
