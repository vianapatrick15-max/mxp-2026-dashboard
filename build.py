#!/usr/bin/env python3
"""MXP-Fp01 2026 — dashboard de tráfego x vendas reais.

Duas fontes:
  TRAFEGO = planilha "MXP-Fp01 META ADS", aba dados_trafego (Meta, nivel ad/dia)
  VENDAS  = planilha "[MXP-FP01][VENDAS][2026]", aba VENDAS (Hubla, webhook n8n + backfill)

Gera data.json + index.html auto-contido (SVG nativo, sem lib externa).
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.expanduser("~/.claude/skills/google-sheets/scripts"))
from lib.auth import get_gspread_client  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TRAFEGO_ID = "12ldEcVBAyIWcX2APu3CVS82aeswbwxsbJZCYIGN4KKY"
TRAFEGO_TAB = "dados_trafego"
VENDAS_ID = "13uDvwhiiaLsiob1IDzSiGwpktCuZXWUWYXnzyL__3vQ"
VENDAS_TAB = "VENDAS"

# ---------------------------------------------------------------- metas
# Plano fechado com o cliente. Revisar dia 15/08.
METAS = {
    "deadline": "2026-08-15",
    "inicio": "2026-08-01",
    "vendas": 150,
    "faturamento": 29550.0,
    "investimento": 22500.0,
    "cac_max": 150.0,
    "roas": 1.3,
    "vendas_dia": 10,
    "investimento_dia": 1500.0,
}

# benchmark de visita -> checkout em venda de ingresso/evento. Abaixo disso o
# gargalo e a pagina, nao o criativo.
BENCH_LPV_IC = 3.0

# utm_source -> rotulo de frente. O que nao casar entra como "outros".
FRENTES = {
    "meta_ads": ("Meta Ads", "pago"),
    "facebook": ("Meta Ads", "pago"),
    "instagram": ("Meta Ads", "pago"),
    "whatsapp": ("WhatsApp", "proprio"),
    "email": ("E-mail", "proprio"),
    "sms": ("SMS", "proprio"),
    "organico": ("Orgânico", "proprio"),
    "bio": ("Bio / Orgânico", "proprio"),
}


def num(x):
    """Aceita '2,55', '1.234,56', '1485.6', '' -> float."""
    s = str(x or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_dt(s):
    for f in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y, %H:%M:%S", "%d/%m/%Y %H:%M",
              "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip(), f)
        except (ValueError, TypeError):
            continue
    return None


def ad_code(s):
    """'[AD-11][VID][VD][MXP-Fp01]' -> 'AD-11'. Casa utm_content com Ad Name."""
    m = re.search(r"\[?(AD-?\d+)\]?", str(s or "").upper().replace("_", "-"))
    if not m:
        return ""
    n = re.sub(r"\D", "", m.group(1))
    return f"AD-{int(n):02d}" if n else ""


def frente(src):
    s = str(src or "").strip().lower()
    if not s:
        return ("Sem origem", "indefinido")
    for k, v in FRENTES.items():
        if k in s:
            return v
    return (s, "outros")


# ---------------------------------------------------------------- coleta
def coletar():
    gc = get_gspread_client()

    tv = gc.open_by_key(TRAFEGO_ID).worksheet(TRAFEGO_TAB).get_values()
    th = {k: i for i, k in enumerate(tv[0])}
    trafego = []
    for r in tv[1:]:
        if not (r[th["Date"]] or "").strip():
            continue
        trafego.append({
            "data": r[th["Date"]].strip(),
            "campanha": r[th["Campaign Name"]].strip(),
            "adset": r[th["Adset Name"]].strip(),
            "ad": r[th["Ad Name"]].strip(),
            "ad_code": ad_code(r[th["Ad Name"]]),
            "spend": num(r[th["Spend (Cost, Amount Spent)"]]),
            "impr": num(r[th["Impressions"]]),
            "alcance": num(r[th["Reach (Estimated)"]]),
            "clicks": num(r[th["Action Link Clicks"]]),
            "lpv": num(r[th["Action Landing Page View"]]),
            "ic": num(r[th["Action Omni Initiated Checkout"]]),
            "purch_pixel": num(r[th["Action Omni Purchase"]]),
            "vv": num(r[th["Action Video View"]]),
            "status_ad": r[th["Ad Status"]].strip(),
            "ig": r[th["Instagram Permalink URL"]].strip(),
        })

    sv = gc.open_by_key(VENDAS_ID).worksheet(VENDAS_TAB).get_values()
    sh = {k: i for i, k in enumerate(sv[0])}
    vendas = []
    for r in sv[1:]:
        if not (r[sh["id_fatura"]] or "").strip():
            continue
        dt = parse_dt(r[sh["data_venda"]])
        src = r[sh["utm_source"]].strip()
        nome_f, tipo_f = frente(src)
        vendas.append({
            "id": r[sh["id_fatura"]].strip(),
            "data": dt.strftime("%Y-%m-%d") if dt else "",
            "hora": dt.strftime("%H:%M") if dt else "",
            "status": r[sh["status"]].strip(),
            "oferta": r[sh["oferta"]].strip() or "(sem oferta)",
            "valor": num(r[sh["valor"]]),
            "utm_source": src,
            "utm_campaign": r[sh["utm_campaign"]].strip(),
            "utm_content": r[sh["utm_content"]].strip(),
            "ad_code": ad_code(r[sh["utm_content"]]),
            "frente": nome_f,
            "tipo": tipo_f,
        })
    return trafego, vendas


# ---------------------------------------------------------------- agregacao
MET = ("spend", "impr", "clicks", "lpv", "ic", "purch_pixel", "vv", "alcance")


def soma(rows, chave):
    out = defaultdict(Counter)
    for r in rows:
        for m in MET:
            out[r[chave]][m] += r[m]
    return out


def build():
    trafego, vendas = coletar()

    # venda valida = nao reembolsada/cancelada
    perdidas = [v for v in vendas if v["status"] in ("refunded", "canceled", "chargeback")]
    vendas_ok = [v for v in vendas if v not in perdidas]

    tot_t = Counter()
    for r in trafego:
        for m in MET:
            tot_t[m] += r[m]

    receita = sum(v["valor"] for v in vendas_ok)
    n_vendas = len(vendas_ok)

    # --- frentes (utm_source) -------------------------------------------
    fr = defaultdict(lambda: {"vendas": 0, "receita": 0.0, "tipo": "", "sources": set()})
    for v in vendas_ok:
        f = fr[v["frente"]]
        f["vendas"] += 1
        f["receita"] += v["valor"]
        f["tipo"] = v["tipo"]
        f["sources"].add(v["utm_source"] or "(vazio)")
    frentes = []
    for nome, d in sorted(fr.items(), key=lambda x: -x[1]["receita"]):
        pago = d["tipo"] == "pago"
        frentes.append({
            "frente": nome, "tipo": d["tipo"], "vendas": d["vendas"],
            "receita": round(d["receita"], 2),
            "pct_receita": round(100 * d["receita"] / receita, 1) if receita else 0,
            "ticket": round(d["receita"] / d["vendas"], 2) if d["vendas"] else 0,
            "investido": round(tot_t["spend"], 2) if pago else None,
            "cpa": round(tot_t["spend"] / d["vendas"], 2) if pago and d["vendas"] else None,
            "roas": round(d["receita"] / tot_t["spend"], 2) if pago and tot_t["spend"] else None,
            "sources": sorted(d["sources"]),
        })

    vendas_pagas = [v for v in vendas_ok if v["tipo"] == "pago"]
    receita_paga = sum(v["valor"] for v in vendas_pagas)

    # --- funil pago ------------------------------------------------------
    def taxa(a, b):
        return round(100 * a / b, 2) if b else 0

    def custo(b):
        return round(tot_t["spend"] / b, 2) if b else 0

    funil = [
        {"etapa": "Impressões", "n": int(tot_t["impr"]), "taxa": None,
         "taxa_lbl": "", "custo": round(1000 * tot_t["spend"] / tot_t["impr"], 2) if tot_t["impr"] else 0,
         "custo_lbl": "CPM"},
        {"etapa": "Cliques no link", "n": int(tot_t["clicks"]),
         "taxa": taxa(tot_t["clicks"], tot_t["impr"]), "taxa_lbl": "CTR",
         "custo": custo(tot_t["clicks"]), "custo_lbl": "CPC"},
        {"etapa": "Visitas na página", "n": int(tot_t["lpv"]),
         "taxa": taxa(tot_t["lpv"], tot_t["clicks"]), "taxa_lbl": "clique → página",
         "custo": custo(tot_t["lpv"]), "custo_lbl": "custo/visita"},
        {"etapa": "Checkouts iniciados", "n": int(tot_t["ic"]),
         "taxa": taxa(tot_t["ic"], tot_t["lpv"]), "taxa_lbl": "página → checkout",
         "custo": custo(tot_t["ic"]), "custo_lbl": "custo/checkout"},
        {"etapa": "Vendas (Hubla)", "n": len(vendas_pagas),
         "taxa": taxa(len(vendas_pagas), tot_t["ic"]), "taxa_lbl": "checkout → venda",
         "custo": custo(len(vendas_pagas)), "custo_lbl": "CPA real"},
    ]

    # --- serie diaria ----------------------------------------------------
    dias = sorted({r["data"] for r in trafego} | {v["data"] for v in vendas_ok if v["data"]})
    por_dia_t = soma(trafego, "data")
    serie = []
    for d in dias:
        vd = [v for v in vendas_ok if v["data"] == d]
        vp = [v for v in vd if v["tipo"] == "pago"]
        serie.append({
            "data": d,
            "spend": round(por_dia_t[d]["spend"], 2),
            "lpv": int(por_dia_t[d]["lpv"]),
            "ic": int(por_dia_t[d]["ic"]),
            "vendas": len(vd), "receita": round(sum(x["valor"] for x in vd), 2),
            "vendas_pagas": len(vp), "receita_paga": round(sum(x["valor"] for x in vp), 2),
        })

    # --- campanhas -------------------------------------------------------
    por_camp = soma(trafego, "campanha")
    vendas_camp = Counter()
    receita_camp = Counter()
    for v in vendas_pagas:
        for c in por_camp:
            if v["utm_campaign"] and v["utm_campaign"].lower() == c.lower():
                vendas_camp[c] += 1
                receita_camp[c] += v["valor"]
    campanhas = []
    for c, m in sorted(por_camp.items(), key=lambda x: -x[1]["spend"]):
        campanhas.append({
            "campanha": c, "spend": round(m["spend"], 2), "impr": int(m["impr"]),
            "clicks": int(m["clicks"]), "lpv": int(m["lpv"]), "ic": int(m["ic"]),
            "ctr": taxa(m["clicks"], m["impr"]),
            "cpm": round(1000 * m["spend"] / m["impr"], 2) if m["impr"] else 0,
            "custo_lpv": round(m["spend"] / m["lpv"], 2) if m["lpv"] else 0,
            "custo_ic": round(m["spend"] / m["ic"], 2) if m["ic"] else 0,
            "vendas": vendas_camp[c], "receita": round(receita_camp[c], 2),
            "cpa": round(m["spend"] / vendas_camp[c], 2) if vendas_camp[c] else None,
        })

    # --- criativos -------------------------------------------------------
    por_ad = defaultdict(lambda: Counter())
    meta_ad = {}
    for r in trafego:
        k = r["ad_code"] or r["ad"]
        for m in MET:
            por_ad[k][m] += r[m]
        meta_ad.setdefault(k, {"ad": r["ad"], "campanha": r["campanha"], "ig": r["ig"],
                               "status": r["status_ad"]})
        if r["ig"]:
            meta_ad[k]["ig"] = r["ig"]
    vendas_ad = Counter()
    receita_ad = Counter()
    for v in vendas_pagas:
        if v["ad_code"]:
            vendas_ad[v["ad_code"]] += 1
            receita_ad[v["ad_code"]] += v["valor"]
    criativos = []
    for k, m in sorted(por_ad.items(), key=lambda x: -x[1]["spend"]):
        criativos.append({
            "ad": k, "nome": meta_ad[k]["ad"], "campanha": meta_ad[k]["campanha"],
            "tipo": "Vídeo" if "[VID]" in meta_ad[k]["ad"].upper() else "Estático",
            "status": meta_ad[k]["status"], "ig": meta_ad[k]["ig"],
            "spend": round(m["spend"], 2), "impr": int(m["impr"]),
            "clicks": int(m["clicks"]), "lpv": int(m["lpv"]), "ic": int(m["ic"]),
            "ctr": taxa(m["clicks"], m["impr"]),
            "cpm": round(1000 * m["spend"] / m["impr"], 2) if m["impr"] else 0,
            "custo_lpv": round(m["spend"] / m["lpv"], 2) if m["lpv"] else 0,
            "vendas": vendas_ad[k], "receita": round(receita_ad[k], 2),
            "cpa": round(m["spend"] / vendas_ad[k], 2) if vendas_ad[k] else None,
        })

    # --- ofertas ---------------------------------------------------------
    of = defaultdict(lambda: {"n": 0, "receita": 0.0})
    for v in vendas_ok:
        of[v["oferta"]]["n"] += 1
        of[v["oferta"]]["receita"] += v["valor"]
    ofertas = [{"oferta": k, "vendas": d["n"], "receita": round(d["receita"], 2),
                "ticket": round(d["receita"] / d["n"], 2)}
               for k, d in sorted(of.items(), key=lambda x: -x[1]["receita"])]

    # --- metas e pacing ---------------------------------------------------
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ini = datetime.strptime(METAS["inicio"], "%Y-%m-%d")
    fim = datetime.strptime(METAS["deadline"], "%Y-%m-%d")
    dias_totais = (fim - ini).days + 1
    dias_corridos = max(1, min((hoje - ini).days + 1, dias_totais))
    dias_restantes = max(1, (fim - hoje).days + 1)
    fracao = dias_corridos / dias_totais

    def linha(chave, label, meta, real, direcao, unidade, plano_dia=None, obs="",
              acumula=True):
        """direcao 'up' = quanto maior melhor; 'down' = quanto menor melhor.
        acumula=False para razoes (CAC, ROAS): comparam direto com o alvo, sem
        rateio por dia e sem 'falta'."""
        esperado = meta * fracao if (direcao == "up" and acumula) else meta
        if direcao == "up" and acumula:
            razao = real / esperado if esperado else 0
            status = "pos" if razao >= 1 else ("neg" if razao < 0.8 else "warn")
            falta = max(meta - real, 0)
            nec_dia = falta / dias_restantes
        else:
            razao = real / meta if meta else 0
            status = "pos" if real <= meta else ("neg" if real > meta * 1.2 else "warn")
            falta, nec_dia = 0, None
        if not acumula:
            razao = real / meta if meta else 0
            if direcao == "up":
                status = "pos" if real >= meta else ("neg" if real < meta * 0.8 else "warn")
            falta, nec_dia = 0, None
        return {"chave": chave, "label": label, "acumula": acumula,
                "meta": round(meta, 2),
                "realizado": round(real, 2), "esperado_hoje": round(esperado, 2),
                "pct": round(100 * real / meta, 1) if meta else 0,
                "status": status, "unidade": unidade, "direcao": direcao,
                "falta": round(falta, 2),
                "nec_dia": round(nec_dia, 2) if nec_dia is not None else None,
                "plano_dia": plano_dia, "obs": obs}

    ritmo_vendas = n_vendas / dias_corridos
    ritmo_receita = receita / dias_corridos
    ritmo_spend = tot_t["spend"] / dias_corridos
    cac_atual = tot_t["spend"] / n_vendas if n_vendas else 0
    roas_atual = receita / tot_t["spend"] if tot_t["spend"] else 0

    metas = {
        "deadline": fim.strftime("%d/%m/%Y"), "inicio": ini.strftime("%d/%m/%Y"),
        "hoje": hoje.strftime("%d/%m/%Y"),
        "dias_totais": dias_totais, "dias_corridos": dias_corridos,
        "dias_restantes": dias_restantes,
        "linhas": [
            linha("vendas", "Vendas", METAS["vendas"], n_vendas, "up", "int",
                  METAS["vendas_dia"], "Toda venda registrada na Hubla, de qualquer frente."),
            linha("faturamento", "Faturamento", METAS["faturamento"], receita, "up", "brl",
                  METAS["faturamento"] / dias_totais, "Receita bruta das vendas válidas."),
            linha("investimento", "Investimento", METAS["investimento"], tot_t["spend"], "up", "brl",
                  METAS["investimento_dia"], "Verba prevista para o Meta no período."),
            linha("cac", "CAC", METAS["cac_max"], cac_atual, "down", "brl", None,
                  "Investimento dividido por todas as vendas (blended, como no plano).",
                  acumula=False),
            linha("roas", "ROAS", METAS["roas"], roas_atual, "up", "x", None,
                  "Faturamento dividido pelo investimento.", acumula=False),
        ],
        "ritmo": {
            "vendas_dia": round(ritmo_vendas, 2),
            "receita_dia": round(ritmo_receita, 2),
            "spend_dia": round(ritmo_spend, 2),
            "vendas_dia_plano": METAS["vendas_dia"],
            "spend_dia_plano": METAS["investimento_dia"],
        },
        "projecao": {
            "vendas": round(ritmo_vendas * dias_totais),
            "receita": round(ritmo_receita * dias_totais, 2),
            "spend": round(ritmo_spend * dias_totais, 2),
            "pct_meta": round(100 * ritmo_vendas * dias_totais / METAS["vendas"], 1),
        },
        "cac_max": METAS["cac_max"], "roas_meta": METAS["roas"],
        "ticket_plano": round(METAS["faturamento"] / METAS["vendas"], 2),
        "ticket_real": round(receita / n_vendas, 2) if n_vendas else 0,
    }

    data = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "metas": metas, "bench_lpv_ic": BENCH_LPV_IC,
        "janela_trafego": [min(r["data"] for r in trafego), max(r["data"] for r in trafego)] if trafego else ["", ""],
        "janela_vendas": [min(v["data"] for v in vendas_ok if v["data"]),
                          max(v["data"] for v in vendas_ok if v["data"])] if vendas_ok else ["", ""],
        "kpi": {
            "receita": round(receita, 2), "vendas": n_vendas,
            "ticket": round(receita / n_vendas, 2) if n_vendas else 0,
            "investido": round(tot_t["spend"], 2),
            "roas_geral": round(receita / tot_t["spend"], 2) if tot_t["spend"] else 0,
            "cac_blended": round(tot_t["spend"] / n_vendas, 2) if n_vendas else 0,
            "vendas_pagas": len(vendas_pagas), "receita_paga": round(receita_paga, 2),
            "roas_pago": round(receita_paga / tot_t["spend"], 2) if tot_t["spend"] else 0,
            "cpa_pago": round(tot_t["spend"] / len(vendas_pagas), 2) if vendas_pagas else 0,
            "purch_pixel": int(tot_t["purch_pixel"]),
            "reembolsos": len(perdidas),
            "receita_perdida": round(sum(v["valor"] for v in perdidas), 2),
            "ads_ativos": sum(1 for c in criativos if c["spend"] > 0),
        },
        "frentes": frentes, "funil": funil, "serie": serie,
        "campanhas": campanhas, "criativos": criativos, "ofertas": ofertas,
    }

    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"trafego: {len(trafego)} linhas | vendas: {len(vendas_ok)} (perdidas {len(perdidas)})")
    print(f"investido R$ {tot_t['spend']:.2f} | receita R$ {receita:.2f} | ROAS geral {data['kpi']['roas_geral']}")
    print(f"pago: {len(vendas_pagas)} vendas | CPA R$ {data['kpi']['cpa_pago']} | ROAS {data['kpi']['roas_pago']}")
    print("index.html + data.json gerados")


if __name__ == "__main__":
    build()
