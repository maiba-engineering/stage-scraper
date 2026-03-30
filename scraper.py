"""
scraper.py - Scraper de stages pour ma recherche de stage d'exécution été 2026
Cible : stages opérateur à Paris et Strasbourg
Sources : Welcome to the Jungle + HelloWork (ex-RegionsJob)

Pourquoi pas Indeed ?
→ Indeed change sa structure HTML très souvent et bloque les scrapers
   agressivement. WTTJ a une API interne propre, et HelloWork a un
   HTML stable et bien structuré.

Usage :
    python scraper.py                          # recherche par défaut
    python scraper.py -q "stage logistique"    # autre recherche
    python scraper.py -p 5                     # plus de pages
    python scraper.py -f production usine      # filtrer les résultats
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import argparse
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

# Les villes où je cherche un stage, avec leurs coordonnées GPS
# (utilisées par l'API WTTJ pour filtrer par zone géographique)
VILLES = {
    "Paris": {
        "coords": "48.8566,2.3522",
        "rayon": 20000,  # 20km autour du centre
    },
    "Strasbourg": {
        "coords": "48.5734,7.7521",
        "rayon": 15000,  # 15km
    },
}

# Headers HTTP qui imitent un vrai navigateur Chrome
# Sans ça, les sites détectent qu'on est un script et bloquent les requêtes
# (ils vérifient le User-Agent pour filtrer les bots)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}


# ============================================================
# SCRAPER WELCOME TO THE JUNGLE
# ============================================================
# WTTJ est une app React → le HTML renvoyé par le serveur est quasi vide,
# tout le contenu est chargé dynamiquement par JavaScript.
#
# BeautifulSoup ne peut pas exécuter du JS, donc on aurait besoin de
# Selenium (un navigateur automatisé) pour récupérer le contenu.
#
# MAIS en ouvrant les Chrome DevTools (onglet Network), on voit que
# le JavaScript de WTTJ appelle une API REST interne pour charger
# les offres. On peut appeler cette API directement depuis Python
# → pas besoin de Selenium, c'est plus rapide et plus fiable.
#
# C'est un réflexe important en scraping : toujours vérifier s'il y a
# une API cachée avant de sortir Selenium.
# ============================================================

def scrape_wttj(query, ville, nb_pages=3):
    """
    Récupère les offres de stage depuis l'API interne de WTTJ.

    Paramètres :
        query (str)    : mots-clés de recherche, ex "stage opérateur"
        ville (str)    : nom de la ville, doit être une clé de VILLES
        nb_pages (int) : nombre de pages de résultats à parcourir

    Retourne :
        list[dict] : liste d'offres, chaque offre est un dictionnaire
    """
    offres = []

    # on crée une Session HTTP → ça réutilise la connexion TCP entre les requêtes
    # (plus rapide que de créer une nouvelle connexion à chaque fois)
    session = requests.Session()
    session.headers.update(HEADERS)

    # récupérer les coordonnées GPS de la ville
    config_ville = VILLES.get(ville)
    if not config_ville:
        print(f"  [WTTJ] Ville '{ville}' pas dans la config, skip")
        return []

    for page in range(nb_pages):
        print(f"  [WTTJ {ville}] Page {page + 1}...", end=" ")

        # paramètres de l'API WTTJ
        # trouvés en inspectant les requêtes réseau dans Chrome DevTools
        params = {
            "query": query,                         # mots-clés
            "page": page + 1,                       # numéro de page (commence à 1)
            "per_page": 20,                         # résultats par page
            "contract_type": "internship",          # que les stages
            "aroundLatLng": config_ville["coords"], # coordonnées GPS du centre
            "aroundRadius": config_ville["rayon"],  # rayon en mètres
        }

        try:
            resp = session.get(
                "https://api.welcometothejungle.com/api/v1/organizations/jobs/search",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()  # lève une exception si erreur HTTP (4xx, 5xx)
            data = resp.json()       # parse la réponse JSON
        except Exception as e:
            print(f"erreur: {e}")
            continue

        jobs = data.get("jobs", [])
        print(f"{len(jobs)} offres")

        # page vide = fin des résultats
        if not jobs:
            break

        for job in jobs:
            try:
                org = job.get("organization", {})
                office = job.get("office", {}) or {}

                # construire l'URL de l'offre
                lien = ""
                if org.get("slug") and job.get("slug"):
                    lien = f"https://www.welcometothejungle.com/fr/jobs/{org['slug']}/{job['slug']}"

                # tronquer la description pour garder un CSV lisible
                desc = job.get("description", "") or ""
                if len(desc) > 200:
                    desc = desc[:200] + "..."

                offres.append({
                    "titre": job.get("name", "?"),
                    "entreprise": org.get("name", "?"),
                    "lieu": office.get("city", ville),
                    "description": desc,
                    "lien": lien,
                    "source": "WTTJ",
                })
            except Exception:
                pass

        # pause aléatoire pour pas se faire ban
        time.sleep(random.uniform(1, 2.5))

    return offres


# ============================================================
# SCRAPER HELLOWORK (ex-RegionsJob)
# ============================================================
# HelloWork est un job board français classique.
# Contrairement à WTTJ, le HTML est rendu côté serveur (server-side rendering)
# → le contenu est directement dans le HTML qu'on reçoit.
# → BeautifulSoup peut parser la page sans problème.
#
# Comment j'ai trouvé les bons sélecteurs CSS :
# 1. Aller sur hellowork.com, chercher "stage opérateur Paris"
# 2. Clic droit sur une offre → "Inspecter"
# 3. Remonter dans l'arbre HTML pour trouver le conteneur de la carte
# 4. Noter les classes CSS et attributs data-* utilisés
#
# ⚠️ Les sélecteurs CSS peuvent changer si HelloWork refait son site.
# C'est le problème principal du scraping HTML vs API.
# ============================================================

def scrape_hellowork(query, ville, nb_pages=3):
    """
    Récupère les offres de stage sur HelloWork par parsing HTML.

    Ici on utilise BeautifulSoup pour extraire les données du HTML.
    C'est la méthode "classique" de scraping, contrairement à l'approche
    API utilisée pour WTTJ.
    """
    offres = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(nb_pages):
        print(f"  [HelloWork {ville}] Page {page + 1}...", end=" ")

        url = (
            f"https://www.hellowork.com/fr-fr/emploi/recherche.html"
            f"?k={query.replace(' ', '+')}"
            f"&l={ville}"
            f"&p={page + 1}"
            f"&c=Stage"
        )

        try:
            resp = session.get(url, timeout=15)

            # 429 = "trop de requêtes, calme-toi"
            if resp.status_code == 429:
                print("rate limited, attente 10s...")
                time.sleep(10)
                continue

            resp.raise_for_status()
        except Exception as e:
            print(f"erreur: {e}")
            continue

        # --- parsing HTML avec BeautifulSoup ---
        # on donne le HTML brut à BeautifulSoup qui le transforme
        # en un arbre navigable avec des méthodes pratiques :
        #   soup.find("tag", class_="xxx")     → premier élément qui matche
        #   soup.find_all("tag", class_="xxx") → tous les éléments
        #   element.get_text(strip=True)        → texte visible sans espaces
        #   element.get("href")                 → valeur d'un attribut
        soup = BeautifulSoup(resp.text, "html.parser")

        # trouver les cartes d'offres
        # HelloWork utilise des <li> avec un attribut data-cy pour le testing
        cards = soup.find_all("li", attrs={"data-cy": True})
        if not cards:
            # fallback si la structure a changé
            cards = soup.find_all("div", class_="offer")

        print(f"{len(cards)} offres")

        if not cards:
            break

        for card in cards:
            try:
                # titre : dans un <h3> ou <h2>
                titre_tag = card.find("h3") or card.find("h2")
                if not titre_tag:
                    continue
                titre = titre_tag.get_text(strip=True)

                # lien : dans le <a> le plus proche
                a_tag = card.find("a", href=True)
                lien = ""
                if a_tag:
                    href = a_tag["href"]
                    if href.startswith("http"):
                        lien = href
                    else:
                        lien = "https://www.hellowork.com" + href

                # entreprise
                ent_tag = card.find(attrs={"data-cy": "company"})
                if not ent_tag:
                    ent_tag = card.find("span", class_=lambda c: c and "company" in c.lower())
                entreprise = ent_tag.get_text(strip=True) if ent_tag else "?"

                # lieu
                loc_tag = card.find(attrs={"data-cy": "location"})
                if not loc_tag:
                    loc_tag = card.find("span", class_=lambda c: c and "location" in c.lower())
                lieu = loc_tag.get_text(strip=True) if loc_tag else ville

                # description
                desc_tag = card.find("p")
                description = desc_tag.get_text(strip=True) if desc_tag else ""
                if len(description) > 200:
                    description = description[:200] + "..."

                offres.append({
                    "titre": titre,
                    "entreprise": entreprise,
                    "lieu": lieu,
                    "description": description,
                    "lien": lien,
                    "source": "HelloWork",
                })
            except Exception:
                pass

        time.sleep(random.uniform(1.5, 3))

    return offres


# ============================================================
# POST-TRAITEMENT
# ============================================================

def dedup(offres):
    """
    Supprime les doublons entre les sources.
    Même titre + même entreprise = même offre → on en garde qu'une.
    """
    seen = set()
    uniques = []
    for o in offres:
        key = (o["titre"].lower().strip(), o["entreprise"].lower().strip())
        if key not in seen:
            seen.add(key)
            uniques.append(o)
    nb_doublons = len(offres) - len(uniques)
    if nb_doublons:
        print(f"\n{nb_doublons} doublon(s) supprimé(s)")
    return uniques


def filtrer(offres, mots_cles):
    """
    Garde que les offres qui contiennent au moins un des mots-clés
    dans le titre ou la description.
    """
    if not mots_cles:
        return offres
    result = []
    for o in offres:
        texte = f"{o['titre']} {o['description']}".lower()
        if any(m.lower() in texte for m in mots_cles):
            result.append(o)
    print(f"Filtre {mots_cles}: {len(result)}/{len(offres)} offres gardées")
    return result


def exporter_csv(offres, query):
    """
    Exporte les offres en CSV dans output/.
    utf-8-sig = UTF-8 avec BOM pour que Excel gère les accents.
    """
    if not offres:
        print("Rien à exporter :(")
        return

    df = pd.DataFrame(offres)
    df = df[["titre", "entreprise", "lieu", "source", "lien", "description"]]

    date = datetime.now().strftime("%Y-%m-%d")
    slug = query.replace(" ", "-")[:30]
    path = Path("output") / f"stages_{date}_{slug}.csv"
    path.parent.mkdir(exist_ok=True)

    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n{len(df)} offres exportées -> {path}")


# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper de stages - Paris & Strasbourg")
    parser.add_argument("-q", "--query", default="stage opérateur",
                        help="Mots-clés (défaut: 'stage opérateur')")
    parser.add_argument("-p", "--pages", type=int, default=3,
                        help="Pages par source par ville (défaut: 3)")
    parser.add_argument("-f", "--filtre", nargs="*", default=[],
                        help="Mots-clés pour filtrer après scraping")
    parser.add_argument("-s", "--sources", nargs="*", default=["wttj", "hellowork"],
                        choices=["wttj", "hellowork"],
                        help="Sources à utiliser (défaut: wttj hellowork)")
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"Recherche: '{args.query}'")
    print(f"Villes: Paris, Strasbourg")
    print(f"Sources: {', '.join(args.sources)} | Pages: {args.pages}")
    print(f"{'='*50}")

    toutes_offres = []

    # on boucle sur chaque ville × chaque source
    for ville in VILLES:
        print(f"\n📍 {ville}")
        print("-" * 30)

        if "wttj" in args.sources:
            toutes_offres += scrape_wttj(args.query, ville, args.pages)

        if "hellowork" in args.sources:
            toutes_offres += scrape_hellowork(args.query, ville, args.pages)

    if not toutes_offres:
        print("\nAucune offre trouvée, essaie d'autres mots-clés")
    else:
        print(f"\nTotal brut: {len(toutes_offres)} offres")
        toutes_offres = dedup(toutes_offres)

        if args.filtre:
            toutes_offres = filtrer(toutes_offres, args.filtre)

        exporter_csv(toutes_offres, args.query)

        # aperçu
        print(f"\nAperçu:")
        print("-" * 50)
        for i, o in enumerate(toutes_offres[:8], 1):
            print(f"{i}. {o['titre']}")
            print(f"   {o['entreprise']} - {o['lieu']} [{o['source']}]")
            if o["lien"]:
                print(f"   {o['lien'][:70]}")
            print()
