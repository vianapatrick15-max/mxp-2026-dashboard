# MXP 2026 — O ano fechado

Dashboard irmão do MXP-Fp01 (pasta acima). Site separado, Pages separado:

| | |
|---|---|
| Janela de venda, dia a dia, criativo a criativo | https://mxp-2026-dashboard.pages.dev |
| **O ano inteiro do evento** | **https://mxp-2026-ano.pages.dev** |

São o mesmo repositório e o mesmo refresh de 4 em 4 horas, mas respondem perguntas
diferentes. O da janela pergunta "o que fazer amanhã com a verba"; este pergunta
"quanto o evento custou e devolveu em 2026". Por isso aqui não há filtro de período,
nem aba de metas, nem card de criativo: página única, tudo já agregado.

O que tem: acumulado do ano (investimento, receita, vendas, CAC blended, ROAS),
os três ciclos de mídia, mês a mês com curva acumulada, verba por conta de anúncio
e por funil, as campanhas do ano, origem da receita, time de vendas e mix de ofertas.

## Arquivos

- `build.py` — junta as quatro fontes e gera `data.json` + `index.html`
- `template.html` — layout/JS (CSS herdado do dashboard da janela, para os dois
  parecerem a mesma família); `build.py` injeta os dados no lugar de `/*__DATA__*/`
- `pull_trafego_ano.py` — snapshot do ano na Meta API → `trafego_ano.json`
- `import_vendas_hubla.py` — export XLSX do painel Hubla → `vendas_ano.json`
- `deploy.sh` — build + publish no Pages `mxp-2026-ano`

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
./deploy.sh && git add -A && git commit && git push
```

`pull_trafego_ano.py` varre as 9 contas das duas BMs filtrando campanha com "mxp" no
nome, **mês a mês** — o ano inteiro de uma vez a Meta derruba com "Service temporarily
unavailable" nas contas com volume. `import_vendas_hubla.py` ignora o produto
"Palestras MXP 2025", que é outro evento e vem no mesmo export.

## Regras de leitura

- **Merge das fontes**: onde a planilha viva tem dado, ela manda; o snapshot entra só
  no que ela não cobre e aí vira campanha/dia. Nas vendas a planilha ganha por
  `id_fatura`, porque o export só lista fatura paga e **reembolso só existe do lado
  vivo**.
- **A conta de anúncio nunca é inferida da planilha.** Depois da migração de 27/08 a
  mesma campanha rodou na C3 e na C4 Mem; chutar a conta infla uma e zera a outra.
  Quem responde verba por conta é o snapshot.
- **Ciclo é janela de data, não clique.** O evento teve três investidas de mídia
  (Mxp-Le01 em fev, Mxp-Le02 em mar-abr, MXP-Fp01 de ago até o evento) e a venda entra
  no ciclo pelo dia do pagamento: não dá para amarrar venda de fevereiro a criativo de
  agosto, e o closer fecha dias depois do anúncio. Bordas no dict `CICLOS`.
- **A leitura do evento é blended.** Só 90 das 496 vendas chegaram com `utm` de mídia:
  o grosso entra por WhatsApp e pelo time de vendas, que fecha o lead que a mídia
  trouxe. O ROAS da frente paga isolada não responde pelo evento, e campanha de
  captação aparece sem venda de propósito.
- **Venda = Hubla, nunca pixel.** Estornos (`refunded`/`canceled`/`chargeback`) saem
  de toda a leitura.
- **Receita é valor total da fatura** (com juros de parcelamento), mesma base do campo
  `valor` da planilha viva.
