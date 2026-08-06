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


MIDIA = {"VID": "Vídeo", "EST": "Estático", "CAR": "Carrossel", "IMG": "Imagem"}


def ad_code(s):
    """'[AD-11][VID][VD][MXP-Fp01]' -> 'AD-11|VID'.

    O codigo sozinho NAO identifica o anuncio: AD-11 existe na campanha de
    estaticos E na de videos. A chave tem que levar o formato junto, senao os
    dois viram uma linha so. Mesma regra vale pro utm_content da Hubla, que
    carrega os mesmos tokens.
    """
    up = str(s or "").upper().replace("_", "-")
    m = re.search(r"\[?(AD-?\d+)\]?", up)
    if not m:
        return ""
    n = re.sub(r"\D", "", m.group(1))
    if not n:
        return ""
    fmt = next((k for k in MIDIA if f"[{k}]" in up), "")
    return f"AD-{int(n):02d}" + (f"|{fmt}" if fmt else "")


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

    perdidas = {"refunded", "canceled", "chargeback"}
    vendas_ok = [v for v in vendas if v["status"] not in perdidas]

    # --- dados crus para o navegador agregar por periodo -------------------
    # chaves curtas: o arquivo vai embutido no HTML.
    ads = {}
    for r in trafego:
        k = r["ad_code"] or r["ad"]
        fmt = k.split("|")[1] if "|" in k else ""
        a = ads.setdefault(k, {"nome": r["ad"], "camp": r["campanha"], "ig": "",
                               "status": r["status_ad"],
                               "rotulo": k.replace("|", " "),
                               "tipo": MIDIA.get(fmt, "")})
        if r["ig"]:
            a["ig"] = r["ig"]
        if r["status_ad"] == "ACTIVE":
            a["status"] = "ACTIVE"

    traf = [{"d": r["data"], "c": r["campanha"], "a": r["ad_code"] or r["ad"],
             "s": round(r["spend"], 2), "i": int(r["impr"]), "k": int(r["clicks"]),
             "l": int(r["lpv"]), "ic": int(r["ic"]), "p": int(r["purch_pixel"])}
            for r in trafego]

    vds = [{"d": v["data"], "f": v["frente"], "t": v["tipo"], "v": round(v["valor"], 2),
            "o": v["oferta"], "a": v["ad_code"], "c": v["utm_campaign"],
            "src": v["utm_source"]}
           for v in vendas_ok if v["data"]]

    # --- metas: sempre no periodo cheio do plano, independem do filtro ----
    tot_spend = sum(r["spend"] for r in trafego)
    receita = sum(v["valor"] for v in vendas_ok)
    n_vendas = len(vendas_ok)

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ini = datetime.strptime(METAS["inicio"], "%Y-%m-%d")
    fim = datetime.strptime(METAS["deadline"], "%Y-%m-%d")
    dias_totais = (fim - ini).days + 1
    dias_corridos = max(1, min((hoje - ini).days + 1, dias_totais))
    dias_restantes = max(1, (fim - hoje).days + 1)
    fracao = dias_corridos / dias_totais

    def linha(chave, label, meta, real, direcao, unidade, obs="", acumula=True):
        esperado = meta * fracao if (direcao == "up" and acumula) else meta
        falta, nec_dia = 0, None
        if acumula:
            razao = real / esperado if esperado else 0
            status = "pos" if razao >= 1 else ("neg" if razao < 0.8 else "warn")
            falta = max(meta - real, 0)
            nec_dia = falta / dias_restantes
        elif direcao == "up":
            status = "pos" if real >= meta else ("neg" if real < meta * 0.8 else "warn")
        else:
            status = "pos" if real <= meta else ("neg" if real > meta * 1.2 else "warn")
        return {"chave": chave, "label": label, "acumula": acumula,
                "meta": round(meta, 2), "realizado": round(real, 2),
                "esperado_hoje": round(esperado, 2),
                "pct": round(100 * real / meta, 1) if meta else 0,
                "status": status, "unidade": unidade, "direcao": direcao,
                "falta": round(falta, 2),
                "nec_dia": round(nec_dia, 2) if nec_dia is not None else None,
                "obs": obs}

    cac = tot_spend / n_vendas if n_vendas else 0
    roas = receita / tot_spend if tot_spend else 0
    metas = {
        "deadline": fim.strftime("%d/%m/%Y"), "inicio": ini.strftime("%d/%m/%Y"),
        "dias_totais": dias_totais, "dias_corridos": dias_corridos,
        "dias_restantes": dias_restantes,
        "linhas": [
            linha("vendas", "Vendas", METAS["vendas"], n_vendas, "up", "int",
                  "Toda venda registrada na Hubla, de qualquer frente."),
            linha("faturamento", "Faturamento", METAS["faturamento"], receita, "up", "brl",
                  "Receita bruta das vendas válidas."),
            linha("investimento", "Investimento", METAS["investimento"], tot_spend, "up", "brl",
                  "Verba prevista para o Meta no período."),
            linha("cac", "CAC", METAS["cac_max"], cac, "down", "brl",
                  "Investimento dividido por todas as vendas (blended, como no plano).",
                  acumula=False),
            linha("roas", "ROAS", METAS["roas"], roas, "up", "x",
                  "Faturamento dividido pelo investimento.", acumula=False),
        ],
        "ritmo": {
            "vendas_dia": round(n_vendas / dias_corridos, 2),
            "spend_dia": round(tot_spend / dias_corridos, 2),
            "vendas_dia_plano": METAS["vendas_dia"],
            "spend_dia_plano": METAS["investimento_dia"],
        },
        "projecao": {
            "vendas": round(n_vendas / dias_corridos * dias_totais),
            "receita": round(receita / dias_corridos * dias_totais, 2),
            "spend": round(tot_spend / dias_corridos * dias_totais, 2),
            "pct_meta": round(100 * (n_vendas / dias_corridos * dias_totais) / METAS["vendas"], 1),
        },
        "cac_max": METAS["cac_max"], "roas_meta": METAS["roas"],
        "ticket_plano": round(METAS["faturamento"] / METAS["vendas"], 2),
        "ticket_real": round(receita / n_vendas, 2) if n_vendas else 0,
    }

    dias = sorted({r["d"] for r in traf} | {v["d"] for v in vds})
    data = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "hoje": hoje.strftime("%Y-%m-%d"),
        "dias": [dias[0], dias[-1]] if dias else ["", ""],
        "dias_trafego": [min(r["d"] for r in traf), max(r["d"] for r in traf)] if traf else ["", ""],
        "bench_lpv_ic": BENCH_LPV_IC,
        "metas": metas, "ads": ads, "trafego": traf, "vendas": vds,
        "reembolsos": len(vendas) - len(vendas_ok),
    }

    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"trafego: {len(traf)} linhas | vendas: {len(vds)} | ads: {len(ads)}")
    print(f"investido R$ {tot_spend:.2f} | receita R$ {receita:.2f} | {n_vendas} vendas")
    print("index.html + data.json gerados")


if __name__ == "__main__":
    build()
