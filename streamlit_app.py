
import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import openai
from urllib.parse import urljoin, urlparse
import time
import re
import io


# ---- Helper functions ----
def get_visible_text(html):
    soup = BeautifulSoup(html, "html.parser")
    # Remove scripts/styles
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    # Get text, filter empty/whitespace
    texts = soup.stripped_strings
    return " ".join([t for t in texts if t and len(t) > 20])

def is_internal_link(base_url, link):
    base_domain = urlparse(base_url).netloc
    target = urljoin(base_url, link)
    return urlparse(target).netloc == base_domain

def is_irrelevant_link(link_text):
    blacklist = [
        "kontakt", "privacy", "polityka", "regulamin", "terms",
        "cookies", "kariera", "praca", "career", "login", "logowanie"
    ]
    return any(b in link_text.lower() for b in blacklist)

def find_relevant_links(base_url, soup, max_links=3):
    links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(separator=" ", strip=True)
        href = a["href"]
        if is_internal_link(base_url, href) and not is_irrelevant_link(href + " " + text):
            url = urljoin(base_url, href)
            if url not in links and url != base_url:
                links.append(url)
        if len(links) >= max_links:
            break
    return links

def scrape_website(url, max_pages=4, timeout=8):
    try:
        res = requests.get(url, timeout=timeout, headers={'User-Agent': 'Mozilla/5.0'})
        res.raise_for_status()
        html = res.text
        main_text = get_visible_text(html)
        soup = BeautifulSoup(html, "html.parser")
        subpage_links = find_relevant_links(url, soup, max_links=max_pages-1)
        texts = [main_text]
        for link in subpage_links:
            try:
                sub_res = requests.get(link, timeout=timeout, headers={'User-Agent': 'Mozilla/5.0'})
                sub_res.raise_for_status()
                sub_html = sub_res.text
                sub_text = get_visible_text(sub_html)
                texts.append(sub_text)
                time.sleep(0.5)  # be nice to servers!
            except Exception:
                continue
        return "\n".join(texts)
    except Exception:
        return None

def build_investor_comment(company, gpt_reason, gpt_industry):
    # szablon do personalizacji
    template = (
        f"Od pewnego czasu z zainteresowaniem obserwujemy rozwój spółek w branży {gpt_industry}. "
        f"{company} znalazła się w kręgu naszego zainteresowania ze względu na {gpt_reason}, "
        f"które wpisuje się w strategię inwestycyjną CMT Family Office. "
        f"Rozważamy możliwość zaangażowania się poprzez dofinansowanie spółki lub nabycie pakietu mniejszościowego nawiązując partnerską współpracę."
    )
    return template
    
def build_prompt(company, text):
    prompt = (
        f"Jako potencjalny inwestor zainteresowany współpracą z firmą \"{company}\", "
        f"napisz w języku polskim krótką, profesjonalną wypowiedź (2-3 zdania) skierowaną do zarządu tej spółki. "
        f"Podkreśl, że zwracamy uwagę na Państwa kompetencje, innowacyjność oraz unikalne projekty i rozwiązania, "
        f"które dostarczacie swoim klientom biznesowym. Jeśli spółka tworzy technologie lub systemy dla innych firm, "
        f"zaznacz wprost, że są Państwo twórcą rozwiązań, które wspierają rozwój i cyfryzację swoich partnerów z branży, "
        f"ale nie sugeruj, że sami oferujecie te usługi końcowym użytkownikom. "
        f"Unikaj ogólników, pisz zwięźle i rzeczowo, pokazując prawdziwą rolę spółki na rynku B2B lub technologicznym. "
        f"Nie pisz nic poza tą wypowiedzią. "
        f"Poniżej znajduje się opis oraz treść strony:\n\n{text}"
    )
    return prompt

def get_company_industry(scraped_text, client):
    prompt = (
        f"Na podstawie poniższego opisu określ jednym słowem lub krótką frazą, w jakiej branży działa ta spółka. "
        f"Nie pisz nic więcej.\n\n{scraped_text}"
    )
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10
    )
    return response.choices[0].message.content.strip()

def get_company_reason(scraped_text, client):
    prompt = (
        f"Na podstawie poniższego opisu napisz w języku polskim jednym zdaniem, co szczególnie wyróżnia tę spółkę "
        f"i dlaczego mogła przykuć uwagę inwestora. Nie pisz nic poza tym zdaniem.\n\n{scraped_text}"
    )
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100
    )
    return response.choices[0].message.content.strip()

# Potem w głównej pętli:
industry = get_company_industry(scraped_text, client)
reason = get_company_reason(scraped_text, client)
comment = build_investor_comment(company, scraped_text, reason, industry)

def build_full_email(person, opening, compliment, ending):
    first_name = person.split()[0].title()  # tylko pierwsze słowo z dużej litery
    email = (
        f"Szanowny Panie {first_name},\n\n"
        f"{opening.strip()}\n\n"
        f"{compliment.strip()}\n\n"
        f"{ending.strip()}"
    )
    return email

# ---- Streamlit App ----
st.set_page_config(page_title="GenAI Cold Email Generator", layout="wide")
st.title("✉️ GenAI: Personalizowane maile coldmailingowe")

st.sidebar.header("📝 Opcje e-maila")
opening = st.sidebar.text_area("Wstęp (Opening)", value=" ")
ending = st.sidebar.text_area("Zakończenie (Ending)", value="")

st.sidebar.info("API key OpenAI jest pobierany z `.streamlit/secrets.toml`", icon="🔑")

uploaded_file = st.file_uploader("Wgraj plik Excel z kolumnami: Nazwa firmy, Imię i nazwisko, Strona internetowa", type=["xls", "xlsx"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    st.dataframe(df.head())
    if st.button("Generuj maile"):
        openai.api_key = st.secrets["openai_api_key"]
        results = []
        for idx, row in df.iterrows():
            company = str(row.get("Nazwa firmy", "")).strip()
            person = str(row.get("Imię i nazwisko", "")).strip()
            website = str(row.get("Strona internetowa", "")).strip()
            if not (company and person and website):
                continue
            st.info(f"Przetwarzam: {company} ({website})", icon="🔄")
            scraped = scrape_website(website)
            if scraped is None or len(scraped) < 100:
                st.warning(f"❌ Nie udało się pobrać danych z: {website} (pomijam)", icon="⚠️")
                continue
            try:
                compliment = generate_gpt_compliment(company, scraped)
                full_email = build_full_email(person, opening, compliment, ending)
                results.append({
                    **row,
                    "Personalizowany email": full_email
                })
            except Exception as e:
                st.error(f"Błąd generowania AI: {e}")
                continue
            time.sleep(1.1)  # Be polite to OpenAI and websites
        if results:
            result_df = pd.DataFrame(results)
            st.success(f"Wygenerowano {len(result_df)} spersonalizowanych e-maili!")
            st.dataframe(result_df)
            towrite = io.BytesIO()
            result_df.to_excel(towrite, index=False)
            towrite.seek(0)
            st.download_button(
                label="Pobierz wynikowy plik Excel",
                data=towrite,
                file_name="personalizowane_maile.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("Nie udało się wygenerować żadnych e-maili. Sprawdź dane wejściowe.")
