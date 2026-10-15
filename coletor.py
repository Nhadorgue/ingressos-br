# -*- coding: utf-8 -*-
"""
Coletor de shows — Ingressos BR
===============================
Busca shows de música no Brasil na API Discovery da Ticketmaster, ranqueia por
relevância e grava `saidas/shows_AAAA-MM-DD_HHMM.json` (+ `.xlsx`).

É a mesma lógica que estava no `teste.ipynb`, empacotada em funções para poder
ser chamada automaticamente pelo dashboard (botão "Atualizar agora" e
auto-coleta quando os dados estão velhos) ou direto no terminal:

    python coletor.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# Carrega TICKETMASTER_API_KEY (e demais variáveis) do arquivo .env ao lado.
load_dotenv(Path(__file__).parent / ".env")

BASE = "https://app.ticketmaster.com/discovery/v2/events.json"
ATTR = "https://app.ticketmaster.com/discovery/v2/attractions.json"
SAIDA = Path(__file__).parent / "saidas"

JANELA_DIAS = 180   # quantos dias à frente buscar
TOP = 50            # quantos shows manter após o ranking de relevância

# Capacidades e regras que não vêm da API — preencha conforme for aprendendo.
LOCAIS: dict[str, dict] = {
    # "Allianz Parque": {"capacidade": 43000, "nominal": True, "facial": True},
}

CAMPOS = [
    "artista", "data_show", "cidade", "uf", "local", "capacidade",
    "tiqueteira", "abertura_vendas", "pre_venda",
    "preco_inteira_min", "preco_inteira_max", "preco_meia_min", "preco_meia_max",
    "setores", "publico_ultimo_show_br", "ingresso_nominal",
    "validacao_facial", "data_extra", "status_vendas",
    "estimativas", "fonte", "verificado_em",
]


class ColetaError(RuntimeError):
    """Erro previsível de coleta (ex.: chave ausente, API fora do ar)."""


# ---------------------------------------------------------------------------
# Acesso à API
# ---------------------------------------------------------------------------
def _key() -> str:
    k = os.environ.get("TICKETMASTER_API_KEY")
    if not k:
        raise ColetaError(
            "TICKETMASTER_API_KEY não encontrada. Defina-a no arquivo .env "
            "(TICKETMASTER_API_KEY=sua_chave)."
        )
    return k


def buscar(key: str, keyword: str | None = None, janela_dias: int = JANELA_DIAS) -> list[dict]:
    """Eventos de música no Brasil nos próximos `janela_dias` dias."""
    agora = datetime.now(timezone.utc)
    ini = agora.strftime("%Y-%m-%dT%H:%M:%SZ")
    fim = (agora + timedelta(days=janela_dias)).strftime("%Y-%m-%dT%H:%M:%SZ")

    eventos, pagina = [], 0
    while True:
        p = {
            "apikey": key, "countryCode": "BR", "classificationName": "Music",
            "startDateTime": ini, "endDateTime": fim, "size": 200, "page": pagina,
        }
        if keyword:
            p["keyword"] = keyword
        r = requests.get(BASE, params=p, timeout=30)
        r.raise_for_status()
        d = r.json()
        eventos += d.get("_embedded", {}).get("events", [])
        if pagina >= d.get("page", {}).get("totalPages", 1) - 1 or pagina >= 4:
            break
        pagina += 1
        time.sleep(0.3)
    return eventos


def converter(e: dict) -> dict:
    """Converte um evento cru da Ticketmaster no formato do dashboard."""
    venue = (e.get("_embedded", {}).get("venues") or [{}])[0]
    nome_local = venue.get("name", "")
    extra = LOCAIS.get(nome_local, {})
    precos = e.get("priceRanges") or []
    vendas = e.get("sales", {}).get("public", {})
    presales = e.get("sales", {}).get("presales") or []
    estimativas = [] if extra else ["capacidade", "ingresso_nominal", "validacao_facial"]
    return {
        "artista": (e.get("_embedded", {}).get("attractions") or [{}])[0].get("name", e.get("name")),
        "data_show": e.get("dates", {}).get("start", {}).get("localDate"),
        "cidade": venue.get("city", {}).get("name"),
        "uf": venue.get("state", {}).get("stateCode"),
        "local": nome_local,
        "capacidade": extra.get("capacidade"),
        "tiqueteira": "Ticketmaster",
        "abertura_vendas": (vendas.get("startDateTime") or "")[:10] or None,
        "pre_venda": (presales[0].get("startDateTime") or "")[:10] if presales else None,
        "preco_inteira_min": precos[0].get("min") if precos else None,
        "preco_inteira_max": precos[0].get("max") if precos else None,
        "preco_meia_min": None, "preco_meia_max": None,
        "setores": [],
        "publico_ultimo_show_br": None,
        "ingresso_nominal": extra.get("nominal"),
        "validacao_facial": extra.get("facial"),
        "data_extra": None,
        "status_vendas": e.get("dates", {}).get("status", {}).get("code"),
        "estimativas": estimativas,
        "fonte": e.get("url"),
    }


def ranquear(shows: list[dict], key: str, top: int = TOP) -> list[dict]:
    """Ordena por relevância (eventos futuros do artista + teto de preço)."""
    if not shows:
        return []

    cache: dict[str, int] = {}

    def eventos_futuros(nome: str) -> int:
        if nome in cache:
            return cache[nome]
        try:
            r = requests.get(ATTR, params={"apikey": key, "keyword": nome, "size": 1}, timeout=30)
            a = (r.json().get("_embedded", {}).get("attractions") or [{}])[0]
            cache[nome] = (a.get("upcomingEvents", {}) or {}).get("_total", 0)
        except requests.RequestException:
            cache[nome] = 0
        time.sleep(0.2)
        return cache[nome]

    df = pd.DataFrame(shows)
    df["eventos_futuros"] = df["artista"].map(eventos_futuros)
    df["teto_preco"] = pd.to_numeric(df["preco_inteira_max"], errors="coerce").fillna(0)

    for c in ["eventos_futuros", "teto_preco"]:
        mx = df[c].max() or 1
        df[c + "_n"] = df[c] / mx

    df["score_relevancia"] = 0.7 * df["eventos_futuros_n"] + 0.3 * df["teto_preco_n"]
    df = df.sort_values("score_relevancia", ascending=False).reset_index(drop=True)

    auxiliares = [c for c in df.columns if c.endswith("_n")] + \
                 ["eventos_futuros", "teto_preco", "score_relevancia"]
    return df.head(top).drop(columns=auxiliares).to_dict("records")


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------
def _salvar(registros: list[dict], agora: datetime) -> Path:
    SAIDA.mkdir(exist_ok=True)
    carimbo = agora.strftime("%Y-%m-%d_%H%M")
    cam_json = SAIDA / f"shows_{carimbo}.json"
    cam_xlsx = SAIDA / f"shows_{carimbo}.xlsx"
    gerado_em = agora.strftime("%Y-%m-%d %H:%M")

    with open(cam_json, "w", encoding="utf-8") as f:
        json.dump(
            {"gerado_em": gerado_em, "total": len(registros), "shows": registros},
            f, ensure_ascii=False, indent=2,
        )

    df = pd.DataFrame(registros)
    plano = [
        {"artista": r["artista"], "data_show": r["data_show"], **s}
        for r in registros for s in (r.get("setores") or [])
    ]
    with pd.ExcelWriter(cam_xlsx, engine="openpyxl") as w:
        df.assign(
            setores=df["setores"].apply(lambda x: json.dumps(x, ensure_ascii=False)),
            estimativas=df["estimativas"].apply(lambda x: ", ".join(x or [])),
        ).to_excel(w, sheet_name="Shows", index=False)
        if plano:
            pd.DataFrame(plano).to_excel(w, sheet_name="Precos_por_setor", index=False)

    return cam_json


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def coletar(janela_dias: int = JANELA_DIAS, top: int = TOP, salvar: bool = True):
    """Coleta, ranqueia e (por padrão) grava os shows.

    Retorna o `Path` do JSON gerado quando `salvar=True`; caso contrário,
    retorna a lista de registros.
    """
    key = _key()

    brutos = buscar(key, None, janela_dias)
    vistos, shows = set(), []
    for e in brutos:
        eid = e.get("id")
        if eid in vistos:
            continue
        vistos.add(eid)
        shows.append(converter(e))

    shows = ranquear(shows, key, top)

    agora = datetime.now()
    verificado_em = agora.strftime("%Y-%m-%d %H:%M")
    registros = []
    for s in shows:
        r = {c: s.get(c) for c in CAMPOS}
        r["verificado_em"] = verificado_em
        registros.append(r)

    if salvar:
        return _salvar(registros, agora)
    return registros


if __name__ == "__main__":
    caminho = coletar()
    print(f"OK: {caminho.name} gravado em {caminho.parent}")
