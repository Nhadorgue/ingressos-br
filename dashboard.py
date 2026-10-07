# -*- coding: utf-8 -*-
"""
Dashboard de Shows — Ingressos BR
=================================
Painel Streamlit que carrega automaticamente o arquivo de saída mais recente
(saidas/shows_YYYY-MM-DD_HHMM.json — o de maior número é o mais novo) e exibe o
máximo de informação possível sobre os shows coletados.

Como rodar:
    streamlit run dashboard.py
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------
# Configuração geral
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard de Shows — Ingressos BR",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)

SAIDAS_DIR = Path(__file__).parent / "saidas"

# Paleta categórica validada (data-viz). Cor segue a entidade, nunca o ranking.
PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
       "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
# Rampa sequencial (azul claro -> escuro) para magnitude.
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK = "#0b0b0b"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

MESES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}

UF_REGIAO = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte", "RO": "Norte",
    "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste",
    "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}


# ----------------------------------------------------------------------------
# Carregamento de dados
# ----------------------------------------------------------------------------
def _file_sort_key(p: Path):
    """Ordena por data e número do arquivo shows_YYYY-MM-DD_HHMM.json."""
    m = re.search(r"shows_(\d{4})-(\d{2})-(\d{2})_(\d+)", p.stem)
    if m:
        return tuple(int(g) for g in m.groups())
    return (0, 0, 0, 0)


def listar_arquivos() -> list[Path]:
    if not SAIDAS_DIR.exists():
        return []
    return sorted(SAIDAS_DIR.glob("shows_*.json"), key=_file_sort_key, reverse=True)


@st.cache_data(show_spinner=False)
def carregar(path_str: str, _mtime: float) -> tuple[pd.DataFrame, dict]:
    path = Path(path_str)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    shows = raw.get("shows", [])
    df = pd.DataFrame(shows)

    meta = {
        "gerado_em": raw.get("gerado_em"),
        "total": raw.get("total", len(shows)),
        "arquivo": path.name,
    }
    if df.empty:
        return df, meta

    # Datas
    for col in ("data_show", "abertura_vendas", "pre_venda", "data_extra"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Derivados
    df["ano"] = df["data_show"].dt.year
    df["mes"] = df["data_show"].dt.month
    df["ano_mes"] = df["data_show"].dt.to_period("M").astype(str)
    df["mes_label"] = df["mes"].map(MESES_PT) + "/" + df["ano"].astype("Int64").astype(str)
    df["regiao"] = df["uf"].map(UF_REGIAO).fillna("—")
    df["dias_ate_show"] = (df["data_show"] - pd.Timestamp.now().normalize()).dt.days
    if "abertura_vendas" in df.columns:
        df["antecedencia_venda"] = (df["data_show"] - df["abertura_vendas"]).dt.days

    # Nº de estimativas (campos inferidos) por show
    if "estimativas" in df.columns:
        df["n_estimativas"] = df["estimativas"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        )

    return df, meta


def tem_dados(df: pd.DataFrame, col: str) -> bool:
    """True se a coluna existe e tem ao menos um valor não-nulo."""
    if col not in df.columns:
        return False
    return df[col].notna().any()


# ----------------------------------------------------------------------------
# Estilo dos gráficos
# ----------------------------------------------------------------------------
def estilizar(fig: go.Figure, h: int = 340) -> go.Figure:
    fig.update_layout(
        height=h,
        margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif",
                  size=13, color=INK),
        title=dict(font=dict(size=15)),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(showgrid=False, zeroline=False,
                     linecolor=GRID, tickcolor=GRID, color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, color=MUTED)
    return fig


# ----------------------------------------------------------------------------
# Sidebar — seleção de arquivo + filtros
# ----------------------------------------------------------------------------
arquivos = listar_arquivos()
if not arquivos:
    st.error(f"Nenhum arquivo `shows_*.json` encontrado em `{SAIDAS_DIR}`.")
    st.stop()

with st.sidebar:
    st.markdown("### 🎫 Ingressos BR")
    nomes = [p.name for p in arquivos]
    idx = st.selectbox(
        "Versão dos dados",
        range(len(arquivos)),
        format_func=lambda i: nomes[i] + ("  · mais recente" if i == 0 else ""),
        index=0,
    )
    arquivo = arquivos[idx]

df, meta = carregar(str(arquivo), arquivo.stat().st_mtime)

if df.empty:
    st.warning("O arquivo selecionado não contém shows.")
    st.stop()

with st.sidebar:
    st.divider()
    st.markdown("#### Filtros")

    ufs = sorted(df["uf"].dropna().unique())
    sel_uf = st.multiselect("Estado (UF)", ufs, default=ufs)

    artistas_opt = sorted(df["artista"].dropna().unique())
    busca = st.text_input("Buscar artista / local", "").strip().lower()

    tiqueteiras = sorted(df["tiqueteira"].dropna().unique())
    sel_tq = st.multiselect("Tiqueteira", tiqueteiras, default=tiqueteiras)

    status_opt = sorted(df["status_vendas"].dropna().unique())
    sel_status = st.multiselect("Status de vendas", status_opt, default=status_opt)

    datas_validas = df["data_show"].dropna()
    if not datas_validas.empty:
        dmin, dmax = datas_validas.min().date(), datas_validas.max().date()
        periodo = st.date_input(
            "Período do show",
            value=(dmin, dmax), min_value=dmin, max_value=dmax,
        )
    else:
        periodo = None

    st.divider()
    st.caption(f"Gerado em **{meta['gerado_em']}**")
    st.caption(f"Arquivo: `{meta['arquivo']}`")

# Aplicar filtros
f = df.copy()
f = f[f["uf"].isin(sel_uf)]
f = f[f["tiqueteira"].isin(sel_tq)]
f = f[f["status_vendas"].isin(sel_status)]
if busca:
    mask = (
        f["artista"].str.lower().str.contains(busca, na=False)
        | f["local"].str.lower().str.contains(busca, na=False)
    )
    f = f[mask]
if periodo and isinstance(periodo, (list, tuple)) and len(periodo) == 2:
    ini, fim = periodo
    f = f[
        (f["data_show"].dt.date >= ini) & (f["data_show"].dt.date <= fim)
        | f["data_show"].isna()
    ]

# ----------------------------------------------------------------------------
# Cabeçalho
# ----------------------------------------------------------------------------
st.title("🎫 Dashboard de Shows")
st.caption(
    f"{len(f)} de {len(df)} shows após filtros · dados de {meta['gerado_em']} · "
    f"fonte: {', '.join(tiqueteiras)}"
)

if f.empty:
    st.warning("Nenhum show corresponde aos filtros selecionados.")
    st.stop()

# ----------------------------------------------------------------------------
# KPIs
# ----------------------------------------------------------------------------
hoje = pd.Timestamp.now().normalize()
prox_30 = f[(f["data_show"] >= hoje) & (f["data_show"] <= hoje + pd.Timedelta(days=30))]
prox_show = f[f["data_show"] >= hoje].sort_values("data_show")

c = st.columns(6)
c[0].metric("Shows", len(f))
c[1].metric("Artistas", f["artista"].nunique())
c[2].metric("Estados", f["uf"].nunique())
c[3].metric("Locais", f["local"].nunique())
c[4].metric("Próx. 30 dias", len(prox_30))
if not prox_show.empty:
    nd = int(prox_show.iloc[0]["dias_ate_show"])
    c[5].metric("Próximo show", f"{nd} dias",
                help=f"{prox_show.iloc[0]['artista']} — "
                     f"{prox_show.iloc[0]['data_show'].date()}")
else:
    c[5].metric("Próximo show", "—")

st.divider()

# ----------------------------------------------------------------------------
# Linha 1 — Timeline mensal + Geografia
# ----------------------------------------------------------------------------
col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("Shows por mês")
    tl = (
        f.dropna(subset=["data_show"])
        .groupby("ano_mes")
        .size()
        .reset_index(name="shows")
        .sort_values("ano_mes")
    )
    if not tl.empty:
        tl["rotulo"] = pd.to_datetime(tl["ano_mes"] + "-01").apply(
            lambda d: f"{MESES_PT[d.month]}/{str(d.year)[2:]}"
        )
        fig = px.bar(tl, x="rotulo", y="shows", text="shows")
        fig.update_traces(marker_color=PAL[0], marker_line_width=0,
                          textposition="outside", cliponaxis=False,
                          hovertemplate="%{x}<br>%{y} shows<extra></extra>")
        fig.update_layout(xaxis_title=None, yaxis_title=None)
        st.plotly_chart(estilizar(fig), use_container_width=True)
    else:
        st.info("Sem datas de show válidas.")

with col2:
    st.subheader("Shows por estado")
    por_uf = f.groupby("uf").size().reset_index(name="shows").sort_values("shows")
    fig = px.bar(por_uf, x="shows", y="uf", orientation="h", text="shows",
                 color="shows", color_continuous_scale=SEQ_BLUE)
    fig.update_traces(textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}<br>%{x} shows<extra></extra>")
    fig.update_layout(xaxis_title=None, yaxis_title=None, coloraxis_showscale=False)
    st.plotly_chart(estilizar(fig), use_container_width=True)

# ----------------------------------------------------------------------------
# Linha 2 — Mapa do Brasil + Região
# ----------------------------------------------------------------------------
GEOJSON_UF = "https://raw.githubusercontent.com/codeforgermany/click_that_hood/main/public/data/brazil-states.geojson"


@st.cache_data(show_spinner=False, ttl=86400)
def carregar_geojson():
    import urllib.request
    with urllib.request.urlopen(GEOJSON_UF, timeout=10) as r:
        return json.load(r)


col3, col4 = st.columns([3, 2])

with col3:
    st.subheader("Mapa de shows por estado")
    por_uf_map = f.groupby("uf").size().reset_index(name="shows")
    try:
        geo = carregar_geojson()
        fig = px.choropleth(
            por_uf_map, geojson=geo, locations="uf",
            featureidkey="properties.sigla", color="shows",
            color_continuous_scale=SEQ_BLUE,
            hover_data={"uf": True, "shows": True},
        )
        fig.update_geos(fitbounds="locations", visible=False)
        fig.update_layout(coloraxis_colorbar=dict(title="shows"))
        st.plotly_chart(estilizar(fig, h=420), use_container_width=True)
    except Exception:
        st.info("Mapa indisponível offline — exibindo distribuição por região.")
        reg = f.groupby("regiao").size().reset_index(name="shows")
        fig = px.bar(reg.sort_values("shows"), x="shows", y="regiao",
                     orientation="h", text="shows", color="shows",
                     color_continuous_scale=SEQ_BLUE)
        fig.update_layout(coloraxis_showscale=False, xaxis_title=None, yaxis_title=None)
        st.plotly_chart(estilizar(fig, h=420), use_container_width=True)

with col4:
    st.subheader("Por região")
    reg = f.groupby("regiao").size().reset_index(name="shows").sort_values("shows", ascending=False)
    fig = px.pie(reg, names="regiao", values="shows", hole=0.55,
                 color_discrete_sequence=PAL)
    fig.update_traces(textinfo="label+value",
                      hovertemplate="%{label}<br>%{value} shows (%{percent})<extra></extra>",
                      marker=dict(line=dict(color=SURFACE, width=2)))
    fig.update_layout(showlegend=False)
    st.plotly_chart(estilizar(fig, h=420), use_container_width=True)

st.divider()

# ----------------------------------------------------------------------------
# Linha 3 — Artistas e Locais
# ----------------------------------------------------------------------------
col5, col6 = st.columns(2)

with col5:
    st.subheader("Artistas com mais shows")
    top_art = (
        f.groupby("artista").size().reset_index(name="shows")
        .sort_values("shows", ascending=False).head(15).sort_values("shows")
    )
    multi = top_art[top_art["shows"] > 1]
    base = multi if not multi.empty else top_art.tail(15)
    fig = px.bar(base, x="shows", y="artista", orientation="h", text="shows")
    fig.update_traces(marker_color=PAL[1], textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}<br>%{x} shows<extra></extra>")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    st.plotly_chart(estilizar(fig, h=max(260, 26 * len(base) + 60)),
                    use_container_width=True)

with col6:
    st.subheader("Locais mais usados")
    top_loc = (
        f.groupby(["local", "uf"]).size().reset_index(name="shows")
        .sort_values("shows", ascending=False).head(15)
    )
    top_loc["rotulo"] = top_loc["local"] + " (" + top_loc["uf"] + ")"
    top_loc = top_loc.sort_values("shows")
    fig = px.bar(top_loc, x="shows", y="rotulo", orientation="h", text="shows")
    fig.update_traces(marker_color=PAL[2], textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}<br>%{x} shows<extra></extra>")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    st.plotly_chart(estilizar(fig, h=max(260, 26 * len(top_loc) + 60)),
                    use_container_width=True)

st.divider()

# ----------------------------------------------------------------------------
# Linha 4 — Janela de vendas (antecedência) + Aberturas por mês
# ----------------------------------------------------------------------------
if tem_dados(f, "abertura_vendas"):
    col7, col8 = st.columns(2)

    with col7:
        st.subheader("Antecedência de venda")
        st.caption("Dias entre a abertura das vendas e a data do show")
        ant = f.dropna(subset=["antecedencia_venda"])
        ant = ant[ant["antecedencia_venda"] >= 0]
        if not ant.empty:
            fig = px.histogram(ant, x="antecedencia_venda", nbins=20)
            fig.update_traces(marker_color=PAL[6], marker_line_color=SURFACE,
                              marker_line_width=1,
                              hovertemplate="%{x} dias<br>%{y} shows<extra></extra>")
            fig.update_layout(xaxis_title="dias de antecedência", yaxis_title="shows",
                              bargap=0.05)
            st.plotly_chart(estilizar(fig), use_container_width=True)
            med = int(ant["antecedencia_venda"].median())
            st.caption(f"Mediana: **{med} dias** de antecedência.")
        else:
            st.info("Sem dados suficientes de antecedência.")

    with col8:
        st.subheader("Aberturas de venda por mês")
        ab = (
            f.dropna(subset=["abertura_vendas"])
            .assign(am=lambda d: d["abertura_vendas"].dt.to_period("M").astype(str))
            .groupby("am").size().reset_index(name="aberturas").sort_values("am")
        )
        if not ab.empty:
            ab["rotulo"] = pd.to_datetime(ab["am"] + "-01").apply(
                lambda d: f"{MESES_PT[d.month]}/{str(d.year)[2:]}")
            fig = px.bar(ab, x="rotulo", y="aberturas", text="aberturas")
            fig.update_traces(marker_color=PAL[3], textposition="outside",
                              cliponaxis=False,
                              hovertemplate="%{x}<br>%{y} aberturas<extra></extra>")
            fig.update_layout(xaxis_title=None, yaxis_title=None)
            st.plotly_chart(estilizar(fig), use_container_width=True)
        else:
            st.info("Sem datas de abertura de venda.")

    st.divider()

# ----------------------------------------------------------------------------
# Linha 5 — Status + Tiqueteira + Completude dos dados
# ----------------------------------------------------------------------------
col9, col10, col11 = st.columns(3)

with col9:
    st.subheader("Status de vendas")
    stt = f.groupby("status_vendas").size().reset_index(name="shows")
    fig = px.pie(stt, names="status_vendas", values="shows", hole=0.55,
                 color_discrete_sequence=PAL)
    fig.update_traces(textinfo="label+value",
                      marker=dict(line=dict(color=SURFACE, width=2)),
                      hovertemplate="%{label}<br>%{value} (%{percent})<extra></extra>")
    fig.update_layout(showlegend=False)
    st.plotly_chart(estilizar(fig, h=300), use_container_width=True)

with col10:
    st.subheader("Tiqueteira")
    tq = f.groupby("tiqueteira").size().reset_index(name="shows").sort_values("shows")
    fig = px.bar(tq, x="shows", y="tiqueteira", orientation="h", text="shows")
    fig.update_traces(marker_color=PAL[4], textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}<br>%{x} shows<extra></extra>")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    st.plotly_chart(estilizar(fig, h=300), use_container_width=True)

with col11:
    st.subheader("Completude dos dados")
    st.caption("% de shows com cada campo preenchido")
    campos = ["artista", "data_show", "cidade", "uf", "local", "capacidade",
              "abertura_vendas", "preco_inteira_min", "setores",
              "status_vendas", "fonte"]
    campos = [c for c in campos if c in f.columns]
    comp = pd.DataFrame({
        "campo": campos,
        "pct": [round(f[c].notna().mean() * 100) for c in campos],
    }).sort_values("pct")
    fig = px.bar(comp, x="pct", y="campo", orientation="h", text="pct",
                 color="pct", color_continuous_scale=SEQ_BLUE, range_x=[0, 105])
    fig.update_traces(texttemplate="%{text}%", textposition="outside",
                      cliponaxis=False,
                      hovertemplate="%{y}: %{x}%<extra></extra>")
    fig.update_layout(coloraxis_showscale=False, xaxis_title=None, yaxis_title=None)
    st.plotly_chart(estilizar(fig, h=300), use_container_width=True)

# ----------------------------------------------------------------------------
# Seção de preços (renderizada só quando houver dados)
# ----------------------------------------------------------------------------
if tem_dados(f, "preco_inteira_min") or tem_dados(f, "preco_inteira_max"):
    st.divider()
    st.subheader("💰 Preços de ingresso (inteira)")
    pf = f.dropna(subset=["preco_inteira_min"]).copy()
    k = st.columns(4)
    k[0].metric("Menor preço", f"R$ {pf['preco_inteira_min'].min():.0f}")
    k[1].metric("Maior preço", f"R$ {pf['preco_inteira_max'].max():.0f}"
                if tem_dados(pf, "preco_inteira_max") else "—")
    k[2].metric("Média (mín.)", f"R$ {pf['preco_inteira_min'].mean():.0f}")
    k[3].metric("Shows com preço", len(pf))
    top_preco = pf.sort_values("preco_inteira_min", ascending=False).head(15)
    fig = px.bar(top_preco.sort_values("preco_inteira_min"),
                 x="preco_inteira_min", y="artista", orientation="h")
    fig.update_traces(marker_color=PAL[5],
                      hovertemplate="%{y}<br>R$ %{x}<extra></extra>")
    fig.update_layout(xaxis_title="preço mínimo (R$)", yaxis_title=None)
    st.plotly_chart(estilizar(fig, h=max(260, 26 * len(top_preco) + 60)),
                    use_container_width=True)

# ----------------------------------------------------------------------------
# Próximos shows (agenda)
# ----------------------------------------------------------------------------
st.divider()
st.subheader("📅 Próximos shows")
ag = prox_show.head(12)
if ag.empty:
    st.info("Nenhum show futuro nos dados filtrados.")
else:
    for _, r in ag.iterrows():
        cidade = r["cidade"] if pd.notna(r.get("cidade")) else r["uf"]
        dd = int(r["dias_ate_show"])
        with st.container(border=True):
            cc = st.columns([3, 2, 2, 1])
            cc[0].markdown(f"**{r['artista']}**")
            cc[1].markdown(f"{r['data_show'].date()}  ·  {dd} dias")
            cc[2].markdown(f"{r['local']} — {cidade}/{r['uf']}")
            if pd.notna(r.get("fonte")):
                cc[3].markdown(f"[ingresso]({r['fonte']})")

# ----------------------------------------------------------------------------
# Tabela completa + download
# ----------------------------------------------------------------------------
st.divider()
st.subheader("🗂️ Tabela completa")

cols_show = [c for c in [
    "artista", "data_show", "cidade", "uf", "local", "tiqueteira",
    "abertura_vendas", "antecedencia_venda", "status_vendas",
    "preco_inteira_min", "preco_inteira_max", "capacidade", "fonte",
] if c in f.columns]

tab = f[cols_show].copy().sort_values("data_show")
for dcol in ("data_show", "abertura_vendas"):
    if dcol in tab.columns:
        tab[dcol] = tab[dcol].dt.strftime("%Y-%m-%d")

st.dataframe(
    tab,
    use_container_width=True,
    hide_index=True,
    column_config={
        "fonte": st.column_config.LinkColumn("fonte", display_text="abrir"),
        "data_show": "data do show",
        "abertura_vendas": "abertura vendas",
        "antecedencia_venda": st.column_config.NumberColumn("antec. (dias)"),
        "status_vendas": "status",
    },
)

dl1, dl2 = st.columns(2)
dl1.download_button(
    "⬇️ Baixar CSV (filtrado)",
    tab.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"shows_filtrado_{datetime.now():%Y%m%d_%H%M}.csv",
    mime="text/csv",
)
dl2.download_button(
    "⬇️ Baixar JSON (filtrado)",
    f[cols_show].to_json(orient="records", force_ascii=False, date_format="iso"),
    file_name=f"shows_filtrado_{datetime.now():%Y%m%d_%H%M}.json",
    mime="application/json",
)

st.caption(
    "Campos como capacidade, preços, setores, público e validação facial aparecem "
    "automaticamente quando presentes nos dados. Itens marcados em `estimativas` "
    "são valores inferidos, não confirmados pela fonte."
)
