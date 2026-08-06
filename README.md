# MXP-Fp01 2026 — Tráfego x vendas reais

Dashboard que cruza a mídia paga (Meta) com a venda real da Hubla, separada por frente (`utm_source`).

- `index.html` — dashboard pronto (dados embutidos, abre com duplo clique)
- `data.json` — dataset agregado (sem PII)
- `build.py` — lê as duas planilhas e gera `data.json` + `index.html`
- `template.html` — layout/JS; `build.py` injeta os dados no lugar de `/*__DATA__*/`

## Fontes

| O quê | Planilha | Aba |
|---|---|---|
| Tráfego (Meta, nível anúncio/dia) | `12ldEcVBAyIWcX2APu3CVS82aeswbwxsbJZCYIGN4KKY` | `dados_trafego` |
| Vendas (Hubla) | `13uDvwhiiaLsiob1IDzSiGwpktCuZXWUWYXnzyL__3vQ` | `VENDAS` |

A aba VENDAS é alimentada em tempo real pelo workflow n8n `[MXP-FP01] VENDAS HUBLA 2026`
(webhook `/webhook/mxp-2026-vendas`) e pelo backfill `_scripts/hubla_backfill_mxp.py`.

## Regras de leitura

- **Venda = Hubla, nunca pixel.** O card de alerta compara os dois de propósito: divergência é esperada (janela de atribuição e view-through do Meta).
- **Frente paga = `utm_source` contendo meta/facebook/instagram.** Só ela recebe CPA e ROAS, porque só ela tem investimento amarrado. As demais (WhatsApp, e-mail, closers) entram na receita mas ficam com `—` nas colunas de custo.
- **Vendas estornadas** (`refunded`/`canceled`/`chargeback`) saem de toda a leitura.
- **Venda por criativo** cruza `utm_content` da Hubla com o Ad Name do Meta pelo código `AD-nn`.
- ROAS geral do topo é leitura de **caixa**, não de eficiência de mídia, sempre que a janela de vendas começar antes da janela de tráfego.

## Atualizar

```bash
cd ~/Documents/CLAUDE_CODE_2026/dashboards/MXP-2026-Dash && python3 build.py
```
