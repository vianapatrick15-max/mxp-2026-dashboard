# MXP 2026 — Tráfego x vendas reais (v2)

Dashboard que cruza a mídia paga (Meta) com a venda real da Hubla, separada por frente (`utm_source`).

**v2 (17/09/2026): o dashboard passou a cobrir o ano inteiro do evento**, não só a
janela de venda direta de agosto. A aba **Ano 2026** abre primeiro e mostra o
acumulado — investimento somando as cinco contas de anúncio que rodaram MXP, receita
de todas as vendas do produto na Hubla desde fevereiro, e o corte por ciclo de mídia.
As abas de operação (Desempenho, Ads, Metas) continuam abrindo na janela viva.

- `index.html` — dashboard pronto (dados embutidos, abre com duplo clique)
- `data.json` — dataset agregado (sem PII)
- `build.py` — junta as quatro fontes e gera `data.json` + `index.html`
- `template.html` — layout/JS; `build.py` injeta os dados no lugar de `/*__DATA__*/`
- `thumbs.json` — imagem de cada criativo (enriquecimento manual, `pull_thumbs.py`)
- `trafego_ano.json` — snapshot do ano na Meta API (`pull_trafego_ano.py`)
- `vendas_ano.json` — histórico de vendas do export da Hubla (`import_vendas_hubla.py`)

## Fontes

Duas vivas (o CI relê a cada 4h) e duas de base fixa (snapshot commitado, gerado na mão):

| O quê | Origem | Cobertura |
|---|---|---|
| Tráfego nível anúncio/dia | planilha `12ldEcVBAyIWcX2APu3CVS82aeswbwxsbJZCYIGN4KKY`, aba `dados_trafego` | 04/08 em diante |
| Vendas novas | planilha `1JmhAHqs8kdDSuhWtZGw721GOIZec0MN9QjhLnuL3V1U`, aba `VENDAS` | 01/08 em diante |
| Tráfego do ano | `trafego_ano.json` (Meta API, 9 contas das duas BMs) | o ano todo |
| Vendas do ano | `vendas_ano.json` (export XLSX do painel Hubla) | o ano todo |

O motivo das duas bases fixas: **o CI não tem token da Meta** (só segredo do Sheets e
do Cloudflare) e **a Hubla não tem API de listagem** — só webhook, que começou em
06/08. Sem os snapshots o dashboard enxergaria apenas agosto em diante e perderia os
dois Meteóricos (fev e abr), que são 62% do investimento do ano.

### Como atualizar os snapshots

```bash
/usr/bin/python3 pull_trafego_ano.py                      # relê o ano todo na Meta API
/usr/bin/python3 import_vendas_hubla.py ~/Downloads/<export>.xlsx
/usr/bin/python3 build.py && git add -A && git commit && git push
```

`pull_trafego_ano.py` varre as 9 contas das duas BMs filtrando campanha com "mxp" no
nome, mês a mês (o ano inteiro de uma vez a Meta derruba com "Service temporarily
unavailable"). `import_vendas_hubla.py` ignora o produto "Palestras MXP 2025", que é
outro evento e aparece no mesmo export.

### Regra de merge

Onde a planilha viva tem dado, ela manda — é ela que traz o nível de anúncio que os
cards de criativo precisam. O snapshot entra só no que ela não cobre (todo o
histórico, a conta que ficou fora da coleta, qualquer dia que ainda não chegou), e aí
vira campanha/dia: criativo de fevereiro não tem thumb nem venda por `utm_content`, só
engordaria o arquivo. Nas vendas, a planilha ganha por `id_fatura` — o export só lista
fatura paga, então **reembolso de venda antiga só existe do lado vivo**.

**A conta de anúncio nunca é inferida da planilha.** Depois da migração de 27/08 a
mesma campanha rodou na C3 e na C4 Mem; chutar a conta infla uma e zera a outra. Quem
responde "quanto cada conta gastou" é o snapshot.

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

## Aba Ano 2026

Ignora o filtro de período: a pergunta dela é sempre "quanto o evento custou e
devolveu no ano". Traz KPIs do acumulado, os três ciclos de mídia, mês a mês com
curva acumulada, verba por conta e por funil, campanhas do ano, origem da receita,
time de vendas e mix de ofertas.

**Ciclo é janela de data, não clique.** O evento teve três investidas de mídia
(Mxp-Le01 em fev, Mxp-Le02 em mar-abr, MXP-Fp01 de ago até o evento) e a venda entra
no ciclo pelo dia do pagamento — não dá para amarrar venda de fevereiro a criativo de
agosto, e o closer fecha dias depois do anúncio. As bordas estão no dict `CICLOS` do
`build.py`.

**A leitura do evento é blended.** Só ~18% das vendas chegam com `utm` de mídia: o
grosso entra por WhatsApp e pelo time de vendas, que fecha o lead que a mídia trouxe.
Por isso o CAC e o ROAS do topo dividem tudo por tudo, e o ROAS da frente paga
isolada não responde pelo evento. Campanha de captação aparece sem venda de propósito.

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
Por isso qualquer intervalo funciona: atalhos (Janela atual, Ano todo, Hoje, Ontem,
7 dias, 14 dias, Este mês, um por ciclo) ou as duas datas livres. O padrão é a
**janela atual** — a parte com nível de anúncio —, porque misturar fevereiro no dia a
dia só atrapalha. As abas Metas e Ano ignoram o filtro de propósito: uma mede o plano
inteiro, a outra o ano fechado.

Fora da janela viva o tráfego é campanha/dia, sem nível de anúncio: a tabela de
criativos e a aba Ads ficam vazias nesses períodos, e o total continua certo.

## Tabelas

Todo cabeçalho ordena: primeiro clique desce, segundo sobe. A ordem padrão é por
investimento (campanhas e criativos) ou por receita (frentes e ofertas).

## Recorte (filtro cruzado)

Clicar numa linha de **campanha**, **criativo**, **dia**, **frente** ou **oferta** —
ou numa barra dos gráficos, ou num card da aba Ads — recorta o dashboard inteiro
por aquele item: KPIs, funil, evolução diária, todas as tabelas e a aba Ads. Os
recortes ativos viram chips abaixo do filtro de período, saem clicando no `×` ou
no mesmo item de novo, e se somam entre si (dia + campanha, por exemplo). O
recorte é uma camada **por cima** do período, nunca no lugar dele; a aba Metas
ignora os dois.

O recorte roda no `agrega()`, antes de qualquer soma, então tudo que é derivado
(CPA, ROAS, funil, mediana de custo por visita) recalcula dentro do recorte.

Duas dimensões não existem no lado do tráfego e por isso têm regra própria, com
aviso no rodapé da barra de chips:

- **Frente**: a frente paga leva toda a mídia do período; frente própria
  (WhatsApp, e-mail, closers) zera o investimento, porque não há mídia amarrada a ela.
- **Oferta**: filtra só a venda. O investimento do Meta não é segmentável por
  oferta, então as colunas de custo continuam sendo o total do período.

## Tooltip nos gráficos

Passar o mouse no gráfico diário mostra o dia inteiro (investido, vendas,
receita, CAC, ROAS, visitas, checkouts); nas barras horizontais mostra receita,
participação, ticket e, na frente paga, CPA e ROAS.

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
