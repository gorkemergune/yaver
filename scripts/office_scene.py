"""Static SVG layers of the Yaver HQ office scene (isometric, 960x600).

    python scripts/office_scene.py [OUT_DIR]     default: web/src/office/scene

Writes one SVG per layer (layer0, yaverDesk, glassY, desks, desksFront, glassM, chairBacks)
plus layout.json (desk columns, rows and layer z-indexes, read by the web app and its tests).
The window sky is `var(--office-sky)`: the web app sets it for day / night. The drawing
order and coordinates are the approved prototype's (design/office-prototype/Main.dc.html);
the obstacle list of the walking grid (web/src/office/geometry.ts) must match them.
"""
OX, OY, TW, TH = 480, 150, 32, 16
def P(x, y, h=0):
    return (OX + (x - y) * TW, OY + (x + y) * TH - h)
def pts(ps):
    return " ".join(f"{a:.1f},{b:.1f}" for a, b in ps)
def poly(ps, fill, extra=""):
    return f'<polygon points="{pts(ps)}" fill="{fill}"{extra}></polygon>'

def box(x, y, w, d, h, top, left, right, z0=0, stroke=None):
    """left = +y face (front-left), right = +x face (front-right)"""
    s = f' stroke="{stroke}" stroke-width="0.6"' if stroke else ""
    out = []
    out.append(poly([P(x, y + d, z0), P(x + w, y + d, z0), P(x + w, y + d, z0 + h), P(x, y + d, z0 + h)], left, s))
    out.append(poly([P(x + w, y, z0), P(x + w, y + d, z0), P(x + w, y + d, z0 + h), P(x + w, y, z0 + h)], right, s))
    out.append(poly([P(x, y, z0 + h), P(x + w, y, z0 + h), P(x + w, y + d, z0 + h), P(x, y + d, z0 + h)], top, s))
    return "".join(out)

def flat(x, y, w, d, z, fill, extra=""):
    return poly([P(x, y, z), P(x + w, y, z), P(x + w, y + d, z), P(x, y + d, z)], fill, extra)

def wallR(x1, x2, h1, h2, fill, extra=""):  # on right wall plane y=0
    return poly([P(x1, 0, h1), P(x2, 0, h1), P(x2, 0, h2), P(x1, 0, h2)], fill, extra)
def wallL(y1, y2, h1, h2, fill, extra=""):  # on left wall plane x=0
    return poly([P(0, y1, h1), P(0, y2, h1), P(0, y2, h2), P(0, y1, h2)], fill, extra)

def cup(x, y, z, color="#f4f1ea"):
    X, Y = P(x, y, z)
    return (f'<rect x="{X-2.6:.1f}" y="{Y-6:.1f}" width="5.2" height="6" rx="1.2" fill="{color}"></rect>'
            f'<ellipse cx="{X:.1f}" cy="{Y-6:.1f}" rx="2.6" ry="1.1" fill="#5a3a24"></ellipse>'
            f'<path d="M{X+2.6:.1f} {Y-4.8:.1f} q2.2 0.6 0 2.6" stroke="{color}" stroke-width="1" fill="none"></path>')

def plant(x, y, big=False):
    pot = box(x, y, 0.35, 0.35, 10 if not big else 14, "#4a3a30", "#3a2d25", "#2f241e")
    X, Y = P(x + 0.175, y + 0.175, 12 if not big else 16)
    r = 9 if not big else 13
    leaves = (f'<circle cx="{X-5:.1f}" cy="{Y-6:.1f}" r="{r*0.7:.1f}" fill="#2f6b45"></circle>'
              f'<circle cx="{X+5:.1f}" cy="{Y-8:.1f}" r="{r*0.75:.1f}" fill="#3b8456"></circle>'
              f'<circle cx="{X:.1f}" cy="{Y-14 - (6 if big else 0):.1f}" r="{r*0.8:.1f}" fill="#47995f"></circle>')
    return pot + leaves

DESK_TOP, DESK_L, DESK_R = "#8b7356", "#5e4c39", "#4e3f30"
MON = "#0c0e16"

def monitor(x, y, z, w, face_front, screen):
    # thin standing box; face_front: screen visible on +y face
    out = box(x, y, w, 0.06, 20, "#1a1d29", screen if face_front else "#151824", MON, z0=z + 4)
    if face_front:
        out += screen_lines(x, x + w, y + 0.06, z + 6, z + 23, "#0b0f24")
    # stand
    out += box(x + w / 2 - 0.04, y + 0.02, 0.08, 0.05, 4, "#2a2e3c", "#20232f", "#1a1d27", z0=z)
    return out

def screen_lines(x1, x2, y, z1, z2, col):
    o = ""
    n = 3
    for i in range(n):
        hh = z2 - (i + 1) * (z2 - z1) / (n + 1)
        a = P(x1 + 0.06, y, hh); b = P(x1 + 0.06 + (x2 - x1 - 0.12) * (0.85 - 0.25 * (i % 2)), y, hh)
        o += f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{col}" stroke-width="1.1" stroke-opacity="0.9"></line>'
    return o

def laptop(x, y, z, face_front, screen):
    out = flat(x, y, 0.46, 0.3, z + 1, "#b8bfcc")
    out += flat(x + 0.04, y + 0.04, 0.38, 0.2, z + 1.4, "#8d94a3")
    if face_front:
        out += box(x, y - 0.03, 0.46, 0.03, 15, "#c9cfda", "#1b2133", "#9aa1af", z0=z + 1)
        a, b, c, d = P(x + 0.03, y, z + 3), P(x + 0.43, y, z + 3), P(x + 0.43, y, z + 15), P(x + 0.03, y, z + 15)
        out += poly([a, b, c, d], screen, ' fill-opacity="0.35"')
        out += screen_lines(x + 0.03, x + 0.43, y, z + 3, z + 15, "#ffffff")
    else:
        out += box(x, y + 0.3, 0.46, 0.03, 15, "#c9cfda", "#aab1bf", "#9aa1af", z0=z + 1)
    return out

def papers(x, y, z):
    return (flat(x, y, 0.3, 0.38, z + 0.5, "#eef0f4") +
            flat(x + 0.05, y + 0.06, 0.3, 0.38, z + 1, "#ffffff") +
            box(x + 0.4, y + 0.02, 0.28, 0.36, 3, "#2a3a6a", "#1f2c52", "#1a2546", z0=z) +
            flat(x + 0.4, y + 0.02, 0.05, 0.36, z + 3.2, "#e0a84a"))

def books(x, y, z):
    return (box(x, y, 0.3, 0.2, 3, "#b24a3a", "#8a3a2e", "#7a3328", z0=z) +
            box(x + 0.02, y, 0.28, 0.2, 3, "#3a6ab2", "#2e528a", "#28487a", z0=z + 3) +
            box(x, y, 0.3, 0.2, 3, "#e3c25a", "#b89a44", "#a2883c", z0=z + 6))

def desk(x, y, w, d, setup, face_front, accent, extra_items=()):
    z = 22
    out = box(x, y, w, d, z, DESK_TOP, DESK_L, DESK_R, stroke="#3d3126")
    scr = accent
    far, near = [], []
    my = y + d - 0.16 if not face_front else y + 0.08  # monitors on the side away from the seated person
    if setup == "triple":
        for ox in [0.08, 0.5, 0.92]:
            far.append(monitor(x + ox, my, z, 0.4, face_front, scr))
    elif setup == "dual":
        for ox in [0.2, 0.68]:
            far.append(monitor(x + ox, my, z, 0.46, face_front, scr))
    elif setup == "paper":
        near.append(papers(x + 0.3, y + 0.15, z))
    if setup in ("triple", "dual"):
        ky = y + 0.4 if face_front else y + 0.14
        kb = box(x + 0.42, ky, 0.56, 0.17, 1.5, "#2a2e3c", "#1c1f2a", "#181a24", z0=z)
        for i in range(3):
            a = P(x + 0.46, ky + 0.04 + i * 0.045, z + 1.6); b = P(x + 0.94, ky + 0.04 + i * 0.045, z + 1.6)
            kb += f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#4a5068" stroke-width="0.8" stroke-dasharray="1.6 1"></line>'
        mx, my2 = P(x + 1.12, ky + 0.09, z + 1)
        kb = flat(x + 1.0, ky - 0.02, 0.28, 0.22, z + 0.3, "#20243a") + kb
        kb += f'<ellipse cx="{mx:.1f}" cy="{my2:.1f}" rx="3" ry="2" fill="#2a2e3c"></ellipse><ellipse cx="{mx:.1f}" cy="{my2-0.6:.1f}" rx="2" ry="1.1" fill="#3a3f52"></ellipse>'
        near.append(kb)
    near.extend(extra_items)
    # painter's order: whatever is further from the viewer (smaller y) first
    out += "".join(near + far) if not face_front else "".join(far + near)
    return out

def office_chair(x, y, back_side):
    """black office chair on wheels; footprint x..x+0.44, y..y+0.42. back_side: 'minus' (backrest at small y) or 'plus'.
    returns (lower_part, backrest)"""
    cx, cy = x + 0.22, y + 0.21
    lower = ""
    import math
    for k in range(5):
        ang = k * 2 * math.pi / 5 + 0.3
        ex, ey = cx + 0.24 * math.cos(ang), cy + 0.24 * math.sin(ang)
        a, b = P(cx, cy, 3), P(ex, ey, 2)
        lower += f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#15161c" stroke-width="2.2" stroke-linecap="round"></line>'
        w = P(ex, ey, 0)
        lower += f'<ellipse cx="{w[0]:.1f}" cy="{w[1]-1:.1f}" rx="2" ry="1.6" fill="#0b0c10"></ellipse>'
    a, b = P(cx, cy, 3), P(cx, cy, 11)
    lower += f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#2a2c34" stroke-width="2.5"></line>'
    lower += box(x, y, 0.44, 0.42, 3, "#2b2d36", "#17181e", "#121318", z0=11)
    if back_side == "minus":
        bk = box(x + 0.02, y - 0.02, 0.40, 0.07, 22, "#24262e", "#1b1c23", "#141519", z0=15)
        arms = box(x - 0.02, y + 0.1, 0.05, 0.26, 2, "#1b1c23", "#141519", "#141519", z0=19) + box(x + 0.41, y + 0.1, 0.05, 0.26, 2, "#1b1c23", "#141519", "#141519", z0=19)
        return lower + bk + arms, ""
    bk = box(x + 0.02, y + 0.37, 0.40, 0.07, 22, "#24262e", "#1b1c23", "#141519", z0=15)
    arms = box(x - 0.02, y + 0.06, 0.05, 0.26, 2, "#1b1c23", "#141519", "#141519", z0=19) + box(x + 0.41, y + 0.06, 0.05, 0.26, 2, "#1b1c23", "#141519", "#141519", z0=19)
    return lower + arms, bk

# ---------- layout ----------
SEATS = {}
DESK_X = [4.3, 5.73, 7.16, 8.59, 10.02]
DW, DD = 1.4, 0.7
YA, YB = 3.9, 4.6
ROW_A = ["atlas", "nova", "orion", "lyra", "arda"]
ROW_B = ["mira", "ece", "deniz", "kaan"]
SETUP = {"atlas": ("paper", "books"), "nova": ("dual", "cup"), "orion": ("triple", "cup"), "lyra": ("triple", None),
         "mira": ("dual", "cup"), "ece": ("paper", "plant"), "deniz": ("dual", "paper"), "kaan": ("triple", "cup"), "arda": ("triple", "cup")}
ACC = {"atlas": "#4cbcff", "nova": "#4fe0c8", "orion": "#ffb547", "lyra": "#ff7eb0", "mira": "#d29bff",
       "ece": "#86e886", "deniz": "#ffa070", "kaan": "#ece35e", "arda": "#dfe6f5"}

layer0 = []
# walls
layer0.append(poly([P(0, 0), P(0, 10), P(0, 10, 120), P(0, 0, 120)], "#1b2142"))
layer0.append(poly([P(0, 0), P(12, 0), P(12, 0, 120), P(0, 0, 120)], "#151a36"))
# floor
layer0.append(poly([P(0, 0), P(12, 0), P(12, 10), P(0, 10)], "#222943"))
for i in range(1, 12):
    layer0.append(f'<line x1="{P(i,0)[0]}" y1="{P(i,0)[1]}" x2="{P(i,10)[0]}" y2="{P(i,10)[1]}" stroke="#262e4b" stroke-width="1"></line>')
layer0.append(poly([P(0, 0), P(12, 0), P(12, 10), P(0, 10)], "none", ' stroke="#2d3555" stroke-width="2"'))
# baseboards
layer0.append(poly([P(0, 0), P(12, 0), P(12, 0, 4), P(0, 0, 4)], "#2a3157"))
layer0.append(poly([P(0, 0), P(0, 10), P(0, 10, 4), P(0, 0, 4)], "#2f3762"))
# windows (right wall, x 0.9 -> 6.8)
for x1, x2 in [(0.9, 3.4), (4.1, 6.6)]:
    layer0.append(wallR(x1, x2, 40, 100, "{{sky}}", ' stroke="#3a4374" stroke-width="3"'))
    xm = (x1 + x2) / 2
    a, b = P(xm, 0, 40), P(xm, 0, 100)
    layer0.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#3a4374" stroke-width="2"></line>')
# wall art / clock on left wall above lobby
X, Y = P(0, 4.6, 78)
layer0.append(f'<ellipse cx="{X}" cy="{Y}" rx="7" ry="9" fill="#e9ecf6"></ellipse><line x1="{X}" y1="{Y}" x2="{X}" y2="{Y-6}" stroke="#20253a" stroke-width="1.5"></line><line x1="{X}" y1="{Y}" x2="{X+3}" y2="{Y+2}" stroke="#20253a" stroke-width="1.5"></line>')

# ---------- kitchen against right wall (x 7.3 -> 12) ----------
layer0.append(flat(7.3, 0, 4.7, 1.9, 0.2, "#2a2f45"))  # tile zone
layer0.append(wallR(7.4, 10.5, 62, 92, "#3a3f55"))   # upper cabinets front
for xx in [7.4, 8.2, 9.0, 9.8]:
    layer0.append(wallR(xx + 0.04, xx + 0.76, 64, 90, "#454b63"))
layer0.append(wallR(7.4, 10.5, 30, 62, "#2c3047"))   # backsplash
# counter
layer0.append(box(7.4, 0, 3.1, 0.65, 30, "#cfd3dc", "#3a3f55", "#30344a"))
for xx in [7.5, 8.3, 9.1, 9.9]:
    a = P(xx, 0.65, 4); b = P(xx + 0.7, 0.65, 4); c = P(xx + 0.7, 0.65, 26); d = P(xx, 0.65, 26)
    layer0.append(poly([a, b, c, d], "none", ' stroke="#4a5070" stroke-width="1"'))
# espresso machine
layer0.append(box(7.6, 0.08, 0.6, 0.45, 22, "#2b2b30", "#3a3a42", "#26262c", z0=30))
X, Y = P(7.9, 0.53, 40)
layer0.append(f'<rect x="{X-6:.1f}" y="{Y-3:.1f}" width="12" height="4" rx="1" fill="#c0c4cf"></rect><circle cx="{X+8:.1f}" cy="{Y-8:.1f}" r="2" fill="#e05050"></circle>')
layer0.append(cup(7.95, 0.5, 30))
# filter coffee / grinder
layer0.append(box(8.45, 0.12, 0.35, 0.35, 26, "#c8ccd6", "#a9aebb", "#959aa8", z0=30))
layer0.append(box(8.48, 0.16, 0.28, 0.28, 8, "#5a3a24", "#4a2f1d", "#3e2718", z0=56))
# sink
layer0.append(flat(9.1, 0.12, 0.6, 0.4, 30.5, "#9aa1b0"))
X, Y = P(9.4, 0.12, 30)
layer0.append(f'<path d="M{X:.1f} {Y:.1f} v-12 q0 -4 5 -2" stroke="#c0c4cf" stroke-width="2" fill="none"></path>')
# cups shelf
for i, xx in enumerate([9.9, 10.05, 10.2]):
    layer0.append(cup(xx, 0.35, 30, ["#f4f1ea", "#e8b04a", "#4cbcff"][i]))
# minibar under counter (glass door)
a, b, c, d = P(9.85, 0.65, 3), P(10.45, 0.65, 3), P(10.45, 0.65, 26), P(9.85, 0.65, 26)
layer0.append(poly([a, b, c, d], "#16243d", ' stroke="#6d7aa8" stroke-width="1.2"'))
for hh, col in [(8, "#e05050"), (8, "#4cbcff"), (17, "#86e886"), (17, "#ffb547")]:
    pass
for i, (xx, hh, col) in enumerate([(9.95, 7, "#e05050"), (10.1, 7, "#4cbcff"), (10.25, 7, "#e05050"), (9.98, 16, "#86e886"), (10.15, 16, "#ffb547"), (10.32, 16, "#86e886")]):
    X, Y = P(xx, 0.62, hh)
    layer0.append(f'<rect x="{X-1.8:.1f}" y="{Y-6:.1f}" width="3.6" height="6" rx="1" fill="{col}"></rect>')
# fridge
layer0.append(box(10.6, 0, 0.8, 0.75, 96, "#d9dde6", "#c3c8d3", "#aeb3c0"))
a, b = P(10.6, 0.75, 60), P(11.4, 0.75, 60)
layer0.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#9aa0ad" stroke-width="1.5"></line>')
a, b = P(11.25, 0.75, 66), P(11.25, 0.75, 86)
layer0.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#7d838f" stroke-width="2.5" stroke-linecap="round"></line>')
a, b = P(11.25, 0.75, 30), P(11.25, 0.75, 54)
layer0.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#7d838f" stroke-width="2.5" stroke-linecap="round"></line>')
# water dispenser (sebil)
layer0.append(box(11.5, 0.1, 0.42, 0.42, 48, "#e8ebf2", "#cfd4de", "#b9bfcb"))
X, Y = P(11.71, 0.31, 48)
layer0.append(f'<rect x="{X-7:.1f}" y="{Y-22:.1f}" width="14" height="22" rx="5" fill="#7cc4ff" fill-opacity="0.75"></rect><ellipse cx="{X:.1f}" cy="{Y-22:.1f}" rx="7" ry="2.5" fill="#a9daff"></ellipse>')
a = P(11.6, 0.52, 30); b = P(11.82, 0.52, 30)
layer0.append(f'<circle cx="{a[0]:.1f}" cy="{a[1]:.1f}" r="1.8" fill="#4cbcff"></circle><circle cx="{b[0]:.1f}" cy="{b[1]:.1f}" r="1.8" fill="#e05050"></circle>')
# bar stools / high table
layer0.append(box(8.2, 1.35, 1.2, 0.45, 30, "#8b7356", "#5e4c39", "#4e3f30"))
layer0.append(cup(8.5, 1.5, 30, "#e8b04a"))


layer0.append(flat(4.1, 0.05, 2.9, 1.0, 0.25, "#2c2a3e"))
for ax in [4.3, 5.25, 6.2]:
    layer0.append(box(ax, 0.12, 0.6, 0.62, 12, "#8a5f48", "#6e4a38", "#5e3f30"))
    layer0.append(box(ax, 0.12, 0.6, 0.14, 28, "#8a5f48", "#6e4a38", "#5e3f30"))
    layer0.append(box(ax, 0.12, 0.08, 0.62, 19, "#7a5440", "#6e4a38", "#5e3f30"))
    layer0.append(box(ax + 0.52, 0.12, 0.08, 0.62, 19, "#7a5440", "#6e4a38", "#5e3f30"))
for tx in [5.0, 5.95]:
    layer0.append(box(tx, 0.3, 0.2, 0.2, 16, "#cfc7b8", "#8b7f6c", "#7a6f5e"))
    layer0.append(cup(tx + 0.1, 0.4, 16))

# ---------- Yaver private office (left wall, y 0.6 -> 3.8, x 0 -> 2.9) ----------
layer0.append(flat(0, 0.6, 2.9, 3.2, 0.2, "#2a2440"))
layer0.append(flat(0.5, 1.2, 1.6, 1.9, 0.4, "#3a2f5a"))  # rug
# bookshelf on left wall
layer0.append(box(0.02, 0.8, 0.35, 1.3, 70, "#5e4c39", "#4e3f30", "#43362a"))
for hh in [18, 36, 54]:
    for k, col in enumerate(["#b24a3a", "#3a6ab2", "#e3c25a", "#86e886", "#d29bff"]):
        yy = 0.85 + k * 0.24
        layer0.append(box(0.38, yy, 0.02, 0.18, 14, col, col, col, z0=hh))
layer0.append(plant(0.1, 3.2, True))
yaver_desk = []
yaver_desk.append(box(0.75, 1.4, 1.4, 0.75, 24, "#6b4f3a", "#4a3628", "#3d2c20", stroke="#2e2118"))  # exec desk
yaver_desk.append(cup(2.0, 1.6, 24))
yaver_desk.append(flat(0.82, 1.5, 0.3, 0.22, 24.5, "#f4f4f6"))
yaver_desk.append(monitor(0.92, 1.95, 24, 0.5, False, "#b3a6ff"))
yaver_desk.append(monitor(1.47, 1.95, 24, 0.5, False, "#b3a6ff"))
# exec chair behind desk? (Yaver sits at y ~1.1 side facing +y -> chair behind at y 1.0)
layer0.append(office_chair(1.23, 0.95, "minus")[0])
# guest armchairs
layer0.append(box(1.1, 2.6, 0.5, 0.5, 12, "#5a4a7a", "#463a60", "#3c3254"))
layer0.append(box(1.9, 2.6, 0.5, 0.5, 12, "#5a4a7a", "#463a60", "#3c3254"))
# Yaver room glass partition: back part along x=2.9 (y 0.6->3.8) drawn in layer0 (agents in room are left of it -> front glass layer)
# nameplate on wall
X, Y = P(0, 2.2, 96)

# ---------- Meeting room (left wall, x 0->3.6, y 5.6->9.8) ----------
layer0.append(flat(0, 5.35, 3.6, 4.45, 0.2, "#262043"))
layer0.append(flat(0.6, 6.2, 2.8, 2.3, 0.4, "#33295a"))  # rug
# projection screen on left wall
layer0.append(wallL(6.2, 8.6, 38, 98, "#e9ecf6", ' stroke="#9aa1b8" stroke-width="2"'))
a, b = P(0, 6.2, 98), P(0, 8.6, 98)
layer0.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#4a5070" stroke-width="5" stroke-linecap="round"></line>')
# projected slide content (chart bars)
for i, (y1, hgt, col) in enumerate([(6.7, 22, "#4cbcff"), (7.0, 34, "#9d8cff"), (7.3, 28, "#ffb547"), (7.6, 44, "#4fe0c8")]):
    layer0.append(wallL(y1, y1 + 0.18, 48, 48 + hgt, col))
layer0.append(wallL(6.4, 8.4, 88, 92, "#20253a"))
# meeting chairs back side (y 6.15)
CH = ("#3a4166", "#2e3454", "#272c48")
for xx in [1.2, 2.0, 2.8]:
    layer0.append(office_chair(xx - 0.21, 6.03, "minus")[0])
# table
layer0.append(box(0.9, 6.6, 2.4, 1.2, 20, "#cfc7b8", "#8b7f6c", "#7a6f5e", stroke="#6d6252"))
# projector on table
layer0.append(box(1.4, 7.0, 0.35, 0.3, 6, "#e8ebf2", "#c3c8d3", "#aeb3c0", z0=20))
X, Y = P(1.4, 7.15, 23)
layer0.append(f'<polygon points="{X:.1f},{Y:.1f} {P(0,7.35,70)[0]:.1f},{P(0,7.35,70)[1]:.1f} {P(0,7.35,50)[0]:.1f},{P(0,7.35,50)[1]:.1f}" fill="#ffffff" opacity="0.06"></polygon>')
layer0.append(flat(2.2, 7.0, 0.3, 0.38, 20.5, "#ffffff"))
layer0.append(cup(2.9, 7.2, 20))
layer0.append(flat(2.45, 7.35, 0.32, 0.24, 20.5, "#e9ecf6"))
# front chairs (y 8.0)
meet_backs = []
for xx in [1.2, 2.0, 2.8]:
    lo, bk = office_chair(xx - 0.21, 7.98, "plus")
    layer0.append(lo)
    meet_backs.append(bk)
# sofa at front of meeting room
layer0.append(box(0.3, 9.0, 2.6, 0.15, 30, "#4a3f7a", "#3a3166", "#322a58"))
layer0.append(box(0.3, 9.0, 2.6, 0.6, 12, "#55498a", "#3a3166", "#322a58"))
layer0.append(plant(3.15, 9.35, True))

# ---------- Lounge front-right ----------
layer0.append(flat(8.6, 7.3, 3.0, 2.3, 0.3, "#2c3350"))
layer0.append(box(8.9, 7.6, 2.2, 0.15, 30, "#3f6a7a", "#30535f", "#2a4852"))
layer0.append(box(8.9, 7.6, 2.2, 0.6, 12, "#4a7a8a", "#30535f", "#2a4852"))
layer0.append(box(9.4, 8.65, 1.2, 0.5, 11, "#8b7356", "#5e4c39", "#4e3f30"))
layer0.append(cup(9.7, 8.85, 11))
layer0.append(flat(10.05, 8.8, 0.3, 0.22, 11.5, "#e9ecf6"))
layer0.append(plant(11.5, 9.35, True))
layer0.append(plant(6.5, 9.4))

# ---------- open-plan bench desks (layer desks) ----------
desks = []
for i, xx in enumerate(DESK_X):
    a_id = ROW_A[i] if i < len(ROW_A) else None
    b_id = ROW_B[i] if i < len(ROW_B) else None
    # chairs row A (behind person; drawn in back layer -> layer0 is fine since person over chair)
    lo, _ = office_chair(xx + 0.48, 3.0 if a_id else 3.25, "minus")
    layer0.append(lo)
    # divider between the facing desks (low)
    sa, sa2 = SETUP.get(a_id, (None, None)) if a_id else (None, None)
    sb, sb2 = SETUP.get(b_id, (None, None)) if b_id else (None, None)
    def extras(pid, extra, yy, front):
        o = []
        if not pid: return o
        cy = yy + 0.12 if not front else yy + 0.48
        if extra == "books": o.append(books(xx + 0.05, yy + 0.08 if not front else yy + 0.4, 22))
        if extra == "paper": o.append(papers(xx + 0.05 if extra != "paper" or SETUP[pid][0] != "paper" else xx + 0.75, yy + 0.07 if not front else yy + 0.3, 22))
        if extra == "plant":
            X, Y = P(xx + 1.15, yy + 0.35, 22)
            o.append(f'<rect x="{X-4:.1f}" y="{Y-6:.1f}" width="8" height="6" rx="1.5" fill="#c86f4a"></rect><circle cx="{X-3:.1f}" cy="{Y-10:.1f}" r="4.5" fill="#3b8456"></circle><circle cx="{X+3:.1f}" cy="{Y-11:.1f}" r="4.5" fill="#47995f"></circle>')
        if extra == "cup" or pid in ("atlas", "lyra", "deniz", "ece"):
            o.append(cup(xx + 0.2, cy, 22, "#ff7eb0" if pid == "lyra" else "#f4f1ea"))
        return o
    # painter order: back desk + its items, divider, front desk + its items
    desks.append(desk(xx, YA, DW, DD, sa, False, ACC.get(a_id, "#3a4166"), extras(a_id, sa2, YA, False)))
    desks.append(box(xx, YB - 0.03, DW, 0.03, 9, "#3a4166", "#2e3454", "#272c48", z0=22))
    desks.append(desk(xx, YB, DW, DD, sb, True, ACC.get(b_id, "#3a4166"), extras(b_id, sb2, YB, True)))
    # chairs row B (in front of person) -> separate front layer
desks_front = []
chair_backs = []
for i, xx in enumerate(DESK_X):
    # row B chairs: seat only (person sits on it; drawn under agent? place in layer0-like below agents but above desks)
    lo, bk = office_chair(xx + 0.48, 5.9, "plus")
    desks_front.append(lo)
    chair_backs.append(bk)

# spare label position
spare = P(DESK_X[-1] + 0.7, YB + 0.9, 0)

# glass partitions
glass_y = []  # Yaver room front glass (layer z 45): along x=2.9 (y 0.6->3.8) and y=3.8 (x 0 -> 2.9) with door gap x 0.9->1.8
G = ' fill="#c9d2ff" fill-opacity="0.07" stroke="#9aa6dd" stroke-opacity="0.45" stroke-width="1"'
glass_y.append(poly([P(2.9, 0.6), P(2.9, 3.8), P(2.9, 3.8, 70), P(2.9, 0.6, 70)], "#c9d2ff", G.replace(' fill="#c9d2ff"', '')))
glass_y.append(poly([P(0, 3.8), P(0.9, 3.8), P(0.9, 3.8, 70), P(0, 3.8, 70)], "#c9d2ff", G.replace(' fill="#c9d2ff"', '')))
glass_y.append(poly([P(1.8, 3.8), P(2.9, 3.8), P(2.9, 3.8, 70), P(1.8, 3.8, 70)], "#c9d2ff", G.replace(' fill="#c9d2ff"', '')))
a, b = P(0, 3.8, 70), P(0.9, 3.8, 70)
glass_y.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#b3a6ff" stroke-width="2"></line>')
a, b, c = P(1.8, 3.8, 70), P(2.9, 3.8, 70), P(2.9, 0.6, 70)
glass_y.append(f'<polyline points="{pts([a,b,c])}" fill="none" stroke="#b3a6ff" stroke-width="2"></polyline>')
glass_m = []  # meeting room: back glass y=5.6 in layer0, side glass x=3.6 with door gap y 7.5->8.4 in front layer
layer0.append(poly([P(0, 5.35), P(3.6, 5.35), P(3.6, 5.35, 70), P(0, 5.35, 70)], "#c9d2ff", G.replace(' fill="#c9d2ff"', '')))
glass_m.append(poly([P(3.6, 5.35), P(3.6, 7.5), P(3.6, 7.5, 70), P(3.6, 5.35, 70)], "#c9d2ff", G.replace(' fill="#c9d2ff"', '')))
glass_m.append(poly([P(3.6, 8.4), P(3.6, 9.8), P(3.6, 9.8, 70), P(3.6, 8.4, 70)], "#c9d2ff", G.replace(' fill="#c9d2ff"', '')))

def svg(content, h=600):
    return f'<svg width="960" height="{h}" viewBox="0 0 960 {h}" aria-hidden="true" style="position: absolute; left: 0; top: 0">{"".join(content)}</svg>'

# ---------- wall signs ----------
PADT = 0.25
def tl(span_tiles):
    return span_tiles * 32 - 2 * PADT * 32
def sign_right(x1, x2, h1, h2, text, color, sub=None):
    a, b, c, d = P(x1, 0, h1), P(x2, 0, h1), P(x2, 0, h2), P(x1, 0, h2)
    o = poly([a, b, c, d], "#0f1328", f' stroke="{color}" stroke-opacity="0.85" stroke-width="1.4"')
    X, Y = P(x1 + PADT, 0, (h1 + h2) / 2 - 3.6)
    o += f'<text transform="matrix(1,0.5,0,1,{X:.1f},{Y:.1f})" font-family="Inter, sans-serif" font-size="9.5" font-weight="700" fill="{color}" textLength="{tl(x2-x1):.1f}" lengthAdjust="spacingAndGlyphs">{text}</text>'
    return o
def sign_left(y_front, y_back, h1, h2, text, color, pad=None):
    global PADT
    old = PADT
    if pad is not None: PADT = pad
    a, b, c, d = P(0, y_front, h1), P(0, y_back, h1), P(0, y_back, h2), P(0, y_front, h2)
    o = poly([a, b, c, d], "#0f1328", f' stroke="{color}" stroke-opacity="0.85" stroke-width="1.4"')
    X, Y = P(0, y_front - PADT, (h1 + h2) / 2 - 3.6)
    o += f'<text transform="matrix(1,-0.5,0,1,{X:.1f},{Y:.1f})" font-family="Inter, sans-serif" font-size="9.5" font-weight="700" fill="{color}" textLength="{tl(y_front-y_back):.1f}" lengthAdjust="spacingAndGlyphs">{text}</text>'
    PADT = old
    return o
def sign_stand(x1, x2, y, h1, h2, text, color, legs=True):
    o = ""
    if legs:
        for xx in (x1 + 0.15, x2 - 0.15):
            a, b = P(xx, y, 0), P(xx, y, h1)
            o += f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#4a5070" stroke-width="2"></line>'
    a, b, c, d = P(x1, y, h1), P(x2, y, h1), P(x2, y, h2), P(x1, y, h2)
    o += poly([a, b, c, d], "#0f1328", f' stroke="{color}" stroke-opacity="0.85" stroke-width="1.4"')
    X, Y = P(x1 + PADT, y, (h1 + h2) / 2 - 3.3)
    o += f'<text transform="matrix(1,0.5,0,1,{X:.1f},{Y:.1f})" font-family="Inter, sans-serif" font-size="8.5" font-weight="700" fill="{color}" textLength="{tl(x2-x1):.1f}" lengthAdjust="spacingAndGlyphs">{text}</text>'
    return o

signs0 = []
signs0.append(sign_left(3.75, 0.55, 94, 110, "GENEL MÜDÜR · YAVER", "#b3a6ff"))
signs0.append(sign_left(8.6, 6.2, 102, 116, "TOPLANTI ODASI", "#a99cff", pad=0.14))
signs0.append(sign_right(7.45, 10.45, 97, 111, "MUTFAK · KAHVE", "#e0b07a"))
signs0.append(sign_stand(7.0, 8.75, 7.95, 30, 42, "DİNLENME", "#7fd0e0"))
spare_sign = sign_stand(10.45, 11.35, 5.33, 22, 31, "BOŞ MASA", "#8a91b8", legs=False)

# ---------- output ----------
import json
import sys
from pathlib import Path

NL = chr(10)
SKY = 'fill="{{sky}}"'
SKY_CSS = 'fill="#8fbaf0" style="fill: var(--office-sky, #8fbaf0)"'
# z-index of each static layer; figures sit between them (400 back row, 520 meeting room,
# 600 middle, 700 front; see web/src/office/geometry.ts)
LAYERS = [
    ("layer0", 1, layer0 + signs0),
    ("yaverDesk", 420, yaver_desk),
    ("glassY", 450, glass_y),
    ("desks", 500, desks),
    ("desksFront", 550, desks_front),
    ("glassM", 560, glass_m + meet_backs),
    ("chairBacks", 640, chair_backs),
]


def standalone(content):
    body = svg(content).replace(SKY, SKY_CSS)
    return body.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1) + NL


def write(path, text):
    path.write_bytes(text.encode("utf-8"))  # LF on every OS


def main(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, _, content in LAYERS:
        write(out_dir / f"{name}.svg", standalone(content))
    layout = {
        "width": 960,
        "height": 600,
        "origin": [OX, OY],
        "tile": [TW, TH],
        "deskX": DESK_X,
        "rowY": {"back": YA, "front": YB},
        "desk": [DW, DD],
        "layers": [{"name": name, "z": z} for name, z, _ in LAYERS],
    }
    write(out_dir / "layout.json", json.dumps(layout, indent=2) + NL)
    print(f"{len(LAYERS)} layers -> {out_dir}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else root / "web" / "src" / "office" / "scene")
