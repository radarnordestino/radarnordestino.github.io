#!/usr/bin/env python3
"""
Gerador de identidades visuais (logo.png 1000x380 e card-whatsapp.jpg 1080x1080 < 300 KB)
para todos os portais do Radar Nordestino, com números reais extraídos de cada dados.js
e zero metadados EXIF.
"""

import io
import json
import math
import os
import ssl
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_CACHE = "/tmp/radar_fonts"
SSL_CTX = ssl._create_unverified_context()

FONT_URLS = {
    "display_bold": "https://github.com/google/fonts/raw/main/ofl/bricolagegrotesque/BricolageGrotesque%5Bopsz%2Cwdth%2Cwght%5D.ttf",
    "sans_reg": "https://github.com/google/fonts/raw/main/ofl/publicsans/PublicSans%5Bwght%5D.ttf",
    "sans_bold": "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
}


def get_font(kind: str, size: int, bold: bool = False):
    os.makedirs(FONT_CACHE, exist_ok=True)
    # Tentar fontes estáticas limpas ou fontes do sistema
    candidates = []
    if bold:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ])
    else:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ])
    for p in candidates:
        if os.path.exists(p):
            try:
                idx = 1 if (bold and p.endswith("HelveticaNeue.ttc")) else 0
                return ImageFont.truetype(p, size=size, index=idx)
            except Exception:
                try:
                    return ImageFont.truetype(p, size=size)
                except Exception:
                    pass
    return ImageFont.load_default()


def nf(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def fmt_mil(v: float) -> str:
    n = float(v or 0)
    if n >= 1e6:
        s = f"{n / 1e6:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s} mi"
    if n >= 1e3:
        s = f"{n / 1e3:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s} mil"
    s = f"{n:,.0f}".replace(",", ".")
    return f"R$ {s}"


def draw_brazil_flag(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int):
    draw.rectangle([x, y, x + w, y + h], fill="#009c3b")
    cx, cy = x + w / 2, y + h / 2
    draw.polygon(
        [(cx, y + h * 0.12), (x + w * 0.88, cy), (cx, y + h * 0.88), (x + w * 0.12, cy)],
        fill="#ffdf00",
    )
    r = min(w, h) * 0.24
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#002776")
    draw.line([cx - r * 0.85, cy - r * 0.15, cx + r * 0.85, cy + r * 0.2], fill="#ffffff", width=max(2, int(h * 0.06)))


def generate_logo(out_path: str, red_part: str, black_part: str):
    """Gera logo.png 1000x380 em alta resolução (2x supersampling -> LANCZOS)."""
    S = 2
    W, H = 1000 * S, 380 * S
    img = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # 1. Ícone de ondas ((•)) no topo esquerdo
    cx, cy = 136 * S, 96 * S
    dot_r = 28 * S
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill="#000000")
    for rad, ang in [(66 * S, 42), (108 * S, 46)]:
        bbox = [cx - rad, cy - rad, cx + rad, cy + rad]
        draw.arc(bbox, start=180 - ang, end=180 + ang, fill="#000000", width=16 * S)
        draw.arc(bbox, start=360 - ang, end=360 + ang, fill="#000000", width=16 * S)

    # 2. Palavra RADAR no topo direito
    f_top = get_font("display_bold", 168 * S, bold=True)
    draw.text((275 * S, 4 * S), "RADAR", font=f_top, fill="#000000")

    # 3. Linha inferior auto-ajustada: RED_PART + BLACK_PART + bandeira
    full_word = red_part + black_part
    font_sz = 152 * S
    while font_sz > 64 * S:
        f_bot = get_font("display_bold", font_sz, bold=True)
        bb = draw.textbbox((0, 0), full_word, font=f_bot)
        tw = bb[2] - bb[0]
        if tw <= 900 * S:
            break
        font_sz -= 4 * S

    bb_full = draw.textbbox((0, 0), full_word, font=f_bot)
    tw_full = bb_full[2] - bb_full[0]
    th_full = bb_full[3] - bb_full[1]
    x0 = max(24 * S, (950 * S - tw_full) // 2)
    y0 = 205 * S + max(0, (145 * S - th_full) // 2) - bb_full[1]

    draw.text((x0, y0), red_part, font=f_bot, fill="#ff3131")
    bb_red = draw.textbbox((0, 0), red_part, font=f_bot)
    w_red = bb_red[2] - bb_red[0] if red_part else 0
    if red_part.endswith(" "):
        w_red += int(font_sz * 0.24)
    draw.text((x0 + w_red, y0), black_part, font=f_bot, fill="#000000")

    # Bandeira do Brasil no canto superior direito da palavra inferior
    fx = min(W - 68 * S, x0 + tw_full + 8 * S)
    fy = max(195 * S, y0 + bb_full[1] - 6 * S)
    draw_brazil_flag(draw, fx, fy, 58 * S, 40 * S)

    final = img.resize((1000, 380), Image.Resampling.LANCZOS)
    final.save(out_path, format="PNG", optimize=True)


def wrap_lines(draw, text: str, font, max_w: int):
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        bb = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def save_jpeg_under_300kb(img: Image.Image, out_path: str):
    rgb = img.convert("RGB")
    for q in (84, 78, 72, 66, 60):
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=q, optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) < 290 * 1024 or q == 60:
            with open(out_path, "wb") as f:
                f.write(data)
            return len(data)
    return 0


def generate_whatsapp_card(
    out_path: str,
    city_name: str,
    slug_url: str,
    n_ver: int,
    kpi1: tuple,
    kpi2: tuple,
    kpi3: tuple,
    kpi4: tuple,
    is_hub: bool = False,
):
    """Gera card-whatsapp.jpg 1080x1080 < 300 KB."""
    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), "#0b111e")
    draw = ImageDraw.Draw(img)

    # Fundo com leve gradiente vertical escuro
    for y in range(H):
        t = y / H
        r = int(11 + 8 * (1 - abs(t - 0.35)))
        g = int(17 + 11 * (1 - abs(t - 0.35)))
        b = int(30 + 18 * (1 - abs(t - 0.35)))
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    f_pill = get_font("sans_bold", 20, bold=True)
    f_pill_sm = get_font("sans_reg", 19, bold=False)
    f_eye = get_font("sans_bold", 22, bold=True)
    f_h1 = get_font("display_bold", 50, bold=True)
    f_sub = get_font("sans_reg", 25, bold=False)
    f_kv = get_font("display_bold", 46, bold=True)
    f_kl = get_font("sans_bold", 23, bold=True)
    f_kd = get_font("sans_reg", 19, bold=False)
    f_strip = get_font("sans_bold", 21, bold=True)
    f_cta_sm = get_font("sans_bold", 19, bold=True)
    f_cta_url = get_font("display_bold", 34, bold=True)
    f_btn = get_font("sans_bold", 23, bold=True)

    # Top-left pill
    pill_txt = f"RADAR {city_name.upper()} · 2025–2026"
    p_bb = draw.textbbox((0, 0), pill_txt, font=f_pill)
    pw = (p_bb[2] - p_bb[0]) + 64
    draw.rounded_rectangle([60, 52, 60 + pw, 98], radius=23, fill="#191612", outline="#785118", width=2)
    draw.ellipse([80, 68, 94, 82], fill="#f59e0b")
    draw.text((106, 63), pill_txt, font=f_pill, fill="#fbbf24")

    # Top-right pill
    r_txt = "Dados 100% Oficiais · Câmaras + TSE" if is_hub else "Dados 100% Oficiais · Câmara + TSE"
    r_bb = draw.textbbox((0, 0), r_txt, font=f_pill_sm)
    rw = (r_bb[2] - r_bb[0]) + 44
    draw.rounded_rectangle([W - 60 - rw, 52, W - 60, 98], radius=23, fill="#121a29", outline="#283548", width=1)
    draw.text((W - 60 - rw + 22, 64), r_txt, font=f_pill_sm, fill="#94a3b8")

    # Eyebrow
    draw.text((60, 134), "TRANSPARÊNCIA CIDADÃ INDEPENDENTE", font=f_eye, fill="#60a5fa")

    # Headline
    if is_hub:
        hl_lines = [
            [("13 Cidades do Nordeste: ", "#ffffff")],
            [(f"{n_ver} vereadores", "#fbbf24"), (" sob lupa diária.", "#ffffff")],
        ]
    else:
        hl_full = f"O que os {n_ver} vereadores e o Prefeito de {city_name} realmente fazem?"
        # Renderizar destacando "{n_ver} vereadores" em amarelo
        words = hl_full.split()
        target_seq = f"{n_ver} vereadores".split()
        hl_lines_raw = wrap_lines(draw, hl_full, f_h1, W - 120)
        hl_lines = []
        target_str = f"{n_ver} vereadores"
        for ln in hl_lines_raw[:3]:
            if target_str in ln:
                before, after = ln.split(target_str, 1)
                segs = []
                if before:
                    segs.append((before, "#ffffff"))
                segs.append((target_str, "#fbbf24"))
                if after:
                    segs.append((after, "#ffffff"))
                hl_lines.append(segs)
            else:
                hl_lines.append([(ln, "#ffffff")])

    hy = 176
    for segs in hl_lines:
        hx = 60
        for txt_s, col_s in segs:
            draw.text((hx, hy), txt_s, font=f_h1, fill=col_s)
            bb_s = draw.textbbox((0, 0), txt_s, font=f_h1)
            hx += bb_s[2] - bb_s[0]
            if txt_s.endswith(" "):
                hx += 12
        hy += 60

    # Subtitle
    sub_txt = (
        "Consulte seu bairro, veja quem faz leis de verdade, quem só vota junto e quanto cada um gastou nas eleições."
    )
    sy = max(hy + 12, 310)
    for sl in wrap_lines(draw, sub_txt, f_sub, W - 120)[:2]:
        draw.text((60, sy), sl, font=f_sub, fill="#cbd5e1")
        sy += 34

    # 2x2 KPI Cards
    cards = [
        (60, 405, 525, 590, "#111928", "#263346", "#ffffff", kpi1),
        (555, 405, 1020, 590, "#111928", "#263346", "#ffffff", kpi2),
        (60, 612, 525, 797, "#191714", "#5c4218", "#fbbf24", kpi3),
        (555, 612, 1020, 797, "#21141c", "#63293a", "#f87171", kpi4),
    ]
    for x1, y1, x2, y2, bg, bd, vcol, (val, lbl, desc) in cards:
        draw.rounded_rectangle([x1, y1, x2, y2], radius=22, fill=bg, outline=bd, width=2)
        draw.text((x1 + 28, y1 + 22), val, font=f_kv, fill=vcol)
        draw.text((x1 + 28, y1 + 82), lbl, font=f_kl, fill="#f8fafc")
        dy = y1 + 116
        for dl in wrap_lines(draw, desc, f_kd, (x2 - x1) - 56)[:2]:
            draw.text((x1 + 28, dy), dl, font=f_kd, fill="#94a3b8")
            dy += 25

    # Feature strip
    draw.rounded_rectangle([60, 824, 1020, 886], radius=18, fill="#111a2a", outline="#263346", width=1)
    strip_txt = "Busca por Bairro    •    Comparador Lado a Lado    •    Histórico TSE 2012–2026"
    s_bb = draw.textbbox((0, 0), strip_txt, font=f_strip)
    draw.text(((W - (s_bb[2] - s_bb[0])) // 2, 843), strip_txt, font=f_strip, fill="#f1f5f9")

    # Bottom Amber CTA
    draw.rounded_rectangle([60, 914, 1020, 1028], radius=24, fill="#f59e0b")
    draw.text((94, 936), "ACESSE GRÁTIS PELO CELULAR OU COMPUTADOR", font=f_cta_sm, fill="#1e293b")
    draw.text((94, 966), slug_url, font=f_cta_url, fill="#0b111e")

    # CTA Button
    draw.rounded_rectangle([725, 938, 988, 1004], radius=16, fill="#0b111e")
    btn_txt = "Consultar agora →"
    b_bb = draw.textbbox((0, 0), btn_txt, font=f_btn)
    draw.text((725 + (263 - (b_bb[2] - b_bb[0])) // 2, 958), btn_txt, font=f_btn, fill="#fbbf24")

    return save_jpeg_under_300kb(img, out_path)


if __name__ == "__main__":
    print("Módulo gerar_artes carregado com sucesso.")
