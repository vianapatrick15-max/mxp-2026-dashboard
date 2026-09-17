"""MXP 2026 — dashboard de tráfego x vendas reais. v2: o ano inteiro.

Quatro fontes, duas vivas e duas de base fixa:

  VIVAS (o CI le a cada 4h)
    TRAFEGO = planilha "MXP-Fp01 META ADS", aba dados_trafego (Meta, nivel ad/dia,
              so a janela do Fp01 ago-set)
    VENDAS  = planilha "[MXP-FP01][2026][BACKUP]", aba VENDAS (Hubla, webhook n8n)

  BASE DO ANO (snapshots commitados, gerados na mao)
    trafego_ano.json = `pull_trafego_ano.py`  — Meta API, todas as contas, o ano todo
    vendas_ano.json  = `import_vendas_hubla.py <export.xlsx>` — historico da Hubla

O motivo das duas bases: o CI nao tem token da Meta e a Hubla nao tem API de
listagem. Sem elas o dashboard so enxerga agosto em diante e perde os dois
Meteoricos (fev e abr), que sao 62% do investimento do ano.

Gera data.json + index.html auto-contido (SVG nativo, sem lib externa).
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

def get_gspread_client():
    """Autentica no Sheets. Local usa a lib da skill; no CI usa o segredo."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]

    raw = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if raw:
        return gspread.authorize(
            Credentials.from_service_account_info(json.loads(raw), scopes=scopes))

    path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH")
    if path and os.path.exists(path):
        return gspread.authorize(
            Credentials.from_service_account_file(path, scopes=scopes))

    sys.path.insert(0, os.path.expanduser("~/.claude/skills/google-sheets/scripts"))
    from lib.auth import get_gspread_client as _local
    return _local()

HERE = os.path.dirname(os.path.abspath(__file__))
TRAFEGO_ID = "12ldEcVBAyIWcX2APu3CVS82aeswbwxsbJZCYIGN4KKY"
TRAFEGO_TAB = "dados_trafego"
VENDAS_ID = "1JmhAHqs8kdDSuhWtZGw721GOIZec0MN9QjhLnuL3V1U"  # [MXP-FP01][2026][BACKUP], desde 18/08
VENDAS_TAB = "VENDAS"
SNAP_TRAFEGO = os.path.join(HERE, "trafego_ano.json")
SNAP_VENDAS = os.path.join(HERE, "vendas_ano.json")

# ---------------------------------------------------------------- ciclos
# O evento teve tres investidas de midia no ano. A venda entra no ciclo pelo dia
# do pagamento: nao da pra amarrar venda de fevereiro a criativo de agosto, e o
# closer fecha dias depois do anuncio. As bordas saem do proprio gasto — o Le02
# comecou em 29/03 e a reta final em 01/08 — e o build avisa se o dado nao bater.
CICLOS = [
    {"chave": "c1", "nome": "Ciclo 1 · Meteórico fev", "de": "2026-01-01", "ate": "2026-03-28",
     "obs": "Captação Mxp-Le01 e a primeira leva de ingressos."},
    {"chave": "c2", "nome": "Ciclo 2 · Meteórico abr", "de": "2026-03-29", "ate": "2026-07-31",
     "obs": "Captação Mxp-Le02, o 2º Meteórico e a rodada curta de venda em abril."},
    {"chave": "c3", "nome": "Ciclo 3 · Reta final", "de": "2026-08-01", "ate": "2026-12-31",
     "obs": "MXP-Fp01: venda direta de ingresso até o evento."},
]

# ---------------------------------------------------------------- metas
# Plano fechado com o cliente para a janela de venda direta (ago). A aba Metas
# mede so esse recorte — o ano inteiro vive na aba Ano.
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

# utm_source -> rotulo de frente. O que nao casar e parecer nome de gente entra
# como time de vendas; o resto vira "outros".
FRENTES = {
    "meta_ads": ("Meta Ads", "pago"),
    "facebook": ("Meta Ads", "pago"),
    "instagram": ("Meta Ads", "pago"),
    "whatsapp": ("WhatsApp", "proprio"),
    "activecampaign": ("E-mail", "proprio"),
    "tathinews": ("E-mail", "proprio"),
    "email": ("E-mail", "proprio"),
    "sms": ("SMS", "proprio"),
    "organico": ("Orgânico", "proprio"),
    "bio": ("Bio / Orgânico", "proprio"),
    "embaixador": ("Embaixador", "proprio"),
    "indicacao": ("Indicação", "proprio"),
    "redirect": ("Direto / redirect", "outros"),
}
# palavras que nao sao gente, pra nao virarem "closer Fulano"
NAO_PESSOA = {"site", "lp", "link", "checkout", "teste", "direto", "marketing",
              "hubla", "youtube", "tiktok", "google", "telegram", "manychat",
              "meta", "ads", "trafego", "pago", "anuncio"}

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

def chave_camp(s):
    """Nome de campanha comparavel entre Meta e utm_campaign da Hubla.

    O utm chega com espaco sobrando dentro do colchete ([ADV ] x [ADV]) e as
    vezes com caixa trocada — sem normalizar, a venda nao acha a campanha.
    """
    return re.sub(r"\s+", "", str(s or "")).lower()

def funil(camp):
    """Mxp-Le01 / Mxp-Le02 / MXP-Fp01 a partir do nome da campanha."""
    s = chave_camp(camp)
    for tok, nome in (("mxp-le01", "Mxp-Le01"), ("mxp-le02", "Mxp-Le02"),
                      ("mxp-fp01", "MXP-Fp01")):
        if tok in s:
            return nome
    return "Outros MXP"

def ciclo(d):
    for c in CICLOS:
        if c["de"] <= d <= c["ate"]:
            return c["chave"]
    return CICLOS[-1]["chave"] if d > CICLOS[-1]["ate"] else CICLOS[0]["chave"]

def limpa_src(s):
    """'%20Luana_Queiroz' / 'ThaysAlmeida' -> 'luana queiroz' / 'thays almeida'."""
    s = re.sub(r"%[0-9a-fA-F]{2}", " ", str(s or ""))
    s = re.sub(r"(?<=[a-zà-ú])(?=[A-ZÀ-Ú])", " ", s)   # quebra camelCase
    return re.sub(r"[_.\-]+", " ", s).strip().lower()

def parece_pessoa(s):
    p = [x for x in s.split() if x]
    return (1 <= len(p) <= 3 and all(re.fullmatch(r"[a-zà-úç']{2,}", x) for x in p)
            and not set(p) & NAO_PESSOA)

def frente(src):
    """Devolve (rotulo, tipo, vendedor). Tipo alimenta a cor e a regra de custo."""
    s = limpa_src(src)
    if not s:
        return ("Sem origem", "indefinido", "")
    # a chave do mapa tem "_" e o source chega de todo jeito (meta_ads, Meta Ads,
    # metaAds): compara com os dois lados sem separador nenhum.
    seco = s.replace(" ", "")
    for k, v in FRENTES.items():
        if k.replace("_", "") in seco:
            return (v[0], v[1], "")
    if parece_pessoa(s):
        return ("Time de vendas", "proprio", s.title())
    return (s, "outros", "")

# ---------------------------------------------------------------- coleta

def ler_snapshot(path, campo):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        print(f"AVISO: {os.path.basename(path)} ausente — o ano vai sair só com a "
              f"janela viva. Rode o script que gera esse arquivo.")
        return {campo: [], "ate": "", "gerado_em": ""}

def coletar():
    gc = get_gspread_client()

    tv = gc.open_by_key(TRAFEGO_ID).worksheet(TRAFEGO_TAB).get_values()
    th = {k: i for i, k in enumerate(tv[0])}
    planilha = []
    for r in tv[1:]:
        if not (r[th["Date"]] or "").strip():
            continue
        planilha.append({
            "data": r[th["Date"]].strip(),
            "campanha": r[th["Campaign Name"]].strip(),
            "ad": r[th["Ad Name"]].strip(),
            "ad_code": ad_code(r[th["Ad Name"]]),
            "conta": "",
            "spend": num(r[th["Spend (Cost, Amount Spent)"]]),
            "impr": num(r[th["Impressions"]]),
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
    vivas = []
    for r in sv[1:]:
        if not (r[sh["id_fatura"]] or "").strip():
            continue
        dt = parse_dt(r[sh["data_venda"]])
        vivas.append({
            "id": r[sh["id_fatura"]].strip(),
            "d": dt.strftime("%Y-%m-%d") if dt else "",
            "status": r[sh["status"]].strip().lower(),
            "oferta": r[sh["oferta"]].strip() or "(sem oferta)",
            "valor": num(r[sh["valor"]]),
            "utm_source": r[sh["utm_source"]].strip(),
            "utm_campaign": r[sh["utm_campaign"]].strip(),
            "utm_content": r[sh["utm_content"]].strip(),
        })

    return planilha, vivas

def montar_trafego(planilha, snap):
    """Junta snapshot do ano + planilha viva sem contar o mesmo dia duas vezes.

    A planilha manda onde ela existe (tem nivel anuncio, que os cards de criativo
    precisam). O snapshot entra so no que ela nao cobre: todo o historico, a conta
    que ficou fora da coleta e qualquer dia que a planilha ainda nao trouxe. Fora
    da janela viva o dado vira campanha/dia — criativo de fevereiro nao tem thumb
    nem venda por utm_content, so engordaria o arquivo.
    """
    coberto = {(r["data"], chave_camp(r["campanha"])) for r in planilha}

    linhas = []
    for r in planilha:
        # a planilha nao traz conta, e a mesma campanha rodou em C3 e C4 depois da
        # migracao de 27/08 — chutar a conta aqui inflaria uma e zeraria a outra.
        # Quem responde "quanto cada conta gastou" e o snapshot, na aba Ano.
        linhas.append({
            "d": r["data"], "c": r["campanha"], "a": r["ad_code"] or r["ad"], "cta": "",
            "s": round(r["spend"], 2), "i": int(r["impr"]), "k": int(r["clicks"]),
            "l": int(r["lpv"]), "ic": int(r["ic"]), "p": int(r["purch_pixel"]),
            "v": int(r["vv"]),
        })

    hist = {}
    for r in snap.get("linhas", []):
        if (r["d"], chave_camp(r["c"])) in coberto:
            continue
        k = (r["d"], r["c"], r.get("conta", "—"))
        o = hist.setdefault(k, {"d": r["d"], "c": r["c"], "a": "", "cta": r.get("conta", "—"),
                                "s": 0.0, "i": 0, "k": 0, "l": 0, "ic": 0, "p": 0, "v": 0})
        o["s"] += r["s"]; o["i"] += r["i"]; o["k"] += r["k"]
        o["l"] += r["lpv"]; o["ic"] += r["ic"]; o["p"] += r["p"]; o["v"] += r["v"]
    for o in hist.values():
        o["s"] = round(o["s"], 2)
        linhas.append(o)

    for o in linhas:
        o["fn"] = funil(o["c"])
        o["cic"] = ciclo(o["d"])
    linhas.sort(key=lambda x: (x["d"], x["c"]))
    return linhas

PERDIDAS = {"refunded", "canceled", "chargeback", "reembolsada", "cancelada"}

def montar_vendas(vivas, snap):
    """Base do ano + planilha viva, casadas por id_fatura.

    A planilha ganha de propósito: o export da Hubla so lista fatura paga, entao o
    reembolso de uma venda antiga so aparece do lado vivo. Venda que so existe na
    planilha (posterior ao export) entra normalmente.
    """
    por_id = {}
    for v in snap.get("vendas", []):
        por_id[v["id"]] = {
            "d": v["d"], "status": v.get("status", "paid"), "oferta": v["oferta"],
            "valor": v["valor"], "utm_source": v["utm_source"],
            "utm_campaign": v["utm_campaign"], "utm_content": v["utm_content"],
            "fonte": "export",
        }
    novas = 0
    for v in vivas:
        if v["id"] not in por_id:
            novas += 1
        por_id[v["id"]] = dict(v, fonte="planilha")

    out = []
    perdidas = 0
    for vid, v in por_id.items():
        if v["status"] in PERDIDAS:
            perdidas += 1
            continue
        if not v["d"]:
            continue
        nome_f, tipo_f, vendedor = frente(v["utm_source"])
        out.append({
            "d": v["d"], "f": nome_f, "t": tipo_f, "vd": vendedor,
            "v": round(v["valor"], 2), "o": v["oferta"],
            "a": ad_code(v["utm_content"]), "c": v["utm_campaign"],
            "src": v["utm_source"], "cic": ciclo(v["d"]),
        })
    out.sort(key=lambda x: x["d"])
    return out, perdidas, novas

# ---------------------------------------------------------------- agregação

MET = ("s", "i", "k", "l", "ic", "p", "v")

def zero():
    return {m: 0 for m in MET}

def soma(alvo, r):
    for m in MET:
        alvo[m] += r[m]

def bloco(spend, vendas_rows):
    receita = sum(v["v"] for v in vendas_rows)
    n = len(vendas_rows)
    return {
        "spend": round(spend, 2), "vendas": n, "receita": round(receita, 2),
        "cac": round(spend / n, 2) if n else None,
        "roas": round(receita / spend, 3) if spend else None,
        "ticket": round(receita / n, 2) if n else 0,
    }

def gasto_por_conta(snap, trafego):
    """Verba por conta de anuncio. Sai do snapshot, que e o unico lado que sabe
    em qual conta cada linha caiu; o que a planilha trouxer depois do snapshot
    entra num balde proprio em vez de ser chutado numa conta."""
    g = {}
    for r in snap.get("linhas", []):
        g[r.get("conta", "—")] = g.get(r.get("conta", "—"), 0.0) + r["s"]
    ate = snap.get("ate", "")
    depois = sum(r["s"] for r in trafego if ate and r["d"] > ate)
    if round(depois, 2) > 0:
        g["Depois do snapshot"] = depois
    return g


def contas_por_campanha(snap):
    """campanha -> 'C3 Mem + C4 Mem', na ordem de quanto cada uma gastou."""
    g = defaultdict(lambda: defaultdict(float))
    for r in snap.get("linhas", []):
        g[chave_camp(r["c"])][r.get("conta", "—")] += r["s"]
    return {k: " + ".join(c for c, _ in sorted(v.items(), key=lambda x: -x[1]) if _ > 0)
            for k, v in g.items()}


def resumo_ano(trafego, vendas, snap_t):
    """Tudo que a aba Ano mostra, ja mastigado — ela nao usa o filtro de período."""
    spend_total = sum(r["s"] for r in trafego)
    geral = bloco(spend_total, vendas)
    geral["dias_midia"] = len({r["d"] for r in trafego if r["s"] > 0})

    por_ciclo = []
    for c in CICLOS:
        tr = [r for r in trafego if r["cic"] == c["chave"]]
        vd = [v for v in vendas if v["cic"] == c["chave"]]
        if not tr and not vd:
            continue
        b = bloco(sum(r["s"] for r in tr), vd)
        dias = sorted({r["d"] for r in tr if r["s"] > 0})
        b.update({"chave": c["chave"], "nome": c["nome"], "obs": c["obs"],
                  "midia_de": dias[0] if dias else "", "midia_ate": dias[-1] if dias else "",
                  "pct_spend": round(100 * b["spend"] / spend_total, 1) if spend_total else 0,
                  "pct_receita": round(100 * b["receita"] / geral["receita"], 1) if geral["receita"] else 0,
                  "pago_vendas": sum(1 for v in vd if v["t"] == "pago")})
        por_ciclo.append(b)

    def por(chave, rows_t, rows_v=None, label=None):
        g = {}
        for r in rows_t:
            o = g.setdefault(r[chave], {"id": r[chave], "spend": 0.0, "vendas": 0, "receita": 0.0})
            o["spend"] += r["s"]
        if rows_v:
            for v, k in rows_v:
                o = g.setdefault(k, {"id": k, "spend": 0.0, "vendas": 0, "receita": 0.0})
                o["vendas"] += 1
                o["receita"] += v["v"]
        saida = []
        for o in g.values():
            saida.append({
                "id": o["id"], "spend": round(o["spend"], 2), "vendas": o["vendas"],
                "receita": round(o["receita"], 2),
                "pct_spend": round(100 * o["spend"] / spend_total, 1) if spend_total else 0,
                "cac": round(o["spend"] / o["vendas"], 2) if o["vendas"] else None,
                "roas": round(o["receita"] / o["spend"], 3) if o["spend"] else None,
            })
        saida.sort(key=lambda x: -x["spend"])
        return saida

    por_funil = por("fn", trafego)

    contas = gasto_por_conta(snap_t, trafego)
    por_conta = sorted(
        [{"id": k, "spend": round(v, 2), "vendas": 0, "receita": 0.0, "cac": None, "roas": None,
          "pct_spend": round(100 * v / spend_total, 1) if spend_total else 0}
         for k, v in contas.items() if round(v, 2) > 0],
        key=lambda x: -x["spend"])

    # campanha: a venda encosta pelo utm_campaign normalizado
    camps = {chave_camp(r["c"]): r["c"] for r in trafego}
    pares = [(v, camps[chave_camp(v["c"])]) for v in vendas if chave_camp(v["c"]) in camps]
    por_campanha = por("c", trafego, pares)
    dono = contas_por_campanha(snap_t)
    for o in por_campanha:
        o["funil"] = funil(o["id"])
        o["conta"] = dono.get(chave_camp(o["id"]), "—")

    mes = {}
    for r in trafego:
        o = mes.setdefault(r["d"][:7], {"mes": r["d"][:7], "spend": 0.0, "vendas": 0, "receita": 0.0})
        o["spend"] += r["s"]
    for v in vendas:
        o = mes.setdefault(v["d"][:7], {"mes": v["d"][:7], "spend": 0.0, "vendas": 0, "receita": 0.0})
        o["vendas"] += 1
        o["receita"] += v["v"]
    por_mes = sorted(mes.values(), key=lambda x: x["mes"])
    acc_s = acc_r = 0.0
    for o in por_mes:
        acc_s += o["spend"]; acc_r += o["receita"]
        o["spend"] = round(o["spend"], 2); o["receita"] = round(o["receita"], 2)
        o["acc_spend"] = round(acc_s, 2); o["acc_receita"] = round(acc_r, 2)
        o["cac"] = round(o["spend"] / o["vendas"], 2) if o["vendas"] else None
        o["roas"] = round(o["receita"] / o["spend"], 3) if o["spend"] else None

    fr = {}
    for v in vendas:
        o = fr.setdefault(v["f"], {"frente": v["f"], "tipo": v["t"], "vendas": 0, "receita": 0.0})
        o["vendas"] += 1
        o["receita"] += v["v"]
    por_frente = sorted(fr.values(), key=lambda x: -x["receita"])
    for o in por_frente:
        o["receita"] = round(o["receita"], 2)
        o["ticket"] = round(o["receita"] / o["vendas"], 2)
        o["pct"] = round(100 * o["receita"] / geral["receita"], 1) if geral["receita"] else 0

    of = {}
    for v in vendas:
        o = of.setdefault(v["o"], {"oferta": v["o"], "vendas": 0, "receita": 0.0})
        o["vendas"] += 1
        o["receita"] += v["v"]
    por_oferta = sorted(of.values(), key=lambda x: -x["receita"])
    for o in por_oferta:
        o["receita"] = round(o["receita"], 2)
        o["ticket"] = round(o["receita"] / o["vendas"], 2)
        o["pct"] = round(100 * o["receita"] / geral["receita"], 1) if geral["receita"] else 0

    vend = {}
    for v in vendas:
        if not v["vd"]:
            continue
        o = vend.setdefault(v["vd"], {"nome": v["vd"], "vendas": 0, "receita": 0.0})
        o["vendas"] += 1
        o["receita"] += v["v"]
    vendedores = sorted(vend.values(), key=lambda x: -x["receita"])
    for o in vendedores:
        o["receita"] = round(o["receita"], 2)
        o["ticket"] = round(o["receita"] / o["vendas"], 2)

    pago = [v for v in vendas if v["t"] == "pago"]
    return {
        "geral": geral,
        "receita_pago": round(sum(v["v"] for v in pago), 2),
        "vendas_pago": len(pago),
        "por_ciclo": por_ciclo, "por_conta": por_conta, "por_funil": por_funil,
        "por_campanha": por_campanha, "por_mes": por_mes, "por_frente": por_frente,
        "por_oferta": por_oferta, "vendedores": vendedores,
    }

# ---------------------------------------------------------------- build

def build():
    planilha, vivas = coletar()
    snap_t = ler_snapshot(SNAP_TRAFEGO, "linhas")
    snap_v = ler_snapshot(SNAP_VENDAS, "vendas")

    traf = montar_trafego(planilha, snap_t)
    vds, reembolsos, novas = montar_vendas(vivas, snap_v)

    ads = {}
    for r in planilha:
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

    try:
        with open(os.path.join(HERE, "thumbs.json"), encoding="utf-8") as fh:
            thumbs = json.load(fh)
    except (OSError, ValueError):
        thumbs = {}
    sem_thumb = 0
    for k, a in ads.items():
        url = (thumbs.get(k) or {}).get("thumb")
        a["thumb"] = url or ""
        if not url:
            sem_thumb += 1

    ano = resumo_ano(traf, vds, snap_t)

    # janela viva = o que a planilha de trafego cobre. E o período que abre nas
    # abas de operação; o ano inteiro fica na aba Ano.
    dias_planilha = sorted({r["data"] for r in planilha})
    janela = {"de": dias_planilha[0] if dias_planilha else "",
              "ate": dias_planilha[-1] if dias_planilha else ""}

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ini = datetime.strptime(METAS["inicio"], "%Y-%m-%d")
    fim = datetime.strptime(METAS["deadline"], "%Y-%m-%d")
    dias_totais = (fim - ini).days + 1
    dias_corridos = max(1, min((hoje - ini).days + 1, dias_totais))
    dias_restantes = max(1, (fim - hoje).days + 1)
    fracao = dias_corridos / dias_totais

    # a aba Metas mede so a janela do plano, nunca o ano
    ini_iso = METAS["inicio"]
    spend_plano = sum(r["s"] for r in traf if r["d"] >= ini_iso)
    vendas_plano = [v for v in vds if v["d"] >= ini_iso]
    receita_plano = sum(v["v"] for v in vendas_plano)
    n_plano = len(vendas_plano)

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

    cac = spend_plano / n_plano if n_plano else 0
    roas = receita_plano / spend_plano if spend_plano else 0
    metas = {
        "deadline": fim.strftime("%d/%m/%Y"), "inicio": ini.strftime("%d/%m/%Y"),
        "dias_totais": dias_totais, "dias_corridos": dias_corridos,
        "dias_restantes": dias_restantes,
        "linhas": [
            linha("vendas", "Vendas", METAS["vendas"], n_plano, "up", "int",
                  "Toda venda registrada na Hubla, de qualquer frente."),
            linha("faturamento", "Faturamento", METAS["faturamento"], receita_plano, "up", "brl",
                  "Receita bruta das vendas válidas."),
            linha("investimento", "Investimento", METAS["investimento"], spend_plano, "up", "brl",
                  "Verba prevista para o Meta no período."),
            linha("cac", "CAC", METAS["cac_max"], cac, "down", "brl",
                  "Investimento dividido por todas as vendas (blended, como no plano).",
                  acumula=False),
            linha("roas", "ROAS", METAS["roas"], roas, "up", "x",
                  "Faturamento dividido pelo investimento.", acumula=False),
        ],
        "ritmo": {
            "vendas_dia": round(n_plano / dias_corridos, 2),
            "spend_dia": round(spend_plano / dias_corridos, 2),
            "vendas_dia_plano": METAS["vendas_dia"],
            "spend_dia_plano": METAS["investimento_dia"],
        },
        "projecao": {
            "vendas": round(n_plano / dias_corridos * dias_totais),
            "receita": round(receita_plano / dias_corridos * dias_totais, 2),
            "spend": round(spend_plano / dias_corridos * dias_totais, 2),
            "pct_meta": round(100 * (n_plano / dias_corridos * dias_totais) / METAS["vendas"], 1),
        },
        "cac_max": METAS["cac_max"], "roas_meta": METAS["roas"],
        "ticket_plano": round(METAS["faturamento"] / METAS["vendas"], 2),
        "ticket_real": round(receita_plano / n_plano, 2) if n_plano else 0,
    }

    dias = sorted({r["d"] for r in traf} | {v["d"] for v in vds})
    data = {
        "versao": "2.0",
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "hoje": hoje.strftime("%Y-%m-%d"),
        "dias": [dias[0], dias[-1]] if dias else ["", ""],
        "janela": janela,
        "ciclos": CICLOS,
        "bench_lpv_ic": BENCH_LPV_IC,
        "fontes": {
            "trafego_snapshot": snap_t.get("gerado_em", ""),
            "trafego_ate": snap_t.get("ate", ""),
            "vendas_snapshot": snap_v.get("gerado_em", ""),
            "vendas_origem": snap_v.get("origem", ""),
        },
        "ano": ano, "metas": metas, "ads": ads, "trafego": traf, "vendas": vds,
        "reembolsos": reembolsos,
    }

    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)

    g = ano["geral"]
    print(f"trafego: {len(traf)} linhas ({len(planilha)} da planilha) | vendas: {len(vds)}"
          f" ({novas} só na planilha, {reembolsos} perdidas) | ads: {len(ads)}"
          f" ({len(ads) - sem_thumb} com thumb)")
    print(f"ANO: investido R$ {g['spend']:,.2f} | receita R$ {g['receita']:,.2f}"
          f" | {g['vendas']} vendas | CAC R$ {g['cac'] or 0:,.2f} | ROAS {g['roas'] or 0:.2f}x")
    for c in ano["por_ciclo"]:
        print(f"  {c['nome']:<28} R$ {c['spend']:>11,.2f}  {c['vendas']:>4} vendas"
              f"  R$ {c['receita']:>11,.2f}")
    print("index.html + data.json gerados")

if __name__ == "__main__":
    build()
