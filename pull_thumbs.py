"""Enriquecimento (rodar local/manual) — puxa a imagem dos criativos MXP-Fp01 na
Meta API e grava thumbs.json {ad_code: {thumb, nome}}.

O build.py mescla isso no dict `ads`, que alimenta os cards da aba Ads.

Uso:  /usr/bin/python3 pull_thumbs.py
Requer: facebook_business + python-dotenv + token em ~/.claude/skills/meta-ads-memoravel/.env
Nao roda no CI — o refresh so rele o thumbs.json ja commitado.

Por que passa por image_hash e nao usa o `image_url` do criativo direto: o campo
volta com `stp=..._p64x64_...` na maioria dos anuncios, ou seja, uma miniatura de
64px que no card de 288px vira borrao. O caminho certo e pegar o hash da imagem
(no criativo, no link_data ou no video_data) e resolver em /adimages, que devolve
`permalink_url` — imagem cheia e, de quebra, URL sem assinatura que expira
(as scontent morrem em semanas com "URL signature expired").
"""
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.claude/skills/meta-ads-memoravel/.env"))
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build import ad_code  # mesma chave AD-nn|FMT usada no dashboard

# MXP-Fp01 roda na C3 [MEMORAVEL GLOBAL]. FA-Fp01 mora na mesma conta, por isso
# o filtro por nome (o token tambem enxerga contas que nao interessam aqui).
CONTA = "act_422653132521856"
FILTER = [{"field": "name", "operator": "CONTAIN", "value": "MXP"}]
FIELDS = ["name", "creative{image_hash,image_url,thumbnail_url,object_story_spec,asset_feed_spec}"]
LOTE = 40  # /adimages aceita a lista de hashes de uma vez; 40 mantem a URL curta

FacebookAdsApi.init(app_id=os.getenv("META_APP_ID"),
                    access_token=os.getenv("META_ADS_TOKEN"),
                    api_version="v21.0")


def _dict(v):
    return v if (v is None or isinstance(v, dict)) else v.export_all_data()


def extrai(cr):
    """Devolve (hash, url_fallback) do criativo. A imagem pode estar em quatro
    lugares, e o anuncio Advantage+ so tem o quarto: campo do criativo,
    link_data (estatico classico), video_data (video) e asset_feed_spec
    (criativo com asset por posicionamento)."""
    h = cr.get("image_hash")
    url = ""
    oss = _dict(cr.get("object_story_spec")) or {}
    for bloco in ("link_data", "video_data"):
        d = _dict(oss.get(bloco)) or {}
        h = h or d.get("image_hash")
        url = url or d.get("image_url") or d.get("picture") or ""
    afs = _dict(cr.get("asset_feed_spec")) or {}
    if not h:
        imgs = [_dict(i) or {} for i in (afs.get("images") or [])]
        imgs += [_dict(v) or {} for v in (afs.get("videos") or [])]
        # prefere o asset de FEED: o de story e 9:16 e no card 1:1 vira uma faixa
        rot = lambda i: [_dict(l) or {} for l in (i.get("adlabels") or [])]
        feed = [i for i in imgs
                if any("feed" in (l.get("name") or "") for l in rot(i))]
        for i in (feed or imgs):
            h = i.get("hash") or i.get("image_hash")
            if h:
                break
    return h, (url or cr.get("image_url") or cr.get("thumbnail_url") or "")


acc = AdAccount(CONTA)
por_ad, hashes = {}, set()
vistos = 0
for ad in acc.get_ads(fields=FIELDS, params={"limit": 100, "filtering": FILTER}):
    vistos += 1
    k = ad_code(ad.get("name") or "")
    if not k:
        continue
    h, url = extrai(ad.get("creative") or {})
    ja = por_ad.get(k)
    # o mesmo AD aparece em varios conjuntos; fica o primeiro que trouxer hash
    if ja and ja[1]:
        continue
    por_ad[k] = ((ad.get("name") or "").strip(), h, url)
    if h:
        hashes.add(h)
print(f"{vistos} anuncios MXP na conta -> {len(por_ad)} codigos, {len(hashes)} hashes",
      file=sys.stderr)

full = {}
lista = sorted(hashes)
for i in range(0, len(lista), LOTE):
    for img in acc.get_ad_images(fields=["hash", "permalink_url", "url"],
                                 params={"hashes": lista[i:i + LOTE]}):
        u = img.get("permalink_url") or img.get("url")
        if u:
            full[img["hash"]] = u
print(f"/adimages resolveu {len(full)}/{len(hashes)} hashes", file=sys.stderr)

thumbs, sem = {}, []
for k, (nome, h, url) in sorted(por_ad.items()):
    u = full.get(h) or url
    if not u:
        sem.append(k)
        continue
    thumbs[k] = {"thumb": u, "nome": nome}

with open(os.path.join(HERE, "thumbs.json"), "w", encoding="utf-8") as fh:
    json.dump(thumbs, fh, ensure_ascii=False, indent=0)
print(f"thumbs.json: {len(thumbs)} com imagem"
      + (f" | sem imagem: {', '.join(sem)}" if sem else ""))
