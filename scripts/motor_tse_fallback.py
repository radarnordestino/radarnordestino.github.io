#!/usr/bin/env python3
"""
Motor TSE + Câmara (Fallback resiliente) para o Radar Nordestino.
Quando a API legislativa (SAPL ou portal próprio) estiver indisponível, com timeout,
bloqueada por barreira anti-bot (reCAPTCHA/Cloudflare) ou ainda sem endpoint REST aberto,
gera o portal completo com os vereadores titulares eleitos em 2024 no TSE, Prefeito,
subsídios oficiais e 100% do histórico eleitoral e financeiro do TSE (2012–2026),
exibindo aviso técnico transparente no topo da página.
"""

import datetime
import re
import ssl
import urllib.request

from common_rx import load_tse_city, norm

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def try_probe_open_api(url: str, timeout: int = 8):
    """Verifica de forma rápida se a URL responde sem CAPTCHA e sem timeout."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RadarNordestino/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            body = r.read(16384).decode("utf-8", errors="ignore")
            if "g-recaptcha" in body or "cloudflare" in body.lower() or "cf-turnstile" in body.lower():
                return False, "Barreira anti-bot (reCAPTCHA/Cloudflare) ativa no portal oficial"
            return True, body
    except Exception as e:
        return False, f"Servidor legislativo indisponível ({type(e).__name__})"


def collect_tse_city(cfg: dict, out_dir: str, aviso_override: str = "") -> dict:
    slug = cfg["slug"]
    print(f"\n[TSE + CÂMARA] Coletando {cfg['nome']}/{cfg['uf']} ({cfg['cadeiras']} vereadores)...")

    ok, info = try_probe_open_api(cfg["portal_url"])
    print(f"  -> Status do portal legislativo [{slug}]: {'OK' if ok else info}")

    if aviso_override:
        aviso = aviso_override
    else:
        motivo = info if not ok else "sem API REST aberta (SAPL/dados abertos) para extração automatizada de proposições"
        aviso = (
            f"O portal da Câmara Municipal de {cfg['nome']} ({cfg['portal_url']}) encontra-se com "
            f"{motivo}. Todos os {cfg['cadeiras']} vereadores titulares eleitos (2025–2028), "
            f"subsídios oficiais (R$ {cfg['sal']['v']:,}/mês), dados do Prefeito {cfg['pref']['nome']} "
            f"e o cruzamento eleitoral e financeiro oficial do TSE (2012–2026) estão 100% atualizados abaixo."
        ).replace(",", ".")

    tse_city = load_tse_city(slug)
    ver_tse = tse_city.get("vereadores", [])
    eleitos = [v for v in ver_tse if v.get("eleito24")]
    eleitos.sort(key=lambda x: -x.get("votos24", 0))
    eleitos = eleitos[: cfg["cadeiras"]]

    if len(eleitos) != cfg["cadeiras"]:
        raise RuntimeError(
            f"[{slug}] Validação de cadeiras falhou: esperado {cfg['cadeiras']}, obtido {len(eleitos)}"
        )

    eleitos_sorted = sorted(eleitos, key=lambda x: norm(x.get("urna", x.get("civil", ""))))
    n_ver = len(eleitos_sorted)
    vmat = [[[0, 0] for _ in range(n_ver)] for _ in range(n_ver)]
    v_out = []

    for idx, t in enumerate(eleitos_sorted, start=1):
        ap_raw = t.get("urna", t.get("civil", f"Vereador {idx}")).title()
        ap = re.sub(r"\b(De|Da|Do|Dos|Das|E)\b", lambda m: m.group(1).lower(), ap_raw)

        hist_list = t.get("hist", [])
        ver_eleicoes = [
            h["ano"] for h in hist_list
            if "vereador" in norm(h.get("cargo", "")) and "eleito" in norm(h.get("sit", "")) and "nao" not in norm(h.get("sit", ""))
        ]
        mand_count = max(1, len(set(ver_eleicoes)))
        desde_ano = (min(ver_eleicoes) + 1) if ver_eleicoes else 2025
        mand_txt = f"{mand_count}º mandato · desde {desde_ano}"

        v_out.append({
            "id": str(idx),
            "nome": t.get("civil", ap).title(),
            "ap": ap,
            "part": t.get("part24", "S/P"),
            "votos": t.get("votos24", 0),
            "ini": "2025-01-01",
            "mesa": "",
            "P": 0,
            "A": 0,
            "F": 0,
            "email": "",
            "tel": "",
            "whats": "",
            "vs": 0,
            "vn": 0,
            "va": 0,
            "naos": [],
            "cat": {"b": 0, "c": 0, "h": 0, "l": 0, "o": 0},
            "url": cfg["portal_url"],
            "foto": 0,
            "mand": mand_count,
            "desde": desde_ano,
            "mand_txt": mand_txt,
            "mand_hist": [f"{y+1}–{y+4}" for y in sorted(set(ver_eleicoes))] if ver_eleicoes else ["2025–2028"],
            "nota_exec": "",
            "leis_tot": 0,
            "leis_ord": 0,
            "leis_det": {},
            "coms": [],
            "em_imp": [],
            "alin": 0,
            "alin_s": 0,
            "alin_t": 0,
            "parc": [],
            "cob_pend": 0,
            "rec24": t.get("rec24", 0.0),
            "gasto24": t.get("gasto24", 0.0),
            "cpv24": t.get("cpv24", 0.0),
            "gasto20": t.get("gasto20", 0.0),
            "outras_cand": t.get("outras", []),
            "hist_tse": hist_list,
        })

    p_tse = tse_city.get("prefeito") or {}
    p_cfg = cfg["pref"]
    now_br = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))

    return {
        "ger": now_br.strftime("%Y-%m-%d"),
        "gerh": now_br.strftime("%Y-%m-%dT%H:%M-03:00"),
        "posse": "2025-01-01",
        "aviso_coleta": aviso,
        "cfg": {
            "nome": cfg["nome"],
            "uf": cfg["uf"],
            "portal_url": cfg["portal_url"],
            "proc_url": cfg["proc_url"],
            "form_url": cfg["form_url"],
            "leis_url": cfg["leis_url"],
            "fonte_nome": cfg["fonte_nome"],
            "endereco": cfg["endereco"],
        },
        "rep": [],
        "ult": now_br.strftime("%Y-%m-%d"),
        "sess": [],
        "semreg": [],
        "nvot": 0,
        "unan": 0,
        "v": v_out,
        "items": [],
        "catot": {"b": 0, "c": 0, "h": 0, "l": 0, "o": 0},
        "bairros": list(cfg["bairros"]),
        "bairrosn": [0 for _ in cfg["bairros"]],
        "sal": cfg["sal"],
        "pref": {
            "nome": p_cfg["nome"],
            "civil": p_cfg["civil"],
            "part": p_cfg["part"],
            "vice": p_cfg["vice"],
            "votos_1t": p_tse.get("votos_1t", 0),
            "votos_2t": p_tse.get("votos_2t", 0),
            "pct_1t": p_tse.get("pct_1t", ""),
            "pct_2t": p_tse.get("pct_2t", ""),
            "posse": "2025-01-01",
            "sal": p_cfg["sal"],
            "tot": 0,
            "plo": 0,
            "plc": 0,
            "ret": 0,
            "aprov": 0,
            "tram": 0,
            "rej": 0,
            "items": [],
            "vetos_tot": 0,
            "vetos_mant": 0,
            "vetos_derr": 0,
            "vetos": [],
            "cob_tot": 0,
            "cob_pend": 0,
            "cob_resp": 0,
            "rec24": p_tse.get("rec24", 0.0),
            "gasto24": p_tse.get("gasto24", 0.0),
            "cpv24": p_tse.get("cpv24", 0.0),
            "outras_cand": p_tse.get("outras", []),
            "hist_tse": p_tse.get("hist", []),
        },
        "rachas": [],
        "vmat": vmat,
    }
