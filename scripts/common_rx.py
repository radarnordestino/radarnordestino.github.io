#!/usr/bin/env python3
"""
Motor compartilhado de classificação determinística, extração de ruas repetidas ("O problema que não some"),
cruzamento com a base oficial do TSE (2012–2026) e consolidação do objeto window.RX — Radar Nordestino.
"""

import json
import os
import re
import unicodedata
from collections import Counter, defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TSE_DB_PATH = os.path.join(SCRIPT_DIR, "dados_tse_13cidades.json")

TH_RULES = [
    ("luz", r"iluminac|lampad|luminar|poste|\bled\b|escuro|escurid|brac[oa]s? de luz|rede de energia|coelba|celpe|equatorial|neoenergia|energisa|cosern|enel"),
    ("asf", r"tapa[- ]?burac|buraco|recapea|asfalto|pavimenta|calçamento|calcamento|massa asfaltica|cratera|desnivelad|cascalha|patrolamento|nivelamento|paralelepipedo"),
    ("tra", r"lombada|redutor de velocidade|semaforo|faixa de pedestre|sinalizac|transito|rotatoria|radar|travessia elevada|ombro|mao unica|estacionamento|botoeira|placa|transalvador|cttu|sttu|smtt|semob|amc\b"),
    ("agu", r"esgoto|bueiro|boca de lobo|alagament|drenagem|galeria pluvial|enchent|vazamento|embasa|compesa|casal|cagece|caern|deso|caema|cagepa|agua parada|canaleta|corrego|riacho|abastecimento de agua"),
    ("lim", r"mato alto|capina|rocad|rocag|limpeza|entulho|lixo|cacamba|cata[- ]?bagulho|descarte irregular|poda|arvore|varricao|terreno baldio|zeladoria|limpurb"),
    ("cal", r"calcada|passeio publico|meio[- ]?fio|guia|sarjeta|acessibilidade|rampa|passarela|escadaria|contencao|encosta"),
    ("sau", r"\bubs\b|\besf\b|\bpamo\b|\bupa\b|\bumsf\b|hospital|posto de saude|medicament|remedio|medico|consulta|exame|dengue|zoonose|vacina|ambulancia|samu|saude|cirurgia"),
    ("edu", r"escola|creche|emei|emef|emeb|merenda|aluno|professor|uniforme|educac|quadra escolar"),
    ("seg", r"seguranca|guarda civil|guarda municipal|\bgcm\b|policia|ronda|patrulha|camera|monitoramento|assalto|furto|violencia"),
    ("bus", r"onibus|ponto de onibus|abrigo de onibus|transporte publico|transporte coletivo|linha de onibus|itinerario|rodoviari|brt\b|vlt\b|integracao"),
    ("laz", r"parque|quadra|campo de futebol|academia ao ar livre|playground|brinquedo|pista de caminhada|area de lazer|esportiv|praca|areninha"),
]

THH_RULES = [
    ("pes", r"pesar|falecimento|luto|condolenc|in memoriam"),
    ("tit", r"cidada[oa]|titulo|medalha|comenda|honra ao merito|diploma|utilidade publica|patrimonio cultural"),
    ("nom", r"denomina|denominac|nome de rua|logradouro|da nome"),
    ("dat", r"calendario|institui o dia|institui a semana|institui o mes|dia municipal|semana municipal|data comemorativa"),
    ("par", r"aplauso|congratulac|parabeniz|louvor|homenage|solenidade"),
]

STREET_PAT = re.compile(
    r"\b((?:Rua|Avenida|Av\.|Estrada(?:\s+Municipal)?|Praça|Travessa|Alameda|Rodovia|Viela|Largo|Viaduto|Ladeira)\s+[A-ZÀ-Ú0-9][A-Za-zÀ-ÿ0-9\s\.\'\-]{3,65}?)(?=\s*(?:,|\bnº|\bn\.|\bno\s+bairro|\bna\s+região|\bno\s+distrito|\bbairro\b|\s-\s|\s–\s|\.|\)|;|\bonde\b|\bque\b|\bpara\b|\bem\s+frente\b|\bpróximo\b|\besquina\b|\bcruzamento\b|\baltura\b|$))",
    re.I,
)


def norm(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s or "").lower())
        if unicodedata.category(c) != "Mn"
    ).strip()


def clean_ap(s: str) -> str:
    s = re.sub(r"^(?:Ver\.ª|Ver\.|Vereador(?:a)?)\s+", "", (s or "").strip(), flags=re.I)
    return s.strip()


def classify_theme(grupo: str, txt: str) -> str:
    nt = norm(txt)
    if grupo == "h":
        for code, pat in THH_RULES:
            if re.search(pat, nt):
                return code
        return "par"
    elif grupo in ("b", "c"):
        for code, pat in TH_RULES:
            if re.search(pat, nt):
                return code
        return ""
    return ""


def classify_item(tipo: str, ementa: str):
    nt = norm(ementa)
    ntipo = norm(tipo)
    eh_materia = 1

    if "indicac" in ntipo or ntipo == "ind":
        grupo = "b"
    elif "pedido de informac" in ntipo or "requerimento de informac" in ntipo:
        grupo = "c"
    elif "requerimento" in ntipo or ntipo in ("req", "rds", "rps", "rdp", "rpp", "rpl"):
        if re.search(r"justificativa de ausencia|retirada d[eo] projeto|retirada d[ae] proposi|coautoria|licenca|destaque|regime de urgencia|adiamento|arquivamento|pedido de vista|uso da tribuna|prorrogacao", nt):
            grupo = "o"
        elif re.search(r"solenidade|sessao solene|homenage|voto de louvor|congratulac|aplauso|pesar|falecimento", nt):
            grupo = "h"
        elif re.search(r"informa|esclarec|audiencia|copia|cronograma|convoca|prestacao|relatorio|quantos|quais|motivo|por que|previsao|situacao|fiscaliza|oficio|secretari|prefeit|subprefeit", nt):
            grupo = "c"
        else:
            grupo = "b"
    elif "mocao" in ntipo or "moção" in ntipo or ntipo == "moc":
        if re.search(r"apelo|repudio", nt):
            grupo = "c"
        elif re.search(r"apoio", nt) and not re.search(r"aplauso|congratul|pesar", nt):
            grupo = "o"
        else:
            grupo = "h"
    elif "decreto legislativo" in ntipo or ntipo in ("pdl", "dl"):
        if re.search(r"cidada|titulo|medalha|homenage|solenidade|honra|comenda|denom|salva de prata|merito", nt):
            grupo = "h"
        else:
            grupo = "o"
    elif any(k in ntipo for k in ("resolucao", "frente parlamentar", "nome parlamentar", "emenda", "substitutivo")) and "lei organica" not in ntipo:
        grupo = "o"
    elif any(k in ntipo for k in ("projeto de lei", "lei ordinaria", "lei complementar", "lei organica")) or ntipo in ("pl", "plo", "plc", "pel", "pll", "plcl"):
        if re.search(r"denomina|calendario|institui o dia|institui a semana|institui o mes|dia municipal|semana municipal|utilidade publica|patrimonio cultural|homenage", nt):
            grupo = "h"
        else:
            grupo = "l"
    else:
        grupo = "o"

    th = classify_theme(grupo, ementa)
    return grupo, eh_materia, th


def load_tse_city(city_slug: str) -> dict:
    if not os.path.exists(TSE_DB_PATH):
        return {"prefeito": None, "vereadores": []}
    with open(TSE_DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    return db.get(city_slug, {"prefeito": None, "vereadores": []})


def match_tse_vereador(ap: str, civil: str, tse_list: list) -> dict:
    nap = norm(clean_ap(ap))
    nciv = norm(civil)
    for t in tse_list:
        tu = norm(t.get("urna", ""))
        tc = norm(t.get("civil", ""))
        if (nciv and nciv == tc) or (nap and nap == tu) or (nap and nap == tc):
            return t
    nap_clean = re.sub(r"^(?:professor(?:a)?|dr(?:a)?\.?|pastor(?:a)?|cabo|coronel|vereador(?:a)?|locutor|delegad[oa]|sargento|tenente|major|irm[aã]o?)\s+", "", nap).strip()
    for t in tse_list:
        tu = norm(t.get("urna", ""))
        tc = norm(t.get("civil", ""))
        tu_clean = re.sub(r"^(?:professor(?:a)?|dr(?:a)?\.?|pastor(?:a)?|cabo|coronel|vereador(?:a)?|locutor|delegad[oa]|sargento|tenente|major|irm[aã]o?)\s+", "", tu).strip()
        if nap_clean and len(nap_clean) >= 4 and (nap_clean == tu_clean or nap_clean in tu or tu in nap_clean):
            return t
        if nciv and len(nciv) >= 8 and (nciv in tc or tc in nciv):
            return t
    ap_tokens = [w for w in nap_clean.split() if len(w) > 2 and w not in ("dos", "das", "do", "da", "de")]
    if len(ap_tokens) >= 2:
        for t in tse_list:
            combined = norm(t.get("urna", "") + " " + t.get("civil", ""))
            if all(w in combined for w in ap_tokens):
                return t
    return {}


def compute_bairros_and_rep(items: list, bairros_seed: list):
    norm_items_text = [norm(str(it[2]) + " " + str(it[1])) for it in items]
    bairros_pairs = []
    for b in bairros_seed:
        nb = norm(b)
        cnt = sum(1 for txt in norm_items_text if nb in txt)
        if cnt > 0:
            bairros_pairs.append((b, cnt))
    bairros_pairs.sort(key=lambda x: -x[1])
    if bairros_pairs:
        bairros_out = [b for b, _ in bairros_pairs]
        bairrosn_out = [c for _, c in bairros_pairs]
    else:
        bairros_out = list(bairros_seed)
        bairrosn_out = [0 for _ in bairros_seed]

    rep_groups = defaultdict(list)
    for item_idx, it in enumerate(items):
        pid, code, txt, aaaammdd, grp, res_l, auts, ehm, th = it[:9]
        if grp not in ("b", "c") or not th:
            continue
        m_st = STREET_PAT.search(str(txt))
        if not m_st:
            continue
        st = re.sub(r"\s+", " ", m_st.group(1)).strip(" .,;-–")
        st = re.sub(r"^(?i:av\.|avenida)\s+", "Avenida ", st)
        st = re.sub(r"^(?i:rua)\s+", "Rua ", st)
        st = re.sub(r"^(?i:praça)\s+", "Praça ", st)
        st = re.sub(r"^(?i:estrada)\s+", "Estrada ", st)
        if len(st.split()) < 2 or len(st) > 65:
            continue
        nst = (
            norm(st)
            .replace("teresinha", "terezinha")
            .replace("doutor ", "dr. ")
            .replace("comendador ", "com. ")
            .replace("professor ", "prof. ")
            .replace("professora ", "profa. ")
        )
        rep_groups[(nst, th)].append((st, item_idx, aaaammdd, auts, str(txt)))

    rep_out = []
    for (nst, th), lst in rep_groups.items():
        if len(lst) < 3:
            continue
        st_name = Counter(x[0] for x in lst).most_common(1)[0][0]
        found_b = ""
        for _, _, _, _, txt in lst:
            ntxt = norm(txt)
            for b in bairros_out:
                if norm(b) in ntxt:
                    found_b = b
                    break
            if found_b:
                break
        all_auts = set()
        for _, _, _, auts, _ in lst:
            all_auts.update(auts)
        dates = sorted(x[2] for x in lst if x[2])
        ids = sorted(x[1] for x in lst)
        rep_out.append({
            "r": st_name,
            "b": found_b,
            "th": th,
            "n": len(lst),
            "a": len(all_auts),
            "d0": dates[0] if dates else "20250101",
            "d1": dates[-1] if dates else "20261101",
            "ids": ids,
        })

    rep_out.sort(key=lambda x: (-x["n"], -x["a"], x["r"]))
    return bairros_out, bairrosn_out, rep_out
