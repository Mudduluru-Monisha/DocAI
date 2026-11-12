"""Visual layer for DocuMind: CSS, logo and small HTML builders. All text is escaped before it reaches HTML."""
from __future__ import annotations

import hashlib
import html
import re

PALETTE = ["#FFC247", "#38E1C6", "#8B7BFF", "#FF7A90", "#6EC1FF", "#B6F36B", "#FF9F43", "#E58BFF", "#7FE0A5", "#F2D16B"]


def esc(s) -> str:
    return html.escape(str(s or ""))


def para(text) -> str:
    return "<br>".join(esc(text).split("\n"))


def type_color(t) -> str:
    return PALETTE[int(hashlib.md5(str(t).encode()).hexdigest(), 16) % len(PALETTE)]


def cite_html(text: str) -> str:
    safe = text.replace("<", "&lt;")

    def sub(m):
        nums = [n.strip() for n in m.group(1).split(",") if n.strip().isdigit()]
        return "".join(f'<span class="cite">{n}</span>' for n in nums) if nums else m.group(0)

    return re.sub(r"\[([\d,\s]+)\]", sub, safe)


LOGO = ('<svg width="38" height="38" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="dmg" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">'
        '<stop stop-color="#FFD36E"/><stop offset="1" stop-color="#FF9F43"/></linearGradient></defs>'
        '<rect width="40" height="40" rx="11" fill="url(#dmg)"/>'
        '<path d="M12 9h11l6.5 6.5V30a1.5 1.5 0 0 1-1.5 1.5H12A1.5 1.5 0 0 1 10.5 30V10.5A1.5 1.5 0 0 1 12 9Z" fill="#0A0E1A"/>'
        '<path d="M23 9v5.2a1.3 1.3 0 0 0 1.3 1.3h5.2" stroke="#FFD36E" stroke-width="1.4" stroke-linecap="round"/>'
        '<rect x="14" y="19.5" width="12.5" height="3" rx="1.5" fill="#FFC247"/>'
        '<rect x="14" y="25" width="8" height="2" rx="1" fill="#5B6B90"/></svg>')

ICON = {
    "layers": '<path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 13 9 5 9-5"/>',
    "graph": '<circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/>'
             '<path d="M8 8.2 10.8 15.6M16.2 7.9 13.4 15.6M8.4 7h7.2"/>',
    "quote": '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>',
}


def icon(name: str) -> str:
    return (f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICON[name]}</svg>')


def brand() -> str:
    return (f'<div class="brand">{LOGO}<div><div class="wordmark">DocuMind</div>'
            '<div class="tagline">Document intelligence</div></div></div>')


def pill(text, tone: str = "") -> str:
    dot = '<i class="dot"></i>' if tone else ""
    return f'<span class="pill {tone}">{dot}{esc(text)}</span>'


def chips(items) -> str:
    return "".join(f'<span class="chip"><i style="background:{PALETTE[i % len(PALETTE)]}"></i>{esc(t)}</span>'
                   for i, t in enumerate(items))


def stats(items) -> str:
    cells = "".join(f'<div class="stat"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for k, v in items)
    return f'<div class="stats">{cells}</div>'


def facts(items) -> str:
    return "".join(f'<div class="fact"><i>{n}</i><p>{esc(t)}</p></div>' for n, t in enumerate(items, 1))


def callout(label: str, text: str) -> str:
    return f'<div class="callout"><div class="eyebrow">{esc(label)}</div><p>{para(text)}</p></div>'


def banner(text: str) -> str:
    return f'<div class="banner"><i class="dot"></i><p>{esc(text)}</p></div>'


def dochead(eyebrow: str, title: str, pills: str) -> str:
    return (f'<div class="dochead"><div class="eyebrow">{esc(eyebrow or "Document")}</div>'
            f'<h2 class="display">{esc(title)}</h2><div class="pillrow">{pills}</div></div>')


def entity_cards(entities) -> str:
    cards = ""
    for e in entities:
        c = type_color(e["type"])
        cards += (f'<div class="ecard"><div class="ehead"><i style="background:{c}"></i><b>{esc(e["name"])}</b></div>'
                  f'<div class="etype" style="color:{c}">{esc(e["type"])} · {e["mentions"]} section'
                  f'{"s" if e["mentions"] != 1 else ""}</div><p>{esc(e["description"][:170])}</p></div>')
    return f'<div class="egrid">{cards}</div>'


def stages_for(kind: str, deep: bool):
    if kind == "analyze":
        return [("Understand", 0.0), ("Connect", 0.85), ("Summarise", 0.92)]
    if deep:
        return [("Read", 0.0), ("Index", 0.04), ("Understand", 0.35), ("Connect", 0.90), ("Summarise", 0.945)]
    return [("Read", 0.0), ("Index", 0.10)]


def job_html(stages, g: float, msg: str) -> str:
    g = max(0.0, min(1.0, g))
    cur = max((i for i, (_, t) in enumerate(stages) if g >= t), default=0)
    steps = ""
    for i, (name, _) in enumerate(stages):
        state = "done" if i < cur else "on" if i == cur else ""
        mark = "✓" if i < cur else str(i + 1)
        steps += f'<span class="step {state}"><b>{mark}</b>{esc(name)}</span>'
    return (f'<div class="job"><div class="eyebrow">Working on your document</div><div class="steps">{steps}</div>'
            f'<div class="bar"><span style="width:{g * 100:.1f}%"></span></div>'
            f'<div class="msg">{esc(msg)}<b>{g * 100:.0f}%</b></div></div>')


def hero_preview() -> str:
    return ('<div class="mock"><div class="mockbar"><i></i><i></i><i></i><span>Example answer</span></div>'
            '<div class="mq">What changed in operating margin year over year?</div>'
            '<div class="ma">Operating margin rose from 14.2% to 17.9%, driven by lower logistics costs '
            '<span class="cite">3</span> and the retail restructuring <span class="cite">7</span>. Management expects '
            'the gain to hold into next year <span class="cite">8</span>.</div>'
            '<div class="pillrow"><span class="pill">page 41</span><span class="pill">page 56</span>'
            '<span class="pill">page 58</span></div>'
            '<div class="trail">Looked at the document summary, relationships and 6 passages</div></div>')


def feature_cards() -> str:
    items = [("layers", "Reads the whole thing", "Every section is studied on upload, so questions about the entire "
              "document get real answers, not three random snippets."),
             ("graph", "Finds who and what", "People, places, concepts and how they connect, merged across "
              "chapters and shown as a graph you can explore."),
             ("quote", "Answers with receipts", "Every answer points to the pages it came from. If the document "
              "doesn't say, it tells you.")]
    return '<div class="feats">' + "".join(
        f'<div class="feat"><div class="ficon">{icon(i)}</div><h4>{esc(t)}</h4><p>{esc(d)}</p></div>'
        for i, t, d in items) + "</div>"


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Manrope:wght@400;500;600;700;800&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap');
:root{--bg:#0A0E1A;--bg2:#0F1526;--surf:#131B2F;--surf2:#19233B;--line:rgba(255,255,255,.08);--line2:rgba(255,255,255,.15);
--text:#EAF0FF;--muted:#93A0BE;--amber:#FFC247;--amber2:#FF9F43;--teal:#38E1C6;--violet:#8B7BFF}
.stApp{background:radial-gradient(1000px 520px at 88% -10%,rgba(139,123,255,.18),transparent 60%),
radial-gradient(900px 500px at -8% 6%,rgba(255,194,71,.11),transparent 55%),var(--bg);color:var(--text)}
.stApp,.stMarkdown p,.stMarkdown li,label,input,textarea,button p,[data-testid="stMarkdownContainer"]{font-family:'Manrope',system-ui,sans-serif}
.block-container{max-width:1180px;padding-top:2.4rem;padding-bottom:7rem}
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],.stDeployButton{display:none!important}
header[data-testid="stHeader"]{background:transparent}
::selection{background:rgba(255,194,71,.35)}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes shimmer{to{background-position:-200% 0}}
@keyframes floaty{0%,100%{transform:translateY(0) rotate(-1.2deg)}50%{transform:translateY(-8px) rotate(-1.2deg)}}

/* type */
.display{font-family:'Fraunces',Georgia,serif!important;font-weight:600;letter-spacing:-.025em}
.eyebrow{font-size:.72rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--amber)}
.hl{background:linear-gradient(transparent 60%,rgba(255,194,71,.55) 60%);padding:0 .08em;border-radius:2px}
.reading,.reading p{font-family:'Newsreader',Georgia,serif!important;font-size:1.16rem;line-height:1.72;color:#DCE4F8}

/* sidebar */
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0E1428,#0A0E1A);border-right:1px solid var(--line)}
[data-testid="stSidebar"] .block-container,[data-testid="stSidebarUserContent"]{padding-top:1.2rem}
.brand{display:flex;align-items:center;gap:12px;margin:.2rem 0 1.1rem}
.wordmark{font-family:'Fraunces',serif;font-weight:700;font-size:1.35rem;letter-spacing:-.02em;line-height:1}
.tagline{color:var(--muted);font-size:.74rem;margin-top:3px}
.sidelabel{font-size:.7rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:1.1rem 0 .4rem}

/* buttons */
.stButton>button,.stDownloadButton>button{border-radius:12px;border:1px solid var(--line2);background:var(--surf);color:var(--text);
font-weight:600;transition:all .18s ease}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--amber);transform:translateY(-1px);
box-shadow:0 10px 28px -12px rgba(255,194,71,.45);color:var(--text)}
.stButton>button[kind="primary"],.stButton>button[data-testid="stBaseButton-primary"]{background:linear-gradient(135deg,#FFD36E,#FF9F43);
color:#1A1205;border:0;font-weight:800}
.stButton>button[kind="primary"] p,.stButton>button[data-testid="stBaseButton-primary"] p{color:#1A1205}
.stButton>button:disabled{opacity:.45;transform:none;box-shadow:none}
[class*="st-key-lib-"] button,[class*="st-key-libsel-"] button{justify-content:flex-start;text-align:left;background:transparent;border:1px solid transparent}
[class*="st-key-lib-"] button:hover{background:rgba(255,255,255,.04);border-color:var(--line2);box-shadow:none}
[class*="st-key-libsel-"] button{background:linear-gradient(135deg,rgba(255,194,71,.16),rgba(255,159,67,.06));border-color:rgba(255,194,71,.4)}
[class*="st-key-lib"] button p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:210px}
[class*="st-key-sugg-"] button{min-height:92px;text-align:left;justify-content:flex-start;align-items:flex-start;white-space:normal;
padding:14px 16px;background:linear-gradient(160deg,var(--surf2),var(--surf));border-radius:16px;animation:fadeUp .5s both}
[class*="st-key-sugg-"] button p{font-size:.98rem;font-weight:600;line-height:1.35}

/* inputs */
[data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"]{background:var(--surf)!important;border-radius:12px!important;border-color:var(--line2)!important}
[data-testid="stFileUploaderDropzone"]{border:1.5px dashed rgba(255,194,71,.5);background:rgba(255,194,71,.05);border-radius:18px;transition:all .2s}
[data-testid="stFileUploaderDropzone"]:hover{background:rgba(255,194,71,.1);box-shadow:0 0 0 4px rgba(255,194,71,.08)}
[data-testid="stExpander"]{border:1px solid var(--line);border-radius:14px;background:var(--surf)}
[data-testid="stExpander"] summary{font-weight:600}
[data-testid="stSegmentedControl"]{background:var(--surf);border:1px solid var(--line);border-radius:14px;padding:4px}
[data-testid="stSegmentedControl"] button{border-radius:10px;font-weight:700}
iframe{border-radius:18px;border:1px solid var(--line2)}

/* hero */
.hero h1{font-family:'Fraunces',serif;font-weight:700;font-size:clamp(2.6rem,5vw,4.3rem);line-height:1.02;letter-spacing:-.035em;margin:.7rem 0 1.1rem}
.hero p.lead{color:var(--muted);font-size:1.12rem;line-height:1.6;max-width:44ch;margin-bottom:1.3rem}
.fmts{margin-top:.8rem}
.fmts span{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.06em;color:var(--muted);border:1px solid var(--line2);
border-radius:6px;padding:2px 8px;margin:0 6px 6px 0}
.mock{background:linear-gradient(160deg,var(--surf2),var(--surf));border:1px solid var(--line2);border-radius:22px;padding:18px 20px 20px;
box-shadow:0 40px 80px -30px rgba(0,0,0,.7),0 0 0 1px rgba(255,194,71,.06);animation:floaty 7s ease-in-out infinite;margin-top:1.2rem}
.mockbar{display:flex;align-items:center;gap:6px;margin-bottom:14px}
.mockbar i{width:9px;height:9px;border-radius:50%;background:rgba(255,255,255,.18)}
.mockbar span{margin-left:auto;font-size:.7rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.mq{background:rgba(255,194,71,.12);border:1px solid rgba(255,194,71,.3);border-radius:14px 14px 4px 14px;padding:10px 14px;font-weight:600;
font-size:.93rem;margin:0 0 12px auto;width:fit-content;max-width:92%}
.ma{font-size:.95rem;line-height:1.65;color:#DCE4F8;margin-bottom:12px}
.feats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:2.4rem 0 1rem}
.feat{background:var(--surf);border:1px solid var(--line);border-radius:18px;padding:20px 20px 18px;transition:all .2s;animation:fadeUp .6s both}
.feat:hover{border-color:rgba(255,194,71,.4);transform:translateY(-3px)}
.feat h4{margin:.9rem 0 .4rem;font-size:1.05rem}
.feat p{color:var(--muted);font-size:.92rem;line-height:1.55;margin:0}
.ficon{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;color:var(--amber);background:rgba(255,194,71,.1);border:1px solid rgba(255,194,71,.25)}

/* document header */
.dochead{background:linear-gradient(135deg,rgba(255,194,71,.09),rgba(139,123,255,.08) 60%,transparent);border:1px solid var(--line2);
border-radius:22px;padding:22px 26px 20px;margin-bottom:1rem;animation:fadeUp .5s both}
.dochead h2{font-size:2.05rem;line-height:1.12;margin:.35rem 0 .8rem}
.pillrow{display:flex;flex-wrap:wrap;gap:7px}
.pill{display:inline-flex;align-items:center;gap:7px;padding:4px 12px;border-radius:999px;background:rgba(255,255,255,.06);
border:1px solid var(--line);font-size:.78rem;font-weight:600;color:var(--muted)}
.pill.good{color:#7FF0D8;background:rgba(56,225,198,.1);border-color:rgba(56,225,198,.35)}
.pill.warn{color:var(--amber);background:rgba(255,194,71,.1);border-color:rgba(255,194,71,.35)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor}
.banner{display:flex;gap:12px;align-items:center;background:rgba(255,194,71,.08);border:1px solid rgba(255,194,71,.3);border-radius:14px;
padding:12px 16px;color:var(--amber)}
.banner p{margin:0;color:#F3E3BC;font-size:.92rem}

/* progress */
.job{background:linear-gradient(160deg,var(--surf2),var(--surf));border:1px solid var(--line2);border-radius:22px;padding:22px 26px;margin-bottom:1rem}
.steps{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.step{display:inline-flex;align-items:center;gap:8px;padding:6px 14px 6px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted);font-size:.84rem;font-weight:600}
.step b{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;background:rgba(255,255,255,.08);font-size:.7rem}
.step.on{color:var(--amber);border-color:rgba(255,194,71,.55);background:rgba(255,194,71,.08)}
.step.on b{background:var(--amber);color:#1A1205}
.step.done{color:#7FF0D8;border-color:rgba(56,225,198,.35)}
.step.done b{background:rgba(56,225,198,.2);color:#7FF0D8}
.bar{height:8px;border-radius:99px;background:rgba(255,255,255,.07);overflow:hidden;margin:16px 0 12px}
.bar span{display:block;height:100%;border-radius:99px;transition:width .5s ease;
background:linear-gradient(90deg,#FFC247,#FF9F43,#FFC247);background-size:200% 100%;animation:shimmer 1.6s linear infinite}
.msg{color:var(--muted);font-size:.92rem;display:flex;justify-content:space-between;gap:12px}
.msg b{color:var(--text)}

/* chat */
[data-testid="stChatMessage"]{background:var(--surf);border:1px solid var(--line);border-radius:20px;padding:1rem 1.2rem;margin-bottom:.9rem;animation:fadeUp .4s both}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){background:linear-gradient(135deg,rgba(255,194,71,.14),rgba(255,159,67,.05));border-color:rgba(255,194,71,.3)}
[data-testid="stChatMessage"] p,[data-testid="stChatMessage"] li{font-size:1.02rem;line-height:1.7}
[data-testid="stChatInput"]{border-radius:18px;border:1px solid var(--line2);background:var(--surf)}
[data-testid="stChatInput"]:focus-within{border-color:var(--amber);box-shadow:0 0 0 4px rgba(255,194,71,.14)}
[data-testid="stBottom"]>div{background:linear-gradient(180deg,transparent,var(--bg) 35%)}
.cite{background:var(--amber);color:#1A1205;border-radius:5px;padding:1px 6px;margin:0 2px;font:800 .7rem 'Manrope',sans-serif;vertical-align:2px}
.trail{display:inline-flex;align-items:center;gap:8px;margin:.5rem 0 .6rem;padding:5px 12px;border-radius:999px;background:rgba(56,225,198,.08);
border:1px solid rgba(56,225,198,.25);color:#7FF0D8;font-size:.8rem;font-weight:600}
.src{margin:.2rem 0 .8rem}
.srchead{display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:.92rem}
.passage{font-family:'Newsreader',Georgia,serif;font-size:1.02rem;line-height:1.6;white-space:pre-wrap;background:var(--bg2);
border-left:3px solid var(--amber);border-radius:0 12px 12px 0;padding:.7rem 1rem;color:#D3DBF0}
.emptychat{text-align:center;padding:2.2rem 0 1.4rem;animation:fadeUp .5s both}
.emptychat h3{font-family:'Fraunces',serif;font-size:1.9rem;font-weight:600;letter-spacing:-.02em;margin:0 0 .4rem}
.emptychat p{color:var(--muted);margin:0}

/* overview */
.sumcard{background:linear-gradient(170deg,var(--surf2),var(--surf));border:1px solid var(--line2);border-radius:22px;padding:1.7rem 2rem;margin-bottom:14px;animation:fadeUp .5s both}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}
.stat{background:var(--surf);border:1px solid var(--line);border-radius:18px;padding:16px 20px;animation:fadeUp .6s both}
.stat b{display:block;font-family:'Fraunces',serif;font-size:2.2rem;font-weight:600;line-height:1.1;color:var(--text)}
.stat span{font-size:.72rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.fact{display:flex;gap:14px;align-items:flex-start;padding:13px 16px;border:1px solid var(--line);border-radius:14px;background:var(--surf);margin-bottom:9px}
.fact i{font:700 1.15rem 'Fraunces',serif;color:var(--amber);min-width:20px;font-style:normal}
.fact p{margin:0;font-size:.95rem;line-height:1.55}
.callout{border-left:3px solid var(--amber);background:rgba(255,194,71,.07);border-radius:0 16px 16px 0;padding:14px 20px;margin-bottom:14px}
.callout p{margin:.3rem 0 0;font-family:'Newsreader',Georgia,serif;font-size:1.1rem;line-height:1.6}
.chip{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line2);background:var(--surf);border-radius:999px;padding:5px 13px;margin:0 7px 8px 0;font-size:.86rem;font-weight:600}
.chip i{width:8px;height:8px;border-radius:50%}
.egrid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0}
.ecard{background:var(--surf);border:1px solid var(--line);border-radius:16px;padding:14px 16px;transition:all .2s;animation:fadeUp .5s both}
.ecard:hover{border-color:var(--line2);transform:translateY(-2px)}
.ehead{display:flex;align-items:center;gap:9px}
.ehead i{width:10px;height:10px;border-radius:50%}
.etype{font-size:.72rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin:4px 0 6px}
.ecard p{margin:0;color:var(--muted);font-size:.88rem;line-height:1.5}
@media (max-width:860px){.feats,.egrid{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.dochead h2{font-size:1.6rem}}
</style>
"""
