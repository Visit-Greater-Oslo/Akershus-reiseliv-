"""
Reiseliv i Akershus - Streamlit-app
Henter data direkte fra SSBs PxWebAPI v2, filtrert på reiselivsregion.

Kjør lokalt:      streamlit run app.py
Krever:           streamlit, pandas, requests (se requirements.txt)

VIKTIG (les også chatsvaret): koden er ikke kjørt mot den levende SSB-APIen i
miljøet den ble skrevet i. Diagnostikk-boksen øverst i appen lar deg sjekke om
alt stemmer FØR du stoler på tallene under.
"""

import itertools

import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Oppsett
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Reiseliv i Akershus", layout="wide")

BASE = "https://data.ssb.no/api/pxwebapi/v2/tables"
AKERSHUS_REGION_PREFIX = "032*"  # antatt - bekreft i diagnostikk-boksen under
AKERSHUS_REGION_KEYWORDS = ["Follo", "Romerike", "Asker", "Bærum", "Hadeland"]

TABELLER = {
    "Overnattinger":                    {"id": "14172", "tid_fra": "2022M01"},
    "Kapasitet (rom/senger/bedrifter)":  {"id": "14173", "tid_fra": "2022M01"},
    "Ankomne gjester":                   {"id": "14174", "tid_fra": "2022M01"},
    "Hotell - formål med opphold":       {"id": "14175", "tid_fra": "2022M01"},
    "Hotell - omsetning og utnyttelse":  {"id": "14176", "tid_fra": "2022M01"},
    "Hotell - nøkkelindikatorer":        {"id": "14177", "tid_fra": "2022M01"},
    "Verdiskaping (overnattingsnæring)": {"id": "13185", "tid_fra": "2022"},
}


# ---------------------------------------------------------------------------
# Datahenting (cachet, så SSB ikke spørres på nytt for hver klikk i UI-et)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_metadata(table_id: str) -> dict:
    r = requests.get(f"{BASE}/{table_id}/metadata", params={"lang": "no"}, timeout=30)
    r.raise_for_status()
    return r.json()


def variable_ids(meta: dict) -> list:
    """SSBs metadata-endepunkt bruker IKKE en 'variables'-liste (det jeg antok
    før), men samme JSON-stat2-struktur som selve dataene: en ordnet liste
    'id' med variabelnavn, og detaljer i 'dimension'. Bekreftet mot SSBs egen
    dokumentasjon (pxtools.net/PxWebApi)."""
    return meta["id"]


def ordered_codes(meta: dict, var_id: str) -> list:
    """Returnerer [(kode, tekst), ...] for en variabel, i riktig rekkefølge
    (category.index kan være usortert i selve JSON-en - se dokumentasjonen)."""
    cat = meta["dimension"][var_id]["category"]
    index = cat.get("index", {})
    labels = cat.get("label", {})
    codes = sorted(index, key=lambda k: index[k]) if isinstance(index, dict) else list(index)
    return [(c, labels.get(c, c)) for c in codes]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_table(table_id: str, tid_fra: str, region_pattern: str = AKERSHUS_REGION_PREFIX) -> dict:
    meta = get_metadata(table_id)
    params = {"lang": "no", "outputFormat": "json-stat2"}
    for vid in variable_ids(meta):
        if vid == "Region":
            params[f"valueCodes[{vid}]"] = region_pattern
        elif vid == "Tid":
            params[f"valueCodes[{vid}]"] = f"from({tid_fra})"
        else:
            params[f"valueCodes[{vid}]"] = "*"
    r = requests.get(f"{BASE}/{table_id}/data", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def jsonstat_to_dataframe(jsonstat: dict) -> pd.DataFrame:
    dim_ids = jsonstat["id"]
    values = jsonstat["value"]
    dim_categories = []
    for dim_id in dim_ids:
        cat = jsonstat["dimension"][dim_id]["category"]
        index = cat.get("index", {})
        labels = cat.get("label", {})
        ordered_codes = sorted(index, key=lambda k: index[k]) if isinstance(index, dict) else list(index)
        dim_categories.append([(code, labels.get(code, code)) for code in ordered_codes])
    rows = []
    for combo, val in zip(itertools.product(*dim_categories), values):
        row = {}
        for dim_id, (code, label) in zip(dim_ids, combo):
            row[f"{dim_id}_kode"] = code
            row[f"{dim_id}_navn"] = label
        row["verdi"] = val
        rows.append(row)
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def hent_dataframe(visningsnavn: str) -> pd.DataFrame:
    cfg = TABELLER[visningsnavn]
    data = fetch_table(cfg["id"], cfg["tid_fra"])
    return jsonstat_to_dataframe(data)


# ---------------------------------------------------------------------------
# Sidehode + diagnostikk
# ---------------------------------------------------------------------------

st.title("Reiseliv i Akershus")
st.caption("Data hentet direkte fra SSBs statistikkbank (PxWebAPI v2), per reiselivsregion.")

with st.expander("Diagnostikk - sjekk dette FØRST", expanded=False):
    st.write(
        "Denne boksen henter regionlisten fra tabell 14172 og markerer hvilke "
        "regioner som ser ut til å være i Akershus (kode starter med «032» eller "
        "navnet inneholder Follo/Romerike/Asker/Bærum/Hadeland). Stemmer ikke "
        "dette, må `AKERSHUS_REGION_PREFIX` øverst i koden justeres."
    )
    try:
        meta = get_metadata("14172")
        par = ordered_codes(meta, "Region")
        diag = pd.DataFrame(par, columns=["kode", "navn"])
        diag["akershus?"] = diag["kode"].str.startswith("032") | diag["navn"].str.contains(
            "|".join(AKERSHUS_REGION_KEYWORDS), case=False, na=False
        )
        st.write(f"Fant {diag['akershus?'].sum()} regioner som ser ut til å være i Akershus:")
        st.dataframe(diag[diag["akershus?"]], use_container_width=True, hide_index=True)
        with st.popover("Vis alle regioner i tabellen"):
            st.dataframe(diag, use_container_width=True, hide_index=True, height=300)
    except Exception as e:
        st.error(f"Klarte ikke hente metadata fra SSB: {e}")
        st.info(
            "Sjekk at tabellnummeret finnes og at nettverkstilgang virker - "
            "prøv å åpne https://data.ssb.no/api/pxwebapi/v2/tables/14172/metadata?lang=no "
            "direkte i nettleseren for å se rå-svaret fra SSB."
        )
        st.stop()


# ---------------------------------------------------------------------------
# Velg datasett
# ---------------------------------------------------------------------------

st.sidebar.header("Filtre")
valgt_tabell = st.sidebar.selectbox("Datasett", list(TABELLER.keys()))

try:
    with st.spinner(f"Henter «{valgt_tabell}» fra SSB..."):
        df = hent_dataframe(valgt_tabell)
except Exception as e:
    st.error(f"Klarte ikke hente «{valgt_tabell}» fra SSB: {e}")
    st.info(
        "Vanligste årsak: perioden for denne tabellen er årlig, ikke månedlig "
        f"(eller omvendt) - juster 'tid_fra' i TABELLER-oppslaget for "
        f"'{valgt_tabell}' til f.eks. '2022' uten måned. Sjekk også "
        f"diagnostikk-boksen øverst for å se om SSB svarer i det hele tatt."
    )
    st.stop()

if df.empty:
    st.warning(
        "Fikk 0 rader tilbake. Sjekk diagnostikk-boksen - regionfilteret "
        f"'{AKERSHUS_REGION_PREFIX}' traff kanskje ingen rader i denne tabellen."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Dynamiske filtre - bygges ut fra kolonnene tabellen faktisk har
# ---------------------------------------------------------------------------

st.sidebar.divider()
filtrert = df.copy()

if "Region_navn" in filtrert.columns:
    regioner = sorted(filtrert["Region_navn"].unique())
    valgte_regioner = st.sidebar.multiselect("Reiselivsregion", regioner, default=regioner)
    filtrert = filtrert[filtrert["Region_navn"].isin(valgte_regioner)]

kategori_kolonner = [c for c in df.columns if c.endswith("_navn") and c not in ("Region_navn", "Tid_navn")]

st.sidebar.caption(
    "Forvalgt kategori under er vanligvis SSBs totalkategori («I alt») - "
    "bytt selv om det ser feil ut, eller velg flere for å se breddet."
)
for kol in kategori_kolonner:
    valg = list(dict.fromkeys(filtrert[kol]))  # unike verdier i ORIGINAL rekkefølge (ikke alfabetisk!)
    if len(valg) <= 1:
        continue
    label = kol.replace("_navn", "")
    if kol == "ContentsCode_navn":
        # Ulike statistikkvariabler har ulik måleenhet (kr, %, antall) og kan
        # ikke summeres sammen - derfor kun ett valg om gangen her.
        valgt = st.sidebar.selectbox(label, valg)
        filtrert = filtrert[filtrert[kol] == valgt]
    elif len(valg) > 50:
        st.sidebar.caption(f"{label}: {len(valg)} kategorier - viser kun «{valg[0]}» (antatt total).")
        filtrert = filtrert[filtrert[kol] == valg[0]]
    else:
        valgte = st.sidebar.multiselect(f"{label} ({len(valg)} kategorier)", valg, default=[valg[0]])
        filtrert = filtrert[filtrert[kol].isin(valgte)]

if "Tid_navn" in filtrert.columns:
    perioder = sorted(filtrert["Tid_navn"].unique())
    valgte_perioder = st.sidebar.multiselect("Periode", perioder, default=perioder)
    filtrert = filtrert[filtrert["Tid_navn"].isin(valgte_perioder)]


# ---------------------------------------------------------------------------
# Visning
# ---------------------------------------------------------------------------

st.subheader(valgt_tabell)

if filtrert.empty:
    st.warning("Ingen data igjen etter filtrering - fjern eller endre et filter i sidepanelet.")
    st.stop()

col1, col2 = st.columns([1, 2])
with col1:
    total = filtrert["verdi"].sum()
    st.metric("Sum, valgt utvalg", f"{total:,.0f}".replace(",", " "))
    st.metric("Antall rader", len(filtrert))
    st.caption("Enheten (kroner, prosent, antall ...) avhenger av hvilken kategori du har valgt i sidepanelet.")
with col2:
    if "Tid_navn" in filtrert.columns:
        trend = filtrert.groupby("Tid_navn")["verdi"].sum()
        trend = trend.reindex(sorted(trend.index))
        st.line_chart(trend)

if "Region_navn" in filtrert.columns and filtrert["Region_navn"].nunique() > 1:
    per_region = filtrert.groupby("Region_navn")["verdi"].sum().sort_values(ascending=False)
    st.bar_chart(per_region)

st.divider()
st.subheader("Data (etter filtrering)")
st.dataframe(filtrert, use_container_width=True)
st.download_button(
    "Last ned som CSV",
    filtrert.to_csv(index=False).encode("utf-8"),
    file_name=f"{valgt_tabell.lower().replace(' ', '_').replace('æ','ae').replace('ø','oe').replace('å','aa')}.csv",
)

