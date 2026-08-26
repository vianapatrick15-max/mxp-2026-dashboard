# MXP-Fp01 2026 — Tráfego x vendas reais

Dashboard que cruza a mídia paga (Meta) com a venda real da Hubla, separada por frente (`utm_source`).

- `index.html` — dashboard pronto (dados embutidos, abre com duplo clique)
- `data.json` — dataset agregado (sem PII)
- `build.py` — lê as duas planilhas e gera `data.json` + `index.html`
- `template.html` — layout/JS; `build.py` injeta os dados no lugar de `/*__DATA__*/`
- `thumbs.json` — imagem de cada criativo (enriquecimento manual, `pull_thumbs.py`)

## Fontes

| O quê | Planilha | Aba |
|---|---|---|
| Tráfego (Meta, nível anúncio/dia) | `12ldEcVBAyIWcX2APu3CVS82aeswbwxsbJZCYIGN4KKY` | `dados_trafego` |
| Vendas (Hubla) | `1JmhAHqs8kdDSuhWtZGw721GOIZec0MN9QjhLnuL3V1U` | `VENDAS` |

Em 18/08/2026 a planilha de vendas mudou: a antiga (`13uDvw...`) parou de aceitar escrita do n8n
e foi substituída pela `[MXP-FP01][2026][BACKUP]`, com todo o histórico copiado. A conta que o n8n
usa é `tathi@palestrantememoravel.com.br` — ela precisa ser Editora da planilha, senão volta o 403.

A aba VENDAS é alimentada em tempo real pelo workflow n8n `[MXP-FP01] VENDAS HUBLA 2026`
(webhook `/webhook/mxp-2026-vendas`) e pelo backfill `_scripts/hubla_backfill_mxp.py`.

## Regras de leitura

- **Venda = Hubla, nunca pixel.** O card de alerta compara os dois de propósito: divergência é esperada (janela de atribuição e view-through do Meta).
- **Frente paga = `utm_source` contendo meta/facebook/instagram.** Só ela recebe CPA e ROAS, porque só ela tem investimento amarrado. As demais (WhatsApp, e-mail, closers) entram na receita mas ficam com `—` nas colunas de custo.
- **Vendas estornadas** (`refunded`/`canceled`/`chargeback`) saem de toda a leitura.
- **Venda por criativo** cruza `utm_content` da Hubla com o Ad Name do Meta pelo código `AD-nn`.
- ROAS geral do topo é leitura de **caixa**, não de eficiência de mídia, sempre que a janela de vendas começar antes da janela de tráfego.

## Metas (revisar 15/08)

Fechadas com o cliente e travadas no topo do `build.py` (dict `METAS`):
150 vendas, R$ 29.550 de faturamento, R$ 22.500 de investimento, CAC teto R$ 150,
ROAS 1,3x, prazo 15/08. A aba "Metas e ritmo" calcula sozinha o esperado a esta
altura, o que falta e o necessário por dia. Para revisar, editar só esse dict.

CAC e ROAS entram como alvo fixo (`acumula=False`): comparam direto com o alvo,
sem rateio por dia. Vendas, faturamento e investimento acumulam e por isso têm
"esperado a esta altura" e "necessário por dia".

## Filtro de período

Todo o cálculo da aba Desempenho é feito no navegador a partir dos dados crus
(`DATA.trafego` = uma linha por anúncio/dia, `DATA.vendas` = uma linha por venda).
Por isso qualquer intervalo funciona: atalhos (Tudo, Hoje, Ontem, 7 dias, 14 dias,
Este mês) ou as duas datas livres. A aba Metas ignora o filtro de propósito — ela
mede o plano inteiro.

## Tabelas

Todo cabeçalho ordena: primeiro clique desce, segundo sobe. A ordem padrão é por
investimento (campanhas e criativos) ou por receita (frentes e ofertas).

## Aba Ads

Um card por anúncio: imagem do criativo, status, investimento, vendas, receita,
CPA, ROAS, custo por visita, e a linha de volume (impressões, CTR, visitas,
checkouts, conversão da página, hook nos vídeos). Ordenável por qualquer uma
dessas colunas e filtrável por tipo (estático/vídeo) e status. Respeita o filtro
de período do topo, que agora é global e vale para Desempenho e Ads (a aba Metas
mede o plano inteiro e por isso esconde o filtro).

A venda do card é a mesma regra do resto do dashboard: Hubla cruzada pelo
`utm_content`, nunca o pixel. Verde/vermelho compara CPA com o teto de CAC, ROAS
com a meta e conversão da página com o `BENCH_LPV_IC`.

**Hook rate** = visualizações de vídeo ÷ impressões, só em anúncio `[VID]` e a
partir de 30 visualizações. Estático registra um punhado de video_view em Reels e
sairia com 0,2%, que é ruído de posicionamento, não leitura. A planilha traz
`Action Video View` mas não os quartis, então não há hold rate nem curva de
retenção aqui (o DP100K tem porque puxa vídeo direto da API).

### Imagem dos criativos (`pull_thumbs.py`)

```bash
/usr/bin/python3 pull_thumbs.py    # o SDK da Meta só está nesse Python
```

Roda **local**, fora do CI, e grava `thumbs.json` (`ad_code → {thumb, nome}`).
O refresh de 4 em 4 horas só relê o arquivo já commitado, então: **anúncio novo
na conta só ganha imagem depois de rodar isso e commitar.** Sem o arquivo o
dashboard não quebra, o card cai no link do Instagram.

Lê a **C3 [MEMORÁVEL GLOBAL]** (`act_422653132521856`), filtrando anúncio com
"MXP" no nome porque FA-Fp01 mora na mesma conta.

> O caminho é `image_hash → /adimages → permalink_url`, e não o `image_url` do
> criativo, porque esse campo volta com `stp=..._p64x64_...` na maioria dos
> anúncios: uma miniatura de 64px que num card de 288px vira borrão. O hash pode
> estar em quatro lugares — campo do criativo, `link_data`, `video_data` e
> `asset_feed_spec` (Advantage+ com asset por posicionamento, que é o caso de ~40
> anúncios aqui). O `permalink_url` ainda tem a vantagem de não ser URL assinada,
> então não expira como as `scontent`.

## Chave do criativo

`AD-11` sozinho NÃO identifica o anúncio: o mesmo código existe na campanha de
estáticos e na de vídeos. A chave é `AD-11|VID`, montada a partir dos tokens do
nome do anúncio e casada com os mesmos tokens do `utm_content` da Hubla. Sem isso
os dois viram uma linha só e o custo por visita fica errado.

O botão "prévia" abre o post do Instagram do anúncio (`Instagram Permalink URL`
da planilha de tráfego). Anúncio sem permalink na planilha aparece como
"sem prévia". A imagem do card da aba Ads não vem daí — vem do `thumbs.json`.

## Sinalização

Verde/vermelho aparece só onde muda decisão: KPIs de ROAS e CAC contra a meta,
linhas de meta contra o ritmo (vermelho abaixo de 80% do esperado), a queda
página → checkout contra o benchmark de 3% (`BENCH_LPV_IC`) e o custo por visita
por criativo quando sai muito da mediana. O resto fica neutro de propósito.

## Publicar

```bash
./deploy.sh    # rebuild + Cloudflare Pages
```

No ar em https://mxp-2026-dashboard.pages.dev/

O GitHub Pages deste repo ficou travado num deployment fantasma do lado do
GitHub ("Deployment cancelled" / "due to in progress deployment"), por isso o
Cloudflare virou o canal principal.

## Atualizar sem publicar

```bash
cd ~/Documents/CLAUDE_CODE_2026/dashboards/MXP-2026-Dash && python3 build.py
```
