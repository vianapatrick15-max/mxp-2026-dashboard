"""Enriquecimento (rodar local/manual) — snapshot do ano inteiro do MXP na Meta API.

O CI so le planilha (nao tem token da Meta), e a planilha `dados_trafego` so cobre
a janela viva do Fp01 (a partir de 04/08). Todo o historico do ano — Mxp-Le01 (fev),
Mxp-Le02 (mar-abr) e a primeira rodada do Fp01 (abr) — vive so na API. Este script
varre as contas das duas BMs, filtra campanha com "mxp" no nome e grava
`trafego_ano.json` (nivel anuncio/dia), que o build.py usa como base do ano.

Uso:  /usr/bin/python3 pull_trafego_ano.py [--desde 2026-01-01] [--ate AAAA-MM-DD]
Requer: token em ~/.claude/skills/meta-ads-memoravel/.env (ou meta-ads-instituto-id).

Regra de merge no build.py: o snapshot manda ate `ate`; depois disso vale a
planilha. Rodar de novo sempre que quiser reconsolidar o ano.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "trafego_ano.json")
API = "https://graph.facebook.com/v21.0"

# as duas familias de conta da Tathi. MXP so aparece em 5 delas, mas varrer todas
# e barato e evita descobrir tarde que uma campanha nova nasceu noutro lugar.
CONTAS = [
    ("C1 Mem", "act_1835702343244302"),
    ("C2 Mem", "act_1307282709635504"),
    ("C3 Mem", "act_422653132521856"),
    ("C4 Mem", "act_1631219441753243"),
    ("C1 Inst", "act_1725623984282551"),
    ("C2 Inst", "act_306533480853015"),
    ("C3 Inst", "act_506518827383127"),
    ("C4 Inst", "act_629440996401732"),
    ("C5 Inst", "act_529640016271311"),
]

ACOES = {
    "landing_page_view": "lpv",
    "omni_initiated_checkout": "ic",
    "omni_purchase": "p",
    "video_view": "v",
}


def tokens():
    """Os dois tokens da casa. Nenhum sozinho enxerga as 9 contas."""
    out = []
    for skill in ("meta-ads-memoravel", "meta-ads-instituto-id"):
        p = os.path.expanduser("~/.claude/skills/%s/.env" % skill)
        if not os.path.exists(p):
            continue
        for line in open(p):
            if line.startswith("META_ADS_TOKEN="):
                t = line.split("=", 1)[1].strip().strip('"').strip("'")
                if t and t not in out:
                    out.append(t)
    if not out:
        sys.exit("nenhum META_ADS_TOKEN encontrado nas skills meta-ads-*")
    return out


def get(url, tentativas=4):
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:300]
            # limite de chamada: espera e tenta de novo. Erro de permissao nao adianta.
            if e.code in (429, 500, 503) or "reduce the amount of data" in corpo:
                time.sleep(20 * (i + 1))
                continue
            raise RuntimeError("%s %s" % (e.code, corpo))
        except Exception:
            if i == tentativas - 1:
                raise
            time.sleep(10 * (i + 1))
    raise RuntimeError("falhou apos %d tentativas" % tentativas)


def meses(desde, ate):
    """Quebra o intervalo em pedacos mensais.

    Ano inteiro no nivel anuncio/dia de uma vez a Meta engasga (a chamada fica
    pendurada ate estourar o timeout). Mes a mes cada resposta e pequena e o
    retry de uma falha custa um mes, nao o ano.
    """
    ini, fim = date.fromisoformat(desde), date.fromisoformat(ate)
    while ini <= fim:
        if ini.month == 12:
            prox = date(ini.year + 1, 1, 1)
        else:
            prox = date(ini.year, ini.month + 1, 1)
        yield ini.isoformat(), min(prox - timedelta(days=1), fim).isoformat()
        ini = prox


def insights(act, token, desde, ate):
    params = {
        "level": "ad",
        "time_range": json.dumps({"since": desde, "until": ate}),
        "time_increment": "1",
        "fields": "campaign_name,adset_name,ad_name,ad_id,spend,impressions,reach,"
                  "inline_link_clicks,actions",
        "filtering": json.dumps([{"field": "campaign.name", "operator": "CONTAIN", "value": "mxp"}]),
        "limit": "500",
        "access_token": token,
    }
    url = "%s/%s/insights?%s" % (API, act, urllib.parse.urlencode(params))
    rows, data = [], get(url)
    rows += data.get("data", [])
    while data.get("paging", {}).get("next"):
        data = get(data["paging"]["next"])
        rows += data.get("data", [])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2026-01-01")
    ap.add_argument("--ate", default=date.today().isoformat())
    args = ap.parse_args()

    toks = tokens()
    linhas, por_conta = [], {}
    for label, act in CONTAS:
        rows, erro, tok = [], None, None
        for de, ate in meses(args.desde, args.ate):
            parte = None
            for t in ([tok] if tok else toks):
                try:
                    parte = insights(act, t, de, ate)
                    tok = t
                    break
                except Exception as e:  # conta que o token nao enxerga
                    erro = str(e)[:120]
            if parte is None:
                break
            rows += parte
            print("    %-8s %s  %s" % (label, de[:7], len(parte)), flush=True)
        if tok is None:
            print("  %-8s %s  SEM ACESSO (%s)" % (label, act, erro))
            continue
        gasto = 0.0
        for r in rows:
            a = {x["action_type"]: float(x["value"]) for x in r.get("actions", [])}
            s = float(r.get("spend", 0))
            gasto += s
            linhas.append({
                "d": r["date_start"],
                "conta": label,
                "c": r.get("campaign_name", ""),
                "adset": r.get("adset_name", ""),
                "ad": r.get("ad_name", ""),
                "s": round(s, 2),
                "i": int(float(r.get("impressions", 0))),
                "r": int(float(r.get("reach", 0))),
                "k": int(float(r.get("inline_link_clicks", 0))),
                "lpv": int(a.get("landing_page_view", 0)),
                "ic": int(a.get("omni_initiated_checkout", 0)),
                "p": int(a.get("omni_purchase", 0)),
                "v": int(a.get("video_view", 0)),
            })
        if rows:
            por_conta[label] = round(gasto, 2)
        print("  %-8s %s  %5d linhas  R$ %s" % (label, act, len(rows), format(gasto, ",.2f")))

    out = {
        "gerado_em": time.strftime("%d/%m/%Y %H:%M"),
        "desde": args.desde,
        "ate": args.ate,
        "por_conta": por_conta,
        "linhas": linhas,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    total = sum(por_conta.values())
    print("\n%d linhas | R$ %s no ano | %s" % (len(linhas), format(total, ",.2f"), OUT))


if __name__ == "__main__":
    main()
