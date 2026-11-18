# Radar Nordestino (`radarnordestino`)

Portais independentes, estáticos e automatizados de transparência legislativa e eleitoral para **13 cidades do Nordeste (Mandato 2025–2028)**, com atualização diária via GitHub Actions.

## Cidades Monitoradas (292 vereadores + 13 prefeitos)

### Capitais Estaduais (4)
- **Salvador – BA** (`/salvador/` · 43 vereadores · Prefeito Bruno Reis)
- **São Luís – MA** (`/saoluis/` · 31 vereadores · Prefeito Eduardo Braide)
- **Maceió – AL** (`/maceio/` · 27 vereadores · Prefeito JHC)
- **Aracaju – SE** (`/aracaju/` · 26 vereadores · Prefeita Emília Corrêa)

### Polos Regionais e Regiões Metropolitanas (9)
- **Caruaru – PE** (`/caruaru/` · 23 vereadores · Prefeito Rodrigo Pinheiro)
- **Petrolina – PE** (`/petrolina/` · 23 vereadores · Prefeito Simão Durando)
- **Campina Grande – PB** (`/campinagrande/` · 23 vereadores · Prefeito Bruno Cunha Lima)
- **Maracanaú – CE** (`/maracanau/` · 21 vereadores · Prefeito Roberto Pessoa)
- **Mossoró – RN** (`/mossoro/` · 21 vereadores · Prefeito Allyson Bezerra)
- **Patos – PB** (`/patos/` · 17 vereadores · Prefeito Nabor Wanderley)
- **Cruz das Almas – BA** (`/cruzdasalmas/` · 15 vereadores · Prefeito Ednaldo Ribeiro)
- **Irecê – BA** (`/irece/` · 15 vereadores · Prefeito Murilo Franca)
- **Santo Antônio de Jesus – BA** (`/santoantoniodejesus/` · 14 vereadores · Prefeito Genival Deolino)

## Fontes de Dados
- **Câmaras Municipais / SAPL Interlegis**: proposições, autoria, presença e dados parlamentares quando disponíveis em API aberta.
- **TSE Dados Abertos (2012–2026)**: recortes estaduais (`AL, BA, CE, MA, PB, PE, RN, SE`) de candidaturas, votação nominal e prestação de contas eleitorais.

## Uso Local

```bash
pip install Pillow
python3 scripts/tse_consolidar.py   # Consolida base TSE 2012–2026 dos 8 estados
python3 coletar.py                  # Gera todos os 13 portais + Hub raiz
```
