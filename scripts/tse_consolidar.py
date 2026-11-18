#!/usr/bin/env python3
"""
Extrator e Consolidador Oficial de Dados Eleitorais do TSE (2012–2026) — Radar Nordestino.
Baixa diretamente de https://cdn.tse.jus.br/estatistica/sead/odsele/ os recortes dos 8 estados
do Nordeste (AL, BA, CE, MA, PB, PE, RN, SE) dos pacotes consulta_cand_{ANO}.zip,
votacao_candidato_munzona_2024.zip e prestacao_de_contas_eleitorais_candidatos_{ANO}.zip
(usando HTTP Range para ler apenas os arquivos *_UF.csv sem baixar os demais estados)
e gera dados_tse_13cidades.json.

Regras estritas de desambiguação:
1. Vincula primeiro pelo CPF válido ou Título Eleitoral (NR_TITULO_ELEITORAL_CANDIDATO)
   do candidato na eleição municipal de 2024 naquela cidade.
2. Em fallback por nome civil (NM_CANDIDATO), exige data de nascimento compatível e,
   nos anos municipais (2012, 2016, 2020, 2024), exige obrigatoriamente que NM_UE seja
   a mesma cidade do parlamentar para jamais misturar homônimos de outros municípios.
"""

import concurrent.futures
import csv
import json
import os
import ssl
import struct
import sys
import time
import unicodedata
import urllib.request
import zlib
from collections import defaultdict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = "/tmp/tse_ne_cache"
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados_tse_13cidades.json")

SSL_CTX = ssl.create_default_context()
try:
    urllib.request.urlopen("https://cdn.tse.jus.br/", timeout=8, context=SSL_CTX).close()
except Exception:
    SSL_CTX = ssl._create_unverified_context()

UFS = ["AL", "BA", "CE", "MA", "PB", "PE", "RN", "SE"]

# (NM_UE_NORM, UF) -> slug
TARGET_UES = {
    ("SALVADOR", "BA"): "salvador",
    ("SAO LUIS", "MA"): "saoluis",
    ("MACEIO", "AL"): "maceio",
    ("ARACAJU", "SE"): "aracaju",
    ("CARUARU", "PE"): "caruaru",
    ("PETROLINA", "PE"): "petrolina",
    ("CAMPINA GRANDE", "PB"): "campinagrande",
    ("MARACANAU", "CE"): "maracanau",
    ("MOSSORO", "RN"): "mossoro",
    ("PATOS", "PB"): "patos",
    ("CRUZ DAS ALMAS", "BA"): "cruzdasalmas",
    ("IRECE", "BA"): "irece",
    ("SANTO ANTONIO DE JESUS", "BA"): "santoantoniodejesus",
}

MUNICIPAL_YEARS = {2012, 2016, 2020, 2024}
ALL_YEARS = [2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026]
ACCOUNTS_YEARS = [2018, 2020, 2022, 2024, 2026]


def norm(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").upper())
        if unicodedata.category(c) != "Mn"
    ).strip()


def clean_id(val: str) -> str:
    v = (val or "").strip().strip('"')
    if not v or v in ("-1", "-3", "-4", "#NULO", "#NULO#", "#NE", "NAO DIVULGAVEL", "NÃO DIVULGÁVEL"):
        return ""
    digits = "".join(ch for ch in v if ch.isdigit())
    return digits.lstrip("0") if digits else ""


def http_range(url: str, start: int, end: int) -> bytes:
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (RadarNordestino/1.0)",
                    "Range": f"bytes={start}-{end}",
                },
            )
            return urllib.request.urlopen(req, timeout=60, context=SSL_CTX).read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    return b""


def get_zip_cd(url: str):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0 (RadarNordestino/1.0)"})
    sz = int(urllib.request.urlopen(req, timeout=20, context=SSL_CTX).headers["Content-Length"])
    tail_len = min(sz, 262144)
    tail = http_range(url, sz - tail_len, sz - 1)
    eocd = tail.rfind(b"PK\x05\x06")
    _, _, _, _, _, cd_size, cd_offset, _ = struct.unpack("<4sHHHHIIH", tail[eocd : eocd + 22])
    cd = http_range(url, cd_offset, cd_offset + cd_size - 1)
    entries = {}
    pos = 0
    while pos < len(cd) and cd[pos : pos + 4] == b"PK\x01\x02":
        comp_method, _, _, _, comp_sz, _, fn_len, ex_len, cm_len, _, _, _, lhoff = struct.unpack(
            "<H2s2sIIIHHHHHII", cd[pos + 10 : pos + 46]
        )
        fn = cd[pos + 46 : pos + 46 + fn_len].decode("latin1")
        entries[fn.upper()] = (comp_method, comp_sz, fn_len, lhoff)
        pos += 46 + fn_len + ex_len + cm_len
    return entries


def download_zip_member(url: str, cd_entries: dict, member_substr: str, out_path: str):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 500:
        return out_path
    target = None
    m_up = member_substr.upper()
    for fn_up, info in cd_entries.items():
        if m_up in fn_up:
            target = info
            break
    if not target:
        print(f"  [AVISO] {member_substr} não encontrado em {url}")
        return None
    comp_method, comp_sz, fn_len, lhoff = target
    hdr = http_range(url, lhoff, lhoff + 30 + fn_len + 256)
    fn_l, ex_l = struct.unpack("<HH", hdr[26:30])
    data_start = lhoff + 30 + fn_l + ex_l
    data_end = data_start + comp_sz - 1
    dob = zlib.decompressobj(-zlib.MAX_WBITS) if comp_method == 8 else None
    tmp_path = out_path + ".part"
    with open(tmp_path, "wb") as out:
        cur = data_start
        chunk_sz = 16 * 1024 * 1024
        while cur <= data_end:
            nxt = min(data_end, cur + chunk_sz - 1)
            raw = http_range(url, cur, nxt)
            out.write(dob.decompress(raw) if dob else raw)
            cur = nxt + 1
        if dob:
            out.write(dob.flush())
    os.replace(tmp_path, out_path)
    return out_path


def ensure_tse_files(cache_dir: str):
    os.makedirs(cache_dir, exist_ok=True)
    zip_urls = []
    for yr in ALL_YEARS:
        zip_urls.append((
            f"https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{yr}.zip",
            [(f"consulta_cand_{yr}_{uf}.csv", os.path.join(cache_dir, f"consulta_cand_{yr}_{uf}.csv")) for uf in UFS],
        ))
    zip_urls.append((
        "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2024.zip",
        [(f"votacao_candidato_munzona_2024_{uf}.csv", os.path.join(cache_dir, f"votacao_candidato_munzona_2024_{uf}.csv")) for uf in UFS],
    ))
    for yr in ACCOUNTS_YEARS:
        zurl = f"https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{yr}.zip"
        members = []
        for uf in UFS:
            members.append((f"receitas_candidatos_{yr}_{uf}.csv", os.path.join(cache_dir, f"receitas_candidatos_{yr}_{uf}.csv")))
            members.append((f"despesas_contratadas_candidatos_{yr}_{uf}.csv", os.path.join(cache_dir, f"despesas_contratadas_candidatos_{yr}_{uf}.csv")))
        zip_urls.append((zurl, members))

    tasks = []
    for zurl, members in zip_urls:
        missing = [(m, p) for m, p in members if not (os.path.exists(p) and os.path.getsize(p) > 500)]
        if not missing:
            continue
        try:
            cd_entries = get_zip_cd(zurl)
            for m, p in missing:
                tasks.append((zurl, cd_entries, m, p))
        except Exception as e:
            print(f"  [AVISO] Falha ao ler índice ZIP {zurl}: {e}")

    if tasks:
        print(f"Baixando {len(tasks)} recortes estaduais do TSE via HTTP Range...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(download_zip_member, u, cd, m, p) for u, cd, m, p in tasks]
            for f in concurrent.futures.as_completed(futs):
                f.result()


def format_cargo(ds_cargo: str, is_fem: bool) -> str:
    c = norm(ds_cargo)
    if c == "VEREADOR":
        return "Vereadora" if is_fem else "Vereador"
    if c == "DEPUTADO ESTADUAL":
        return "Deputada Estadual" if is_fem else "Deputado Estadual"
    if c == "DEPUTADO FEDERAL":
        return "Deputada Federal" if is_fem else "Deputado Federal"
    if c == "PREFEITO":
        return "Prefeita" if is_fem else "Prefeito"
    if c in ("VICE-PREFEITO", "VICE PREFEITO"):
        return "Vice-Prefeita" if is_fem else "Vice-Prefeito"
    if c == "SENADOR":
        return "Senadora" if is_fem else "Senador"
    if c == "GOVERNADOR":
        return "Governadora" if is_fem else "Governador"
    return ds_cargo.title()


def format_sit(ds_sit: str, turno: str, is_fem: bool, cargo_norm: str) -> str:
    s = norm(ds_sit)
    if "ELEITO" in s and "NAO" not in s:
        base = "Eleita" if is_fem else "Eleito"
        if turno == "2" and cargo_norm == "PREFEITO":
            return f"{base} (2º Turno)"
        return base
    if "SUPLENTE" in s:
        return "Suplente"
    if "2º TURNO" in ds_sit.upper() or "2O TURNO" in s or "SEGUNDO TURNO" in s:
        return "2º Turno"
    if "NAO ELEITO" in s:
        return "Não Eleita" if is_fem else "Não Eleito"
    if not s or s in ("#NULO#", "#NE", "-1", "-3"):
        return "Registrado"
    return ds_sit.title()


def parse_brl(val: str) -> float:
    v = (val or "0").strip()
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".")
    else:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return 0.0


def build_tse_database(cache_dir: str) -> dict:
    ensure_tse_files(cache_dir)

    # 1. Votação nominal por município/turno em 2024
    votos_2024 = defaultdict(lambda: {"1": 0, "2": 0})
    tot_pref_validos = defaultdict(lambda: {"1": 0, "2": 0})
    for uf in UFS:
        vot_path = os.path.join(cache_dir, f"votacao_candidato_munzona_2024_{uf}.csv")
        if not os.path.exists(vot_path):
            continue
        with open(vot_path, encoding="latin1") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("CD_TIPO_ELEICAO", "").strip() != "2":
                    continue
                ue_n = norm(r.get("NM_UE", ""))
                if (ue_n, uf) not in TARGET_UES:
                    continue
                turno = r.get("NR_TURNO", "1").strip()
                sq = r.get("SQ_CANDIDATO", "").strip()
                v_str = r.get("QT_VOTOS_NOMINAIS_VALIDOS") or r.get("QT_VOTOS_NOMINAIS") or "0"
                v_int = int(v_str) if v_str.isdigit() else 0
                votos_2024[sq][turno] += v_int
                if r.get("CD_CARGO", "").strip() == "11":
                    tot_pref_validos[(ue_n, uf)][turno] += v_int

    # 2. Ler candidatos de 2024 nas 13 cidades-alvo (Vereador, Prefeito, Vice-Prefeito)
    cands_2024_by_sq = {}
    for uf in UFS:
        c24_path = os.path.join(cache_dir, f"consulta_cand_2024_{uf}.csv")
        if not os.path.exists(c24_path):
            continue
        with open(c24_path, encoding="latin1") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("CD_TIPO_ELEICAO", "").strip() != "2":
                    continue
                ue_n = norm(r.get("NM_UE", ""))
                if (ue_n, uf) not in TARGET_UES:
                    continue
                sq = r.get("SQ_CANDIDATO", "").strip()
                turno = r.get("NR_TURNO", "1").strip()
                prev = cands_2024_by_sq.get(sq)
                if prev and int(turno) < int(prev["turno"]):
                    continue
                sit_cand = norm(r.get("DS_SITUACAO_CANDIDATURA", ""))
                sit_tot = norm(r.get("DS_SIT_TOT_TURNO", ""))
                if "INAPTO" in sit_cand and "ELEITO" not in sit_tot and "SUPLENTE" not in sit_tot:
                    continue
                cands_2024_by_sq[sq] = {
                    "sq": sq,
                    "uf": uf,
                    "ue_norm": ue_n,
                    "city_slug": TARGET_UES[(ue_n, uf)],
                    "cargo_cd": r.get("CD_CARGO", "").strip(),
                    "cargo_ds": r.get("DS_CARGO", "").strip(),
                    "nr": r.get("NR_CANDIDATO", "").strip(),
                    "nome": r.get("NM_CANDIDATO", "").strip(),
                    "nome_norm": norm(r.get("NM_CANDIDATO", "")),
                    "urna": r.get("NM_URNA_CANDIDATO", "").strip(),
                    "urna_norm": norm(r.get("NM_URNA_CANDIDATO", "")),
                    "cpf": clean_id(r.get("NR_CPF_CANDIDATO", "")),
                    "titulo": clean_id(r.get("NR_TITULO_ELEITORAL_CANDIDATO", "")),
                    "nasc": r.get("DT_NASCIMENTO", "").strip(),
                    "part": r.get("SG_PARTIDO", "").strip(),
                    "colig": r.get("SQ_COLIGACAO", "").strip(),
                    "is_fem": r.get("CD_GENERO", "").strip() == "4",
                    "turno": turno,
                    "sit_raw": r.get("DS_SIT_TOT_TURNO", "").strip(),
                }

    target_titulos = {c["titulo"] for c in cands_2024_by_sq.values() if c["titulo"]}
    target_cpfs = {c["cpf"] for c in cands_2024_by_sq.values() if c["cpf"]}
    target_names = {c["nome_norm"] for c in cands_2024_by_sq.values() if c["nome_norm"]}

    # 3. Varrer consulta_cand de 2012 a 2026 nos 8 estados
    hist_by_yr_sq = {}
    matched_sqs_by_yr_uf = defaultdict(set)

    for yr in ALL_YEARS:
        for uf in UFS:
            cpath = os.path.join(cache_dir, f"consulta_cand_{yr}_{uf}.csv")
            if not os.path.exists(cpath):
                continue
            with open(cpath, encoding="latin1") as f:
                for r in csv.DictReader(f, delimiter=";"):
                    if r.get("CD_TIPO_ELEICAO", "").strip() != "2":
                        continue
                    tit = clean_id(r.get("NR_TITULO_ELEITORAL_CANDIDATO", ""))
                    cpf = clean_id(r.get("NR_CPF_CANDIDATO", ""))
                    nm_n = norm(r.get("NM_CANDIDATO", ""))
                    if not (
                        (tit and tit in target_titulos)
                        or (cpf and cpf in target_cpfs)
                        or (nm_n and nm_n in target_names)
                    ):
                        continue
                    sit_tot = r.get("DS_SIT_TOT_TURNO", "").strip()
                    sit_cand = norm(r.get("DS_SITUACAO_CANDIDATURA", ""))
                    if yr < 2026 and norm(sit_tot) in ("#NULO#", "#NE", "-1", "") and (
                        "RENUNCIA" in sit_cand or "INAPTO" in sit_cand or "CANCELAD" in sit_cand
                    ):
                        continue
                    sq = r.get("SQ_CANDIDATO", "").strip()
                    turno = r.get("NR_TURNO", "1").strip()
                    key = (yr, sq)
                    prev = hist_by_yr_sq.get(key)
                    if prev and int(turno) < int(prev["turno"]):
                        continue
                    hist_by_yr_sq[key] = {
                        "ano": yr,
                        "uf": uf,
                        "sq": sq,
                        "ue_norm": norm(r.get("NM_UE", "")),
                        "cargo_ds": r.get("DS_CARGO", "").strip(),
                        "part": r.get("SG_PARTIDO", "").strip(),
                        "sit_raw": sit_tot,
                        "turno": turno,
                        "titulo": tit,
                        "cpf": cpf,
                        "nome_norm": nm_n,
                        "nasc": r.get("DT_NASCIMENTO", "").strip(),
                    }
                    matched_sqs_by_yr_uf[(yr, uf)].add(sq)

    # 4. Somar receitas e despesas contratadas apenas dos SQ_CANDIDATO relevantes
    rec_map = defaultdict(float)
    desp_map = defaultdict(float)

    def sum_accounts_for_yr_uf(yr_uf):
        yr, uf = yr_uf
        sqs_needed = matched_sqs_by_yr_uf.get((yr, uf), set())
        if not sqs_needed:
            return {}, {}
        r_loc = defaultdict(float)
        d_loc = defaultdict(float)
        r_path = os.path.join(cache_dir, f"receitas_candidatos_{yr}_{uf}.csv")
        d_path = os.path.join(cache_dir, f"despesas_contratadas_candidatos_{yr}_{uf}.csv")
        if os.path.exists(r_path):
            with open(r_path, encoding="latin1", errors="replace") as f:
                for row in csv.DictReader((ln.replace("\x00", "") for ln in f), delimiter=";"):
                    sq = row.get("SQ_CANDIDATO", "").strip()
                    if sq in sqs_needed:
                        r_loc[sq] += parse_brl(row.get("VR_RECEITA", "0"))
        if os.path.exists(d_path):
            with open(d_path, encoding="latin1", errors="replace") as f:
                for row in csv.DictReader((ln.replace("\x00", "") for ln in f), delimiter=";"):
                    sq = row.get("SQ_CANDIDATO", "").strip()
                    if sq in sqs_needed:
                        d_loc[sq] += parse_brl(row.get("VR_DESPESA_CONTRATADA", "0"))
        return r_loc, d_loc

    yr_uf_keys = [(yr, uf) for yr in ACCOUNTS_YEARS for uf in UFS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        fut_map = {ex.submit(sum_accounts_for_yr_uf, k): k for k in yr_uf_keys}
        for fut in concurrent.futures.as_completed(fut_map):
            yr, _ = fut_map[fut]
            rl, dl = fut.result()
            for sq, v in rl.items():
                rec_map[(yr, sq)] = round(v, 2)
            for sq, v in dl.items():
                desp_map[(yr, sq)] = round(v, 2)

    by_titulo = defaultdict(list)
    by_cpf = defaultdict(list)
    by_name = defaultdict(list)
    for rec in hist_by_yr_sq.values():
        if rec["titulo"]:
            by_titulo[rec["titulo"]].append(rec)
        if rec["cpf"]:
            by_cpf[rec["cpf"]].append(rec)
        if rec["nome_norm"]:
            by_name[rec["nome_norm"]].append(rec)

    # 5. Consolidar por cidade
    out_cities = {slug: {"prefeito": None, "vice": None, "vereadores": []} for slug in TARGET_UES.values()}

    vices_eleitos = {}
    for c in cands_2024_by_sq.values():
        if c["cargo_cd"] == "12" and "ELEITO" in norm(c["sit_raw"]) and "NAO" not in norm(c["sit_raw"]):
            vices_eleitos[c["city_slug"]] = c["urna"]

    for c in cands_2024_by_sq.values():
        slug = c["city_slug"]
        ue_n = c["ue_norm"]
        uf = c["uf"]
        sit_n = norm(c["sit_raw"])

        is_mayor_elected = c["cargo_cd"] == "11" and "ELEITO" in sit_n and "NAO" not in sit_n
        is_councilor_pool = c["cargo_cd"] == "13" and (
            ("ELEITO" in sit_n and "NAO" not in sit_n) or "SUPLENTE" in sit_n
        )
        if not (is_mayor_elected or is_councilor_pool):
            continue

        matched_records = {}
        if c["titulo"] and c["titulo"] in by_titulo:
            for r in by_titulo[c["titulo"]]:
                matched_records[(r["ano"], r["sq"])] = r
        if c["cpf"] and c["cpf"] in by_cpf:
            for r in by_cpf[c["cpf"]]:
                matched_records[(r["ano"], r["sq"])] = r
        for r in by_name.get(c["nome_norm"], []):
            if (r["ano"], r["sq"]) in matched_records:
                continue
            if c["nasc"] and r["nasc"] and c["nasc"] != r["nasc"]:
                continue
            if r["ano"] in MUNICIPAL_YEARS and (r["ue_norm"] != ue_n or r["uf"] != uf):
                continue
            if c["titulo"] and r["titulo"] and c["titulo"] != r["titulo"]:
                continue
            matched_records[(r["ano"], r["sq"])] = r

        hist_list = []
        outras_list = []
        gasto20 = 0.0
        for (_, _), r in sorted(matched_records.items(), key=lambda kv: (-kv[1]["ano"], kv[1]["sq"])):
            yr = r["ano"]
            rec_v = rec_map.get((yr, r["sq"]), 0.0)
            desp_v = desp_map.get((yr, r["sq"]), 0.0)
            cargo_fmt = format_cargo(r["cargo_ds"], c["is_fem"])
            sit_fmt = format_sit(r["sit_raw"], r["turno"], c["is_fem"], norm(r["cargo_ds"]))
            item_h = {
                "ano": yr,
                "cargo": cargo_fmt,
                "part": r["part"],
                "sit": sit_fmt,
                "rec": rec_v,
                "desp": desp_v,
            }
            hist_list.append(item_h)
            if yr == 2020 and norm(r["cargo_ds"]) == "VEREADOR":
                gasto20 = desp_v
            if norm(r["cargo_ds"]) != "VEREADOR" and not (is_mayor_elected and yr == 2024 and norm(r["cargo_ds"]) == "PREFEITO"):
                outras_list.append(item_h)

        rec24 = rec_map.get((2024, c["sq"]), 0.0)
        gasto24 = desp_map.get((2024, c["sq"]), 0.0)
        v1 = votos_2024[c["sq"]]["1"]
        v2 = votos_2024[c["sq"]]["2"]

        if is_mayor_elected:
            v_ref = v2 if v2 > 0 else v1
            cpv24 = round(gasto24 / v_ref, 2) if v_ref > 0 else 0.0
            tot1 = tot_pref_validos[(ue_n, uf)]["1"] or 1
            tot2 = tot_pref_validos[(ue_n, uf)]["2"] or 0
            pct_1t = f"{100.0 * v1 / tot1:.2f}%".replace(".", ",")
            pct_2t = f"{100.0 * v2 / tot2:.2f}%".replace(".", ",") if tot2 > 0 and v2 > 0 else ""
            out_cities[slug]["prefeito"] = {
                "urna": c["urna"],
                "civil": c["nome"].title(),
                "nome_norm": c["nome_norm"],
                "part": c["part"],
                "vice": vices_eleitos.get(slug, ""),
                "votos_1t": v1,
                "votos_2t": v2,
                "pct_1t": pct_1t,
                "pct_2t": pct_2t,
                "rec24": rec24,
                "gasto24": gasto24,
                "cpv24": cpv24,
                "outras": outras_list,
                "hist": hist_list,
            }
        else:
            cpv24 = round(gasto24 / v1, 2) if v1 > 0 else 0.0
            out_cities[slug]["vereadores"].append({
                "sq24": c["sq"],
                "nr": c["nr"],
                "urna": c["urna"],
                "urna_norm": c["urna_norm"],
                "civil": c["nome"],
                "nome_norm": c["nome_norm"],
                "part24": c["part"],
                "sit24": format_sit(c["sit_raw"], "1", c["is_fem"], "VEREADOR"),
                "eleito24": "ELEITO" in sit_n and "NAO" not in sit_n,
                "votos24": v1,
                "rec24": rec24,
                "gasto24": gasto24,
                "cpv24": cpv24,
                "gasto20": gasto20,
                "outras": outras_list,
                "hist": hist_list,
            })

    for slug in out_cities:
        out_cities[slug]["vereadores"].sort(key=lambda x: (-int(x["eleito24"]), -x["votos24"]))

    return out_cities


def main():
    cache_dir = DEFAULT_CACHE
    if "--cache-dir" in sys.argv:
        cache_dir = sys.argv[sys.argv.index("--cache-dir") + 1]
    t0 = time.time()
    db = build_tse_database(cache_dir)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"Base TSE 2012–2026 consolidada em {time.time() - t0:.1f}s -> {OUT_JSON} ({os.path.getsize(OUT_JSON)//1024} KB)")
    for slug, info in db.items():
        eleitos = [v for v in info["vereadores"] if v["eleito24"]]
        cand26 = [v for v in eleitos if any(o["ano"] == 2026 for o in v["outras"])]
        p = info["prefeito"] or {}
        print(
            f"  [{slug:20s}] eleitos_2024={len(eleitos):2d} (+{len(info['vereadores'])-len(eleitos):3d} supl.) | "
            f"cand_2026={len(cand26):2d} | Prefeito={p.get('urna')} ({p.get('part')}) R$ {p.get('gasto24',0):,.2f}"
        )


if __name__ == "__main__":
    main()
