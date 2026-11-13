#!/usr/bin/env python3
"""Met à jour docs/data.json avec les produits fournisseurs de CJ Dropshipping.

Utilisation :
    python fetch.py               -> met à jour docs/data.json
    python fetch.py --categories  -> affiche la liste des catégories CJ (avec leurs identifiants)

La clé API est lue dans la variable d'environnement CJ_API_KEY (jamais dans un fichier).
Sans clé, le script génère des données de DÉMONSTRATION clairement signalées sur le site.

API officielle utilisée (doc : https://developers.cjdropshipping.com) :
    POST /authentication/getAccessToken      clé API -> access token (valable 180 jours)
    POST /authentication/refreshAccessToken  renouvelle le token
    GET  /product/getCategory                arbre des catégories (gratuit en points)
    GET  /product/listV2                     recherche de produits (50 points / appel)
    POST /product/productDetail/query        note, avis, commandes, sous-catégorie, variante (0 point)
    POST /logistic/freightCalculate          délai et prix de livraison par mode de transport (10 points)
Limites (compte gratuit) : 1 requête / seconde, 50 000 points / jour.
"""
import base64, csv, hashlib, json, math, os, random, re, socket, sys, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Constantes modifiables
# ---------------------------------------------------------------------------
VAT = 1.20             # TVA 20 % : prix Amazon TTC -> HT
REFERRAL = 0.15        # commission Amazon (~15 % pour la plupart des catégories)
FBA_FEE = 3.50         # frais logistiques FBA moyens par unité (€)
SHIP = 0.80            # transport fournisseur -> entrepôt Amazon par unité (€)
TAUX_USD_EUR = 0.86    # taux de secours si le taux du jour (BCE) est indisponible
LIVRAISON_EUR_PAR_JOUR = 0.25   # livraison : 1 jour de délai en plus "vaut" 0,25 € (choix du compromis)

BASE = "https://developers.cjdropshipping.com/api2.0/v1"
INTERVALLE = 1.1       # secondes minimum entre deux appels (limite : 1 / seconde)
TIMEOUT = 30           # secondes avant d'abandonner une requête
ESSAIS = 4             # nombre de tentatives par appel en cas d'erreur temporaire
COUT_POINTS = {"/product/listV2": 50, "/logistic/freightCalculate": 10}   # selon la doc ; non listé = 0

ICI = os.path.dirname(os.path.abspath(__file__))
F_CONFIG = os.path.join(ICI, "config.json")
F_AMAZON = os.path.join(ICI, "amazon_prices.csv")
F_SORTIE = os.path.join(ICI, "docs", "data.json")


# ---------------------------------------------------------------------------
# Client API CJ : token, rythme, erreurs, retries
# ---------------------------------------------------------------------------
class ErreurCJ(Exception):
    pass


class QuotaEpuise(ErreurCJ):
    """Plus de points (journée ou budget de cette exécution) : on arrête proprement."""


class CJ:
    def __init__(self, cle, budget):
        self.cle = cle
        self.budget = budget            # points max pour cette exécution
        self.depense = 0                # points dépensés pendant cette exécution
        self.restant_jour = None        # points restants aujourd'hui (renvoyé par CJ)
        self.token = None
        self.token_expire = None
        self.refresh = None
        self.dernier_appel = 0.0

    # -- token ---------------------------------------------------------------
    def _enregistre_token(self, d):
        self.token = d["accessToken"]
        self.refresh = d.get("refreshToken") or self.refresh
        try:
            self.token_expire = datetime.fromisoformat(d["accessTokenExpiryDate"])
        except (KeyError, TypeError, ValueError):
            self.token_expire = datetime.now(timezone.utc) + timedelta(days=1)

    def _token_valide(self):
        if not self.token or not self.token_expire:
            return False
        return datetime.now(timezone.utc) < self.token_expire - timedelta(hours=1)

    def jeton(self, forcer=False):
        if self._token_valide() and not forcer:
            return self.token
        if self.refresh and not forcer:
            try:
                self._enregistre_token(self._appel("POST", "/authentication/refreshAccessToken",
                                                   corps={"refreshToken": self.refresh}, auth=False))
                return self.token
            except ErreurCJ as e:
                print("  refresh du token impossible, nouvelle demande :", e)
        self._enregistre_token(self._appel("POST", "/authentication/getAccessToken",
                                           corps={"apiKey": self.cle}, auth=False))
        return self.token

    # -- appel générique -----------------------------------------------------
    def _attendre(self):
        reste = INTERVALLE - (time.monotonic() - self.dernier_appel)
        if reste > 0:
            time.sleep(reste)
        self.dernier_appel = time.monotonic()

    def _appel(self, methode, chemin, params=None, corps=None, auth=True):
        cout = COUT_POINTS.get(chemin, 0)
        if cout and self.depense + cout > self.budget:
            raise QuotaEpuise(f"budget de {self.budget} points atteint pour cette exécution")
        if auth and self.restant_jour is not None and self.restant_jour < max(cout, 1):
            raise QuotaEpuise("plus assez de points CJ aujourd'hui")

        url = BASE + chemin
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        data = json.dumps(corps).encode() if corps is not None else None
        token_renouvele = False

        for essai in range(1, ESSAIS + 1):
            entetes = {"Content-Type": "application/json", "Accept": "application/json"}
            if auth:
                entetes["CJ-Access-Token"] = self.jeton()
            self._attendre()
            pause = min(2 ** essai, 30)  # 2, 4, 8, 16 s
            try:
                req = urllib.request.Request(url, data=data, method=methode, headers=entetes)
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    rep = json.load(r)
            except urllib.error.HTTPError as e:
                try:
                    rep = json.loads(e.read().decode("utf-8", "replace"))
                except ValueError:
                    rep = None
                if rep is None:
                    if e.code == 429 or e.code >= 500:
                        print(f"  HTTP {e.code} sur {chemin}, nouvel essai dans {pause} s")
                        time.sleep(pause)
                        continue
                    raise ErreurCJ(f"HTTP {e.code} sur {chemin}")
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError) as e:
                print(f"  erreur réseau sur {chemin} ({e}), nouvel essai dans {pause} s")
                time.sleep(pause)
                continue

            if not isinstance(rep, dict):
                raise ErreurCJ(f"réponse inattendue de {chemin}")
            info = rep.get("pointsInfo") or {}
            if isinstance(info.get("remaining"), (int, float)):
                self.restant_jour = info["remaining"]
            code, msg = rep.get("code"), rep.get("message") or ""

            if code == 200:
                self.depense += cout
                return rep.get("data")
            if code in (429, 1600201, 16900500) or "points" in msg.lower():
                raise QuotaEpuise(f"quota CJ épuisé : {msg}")
            if code == 1600200:                      # trop de requêtes par seconde
                print(f"  limite de débit atteinte, pause de {pause} s")
                time.sleep(pause)
                continue
            if code in (1600001, 1600002) and auth and not token_renouvele:
                token_renouvele = True               # token refusé : on en redemande un
                self.token = None
                self.jeton(forcer=True)
                continue
            if code in (1600001, 1601000) and not auth:
                raise ErreurCJ("clé API refusée par CJ (vérifie CJ_API_KEY)")
            raise ErreurCJ(f"{chemin} : code {code} {msg}")
        raise ErreurCJ(f"{chemin} : échec après {ESSAIS} essais")

    # -- endpoints -----------------------------------------------------------
    def categories(self):
        return self._appel("GET", "/product/getCategory") or []

    def recherche(self, mot_cle=None, categorie_id=None, taille=20, page=1, tri=None,
                  pays=None, prix_min=None, prix_max=None):
        data = self._appel("GET", "/product/listV2", params={
            "keyWord": mot_cle, "categoryId": categorie_id, "page": page,
            "size": max(1, min(int(taille), 100)), "orderBy": tri, "countryCode": pays,
            "startSellPrice": prix_min, "endSellPrice": prix_max}) or {}
        produits = []
        for bloc in data.get("content") or []:
            produits.extend(bloc.get("productList") or [])
        return produits

    def detail(self, pid):
        return self._appel("POST", "/product/productDetail/query", corps={"id": pid}) or {}

    def frais_port(self, vid, depart="CN", arrivee="FR"):
        """Modes de livraison pour 1 unité : [{logisticName, logisticAging, logisticPrice (USD)}, …]."""
        return self._appel("POST", "/logistic/freightCalculate", corps={
            "startCountryCode": depart, "endCountryCode": arrivee,
            "products": [{"quantity": 1, "vid": vid}]}) or []


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------
def nombre(v):
    """Convertit '12.5', 12.5 ou '3.10 -- 7.80' en float (le plus petit nombre). None sinon."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    trouves = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(v).replace(",", "."))]
    return min(trouves) if trouves else None


def entier(v):
    n = nombre(v)
    return int(n) if n is not None else None


def taux_usd_eur():
    """Taux du jour publié par la Banque centrale européenne (API publique et gratuite)."""
    try:
        url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
        with urllib.request.urlopen(url, timeout=15) as r:
            xml = r.read().decode("utf-8", "replace")
        m = re.search(r"currency=['\"]USD['\"]\s+rate=['\"]([\d.]+)", xml)
        if m:
            return round(1 / float(m.group(1)), 4)
    except Exception as e:
        print("  taux BCE indisponible, taux de secours utilisé :", e)
    return TAUX_USD_EUR


def lire_json(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def prix_amazon():
    """amazon_prices.csv : id_cj,prix_amazon (TTC en €). Les lignes qui commencent par # sont ignorées."""
    prix = {}
    try:
        with open(F_AMAZON, newline="", encoding="utf-8-sig") as f:
            lignes = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
        for row in csv.DictReader(lignes):
            pid = (row.get("id_cj") or "").strip()
            p = nombre(row.get("prix_amazon"))
            if pid and p:
                prix[pid] = {"prix": p, "asin": (row.get("asin") or "").strip() or None}
    except OSError:
        pass
    return prix


# ---------------------------------------------------------------------------
# Transformation d'un produit CJ en ligne pour le site
# ---------------------------------------------------------------------------
def produit_depuis_cj(p, categorie, taux, modele_lien):
    pid = str(p.get("id") or "").strip()
    if not pid:
        return None
    # Prix : prix remisé ("nowPrice") s'il existe, sinon prix de vente ; pour une fourchette, le minimum.
    candidats = [nombre(p.get("nowPrice")), nombre(p.get("sellPrice"))]
    prix_usd = next((x for x in candidats if x and x > 0), None)
    if not prix_usd:
        return None
    vente = str(p.get("sellPrice") or "")
    return {
        "id": pid,
        "nom": (p.get("nameEn") or "").strip() or "Produit sans nom",
        "categorie": categorie,
        "sous_categorie": p.get("threeCategoryName") or p.get("twoCategoryName") or None,
        "prix_usd": round(prix_usd, 2),
        "prix": round(prix_usd * taux, 2),
        "prix_variable": "-" in vente.replace(" ", "")[1:] if vente else False,
        "image": p.get("bigImage") or None,
        "lien": modele_lien.replace("{id}", urllib.parse.quote(pid)),
        "annonces": entier(p.get("listedNum")),       # nb de boutiques qui vendent ce produit
        "stock": entier(p.get("warehouseInventoryNum")),
        "delai": (str(p.get("deliveryCycle")).strip() or None) if p.get("deliveryCycle") else None,
        "livraison_gratuite": p.get("addMarkStatus") in (1, "1"),
        "note": None, "nb_avis": None, "commandes": None, "details_maj": None, "details_v": None,
        "vid": None, "livraison": None, "livraison_maj": None,
    }


# Champs remplis par l'appel "détail" et conservés d'une exécution à l'autre.
# Augmenter DETAILS_VERSION force la récupération de nouveaux détails pour tous les produits.
CHAMPS_DETAIL = ("note", "nb_avis", "commandes", "sous_categorie", "vid", "details_maj", "details_v")
DETAILS_VERSION = 3


def dernier_niveau(chemin):
    """'Niveau 1 / Niveau 2 / Niveau 3' ou 'A > B > C' -> dernier niveau."""
    if not chemin:
        return None
    return re.split(r"\s*[/>]\s*", str(chemin).strip())[-1].strip() or None


def appliquer_detail(prod, d):
    note = nombre(d.get("score")) or nombre(d.get("comprehensiveScore"))
    prod["note"] = round(note, 1) if note and 0 < note <= 5 else None
    prod["nb_avis"] = entier(d.get("commentCount"))
    # Ventes : "soldOut" (ventes 90 j) est documenté mais vide en pratique ; "orderCount"
    # (nombre de commandes passées chez CJ pour ce produit) est rempli.
    prod["commandes"] = entier(d.get("orderCount"))
    if d.get("soldOut") is not None:
        prod["commandes"] = max(prod["commandes"] or 0, entier(d.get("soldOut")) or 0)
    if d.get("category"):
        prod["sous_categorie"] = dernier_niveau(d["category"])
    # Identifiant de la première variante (nécessaire pour calculer les frais de port).
    variantes = d.get("stanProducts") or []
    if variantes and isinstance(variantes[0], dict) and variantes[0].get("id"):
        prod["vid"] = str(variantes[0]["id"])
    prod["details_maj"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prod["details_v"] = DETAILS_VERSION


def resumer_livraison(options, taux, pays):
    """Choisit le meilleur compromis prix/délai et, s'il existe, un mode plus rapide.
    logisticAging = délai en jours ("7-12"). Prix en USD : totalPostageFee (port + frais annexes)
    quand il est fourni, sinon logisticPrice.
    Compromis = prix + LIVRAISON_EUR_PAR_JOUR x délai maximum : évite de retenir un mode
    à peine moins cher mais beaucoup plus lent (ex. 12 à 50 jours)."""
    modes = []
    for o in options or []:
        total, base = nombre(o.get("totalPostageFee")), nombre(o.get("logisticPrice"))
        prix = total if total and total > 0 else base
        jours = [int(float(x)) for x in re.findall(r"\d+(?:\.\d+)?", str(o.get("logisticAging") or ""))]
        if prix is None or not jours:
            continue
        mini, maxi = min(jours), max(jours)
        modes.append({"mode": str(o.get("logisticName") or "").strip() or "Standard",
                      "delai": f"{mini}-{maxi}" if mini != maxi else str(mini),
                      "jours_min": mini, "jours_max": maxi, "prix": round(prix * taux, 2)})
    if not modes:
        return {"pays": pays, "indisponible": True}
    eco = min(modes, key=lambda m: (m["prix"] + LIVRAISON_EUR_PAR_JOUR * m["jours_max"], m["prix"]))
    rapide = min(modes, key=lambda m: (m["jours_max"], m["prix"]))
    return {"pays": pays, **eco, "nb_modes": len(modes),
            "rapide": rapide if rapide["jours_max"] < eco["jours_max"] else None}


# ---------------------------------------------------------------------------
# Score qualité/prix et marge Amazon
# ---------------------------------------------------------------------------
def calculer_scores(produits, poids):
    """Score de 0 à 100, calculé à l'intérieur de chaque catégorie du site :

      prix   = prix le plus bas de la catégorie / prix du produit
               -> 1 pour le moins cher, 0,5 pour un produit deux fois plus cher.
      ventes = moyenne de deux indicateurs de popularité, chacun ramené entre 0 et 1 :
                 log(1 + commandes) / log(1 + max des commandes de la catégorie)
                 log(1 + boutiques) / log(1 + max des boutiques de la catégorie)
               (commandes = commandes passées chez CJ ; boutiques = nb de boutiques qui le vendent).
               Si les commandes sont inconnues, seul le nombre de boutiques compte.
               Le logarithme évite qu'un best-seller écrase tous les autres.
      note   = note CJ / 5 (seulement si CJ fournit une note pour ce produit).

      score = 100 x moyenne pondérée de ces trois valeurs (poids dans config.json).
      Si la note est inconnue, son poids est réparti sur les deux autres.
      Produit en rupture de stock (stock = 0) : score divisé par 2.
    """
    par_cat = {}
    for p in produits:
        par_cat.setdefault(p["categorie"], []).append(p)
    for groupe in par_cat.values():
        prix_min = min(p["prix"] for p in groupe)
        max_cmd = max((p.get("commandes") or 0) for p in groupe)
        max_bout = max((p.get("annonces") or 0) for p in groupe)
        norm = lambda v, m: math.log1p(v) / math.log1p(m) if m > 0 else 0
        for p in groupe:
            pop = [norm(p.get("annonces") or 0, max_bout)]
            if p.get("commandes") is not None:
                pop.append(norm(p["commandes"], max_cmd))
            parts = [(poids.get("prix", 0.5), prix_min / p["prix"])]
            parts.append((poids.get("ventes", 0.3), sum(pop) / len(pop)))
            if p["note"]:
                parts.append((poids.get("note", 0.2), p["note"] / 5))
            total = sum(w for w, _ in parts) or 1
            s = 100 * sum(w * v for w, v in parts) / total
            if p["stock"] == 0:
                s /= 2
            p["score"] = round(s)


def calculer_marges(produits, amazon):
    for p in produits:
        a = amazon.get(p["id"])
        p["prix_amazon"] = p["profit"] = p["roi"] = None
        p["asin"] = None
        if not a:
            continue
        cout = p["prix"] + SHIP
        net = a["prix"] / VAT - a["prix"] * REFERRAL - FBA_FEE
        profit = net - cout
        p["prix_amazon"] = round(a["prix"], 2)
        p["asin"] = a["asin"]
        p["profit"] = round(profit, 2)
        p["roi"] = round(profit / cout * 100, 1)


# ---------------------------------------------------------------------------
# Mode réel
# ---------------------------------------------------------------------------
def mode_reel(cle, cfg, ancien):
    api = CJ(cle, cfg.get("budget_points_par_execution", 2500))
    taux = taux_usd_eur()
    modele_lien = cfg.get("lien_produit") or "https://cjdropshipping.com/product/-p-{id}.html"
    anciens = {p["id"]: p for p in ancien.get("produits", [])} if not ancien.get("demo") else {}

    print("Connexion à CJ…")
    api.jeton()

    produits, vus, echecs = [], set(), []
    recherches = cfg.get("recherches", [])
    for idx, r in enumerate(recherches):
        cat = r.get("categorie") or "Divers"
        libelle = f"{cat} / {r.get('mot_cle') or r.get('categoryId')}"
        try:
            liste = api.recherche(mot_cle=r.get("mot_cle"), categorie_id=r.get("categoryId"),
                                  taille=cfg.get("produits_par_recherche", 20), tri=cfg.get("tri_cj"),
                                  pays=cfg.get("pays_stock") or None,
                                  prix_min=cfg.get("prix_min_usd"), prix_max=cfg.get("prix_max_usd"))
        except QuotaEpuise as e:
            print("Arrêt des recherches :", e)
            echecs.extend(x.get("categorie") or "Divers" for x in recherches[idx:])
            break
        except ErreurCJ as e:
            print(f"  échec de la recherche {libelle} : {e}")
            echecs.append(cat)
            continue
        n = 0
        for brut in liste:
            prod = produit_depuis_cj(brut, cat, taux, modele_lien)
            if prod and prod["id"] not in vus:
                vus.add(prod["id"]); produits.append(prod); n += 1
        print(f"  {libelle} : {n} produits")

    # Recherche en échec : on garde les produits de l'exécution précédente pour cette catégorie.
    for cat in set(echecs):
        for old in anciens.values():
            if old.get("categorie") == cat and old["id"] not in vus:
                vus.add(old["id"]); produits.append(old)

    if not produits:
        raise ErreurCJ("aucun produit récupéré : docs/data.json n'est pas modifié")

    # Détails (note, avis, ventes 90 j) : réutilisés tant qu'ils ont moins de N heures.
    det = cfg.get("details") or {}
    if det.get("actif", True):
        limite = datetime.now(timezone.utc) - timedelta(hours=det.get("rafraichir_apres_heures", 24))
        a_faire = []
        for p in produits:
            old = anciens.get(p["id"]) or {}
            if old.get("details_v") == DETAILS_VERSION:
                for k in CHAMPS_DETAIL:
                    if p.get(k) is None and old.get(k) is not None:
                        p[k] = old[k]
            try:
                frais = bool(p.get("details_maj")) and datetime.fromisoformat(p["details_maj"]) > limite
            except ValueError:
                frais = False
            if not frais:
                a_faire.append(p)
        a_faire = a_faire[: det.get("max_par_execution", 200)]
        print(f"Détails produits : {len(a_faire)} à récupérer")
        for p in a_faire:
            try:
                appliquer_detail(p, api.detail(p["id"]))
            except QuotaEpuise as e:
                print("Arrêt des détails :", e); break
            except ErreurCJ as e:
                print(f"  détail {p['id']} indisponible : {e}")

    # Livraison (délai + frais de port) : 10 points par produit, réutilisée pendant N heures.
    liv = cfg.get("livraison") or {}
    if liv.get("actif", True):
        pays, depart = (liv.get("pays") or "FR").upper(), (liv.get("depart") or "CN").upper()
        limite = datetime.now(timezone.utc) - timedelta(hours=liv.get("rafraichir_apres_heures", 24))
        a_faire = []
        for p in produits:
            old = anciens.get(p["id"]) or {}
            if p.get("livraison") is None and (old.get("livraison") or {}).get("pays") == pays:
                p["livraison"], p["livraison_maj"] = old["livraison"], old.get("livraison_maj")
            try:
                frais = bool(p.get("livraison_maj")) and datetime.fromisoformat(p["livraison_maj"]) > limite
            except ValueError:
                frais = False
            if not frais:
                a_faire.append(p)
        a_faire = a_faire[: liv.get("max_par_execution", 250)]
        print(f"Livraison {depart} -> {pays} : {len(a_faire)} produits à calculer")
        for p in a_faire:
            try:
                if not p.get("vid"):
                    appliquer_detail(p, api.detail(p["id"]))
                if not p.get("vid"):
                    continue
                p["livraison"] = resumer_livraison(api.frais_port(p["vid"], depart, pays), taux, pays)
                p["livraison_maj"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            except QuotaEpuise as e:
                print("Arrêt du calcul de livraison :", e); break
            except ErreurCJ as e:
                print(f"  livraison {p['id']} indisponible : {e}")
                p["livraison"] = {"pays": pays, "indisponible": True}
                p["livraison_maj"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"Points CJ utilisés (estimation) : {api.depense}"
          + (f", restants aujourd'hui : {api.restant_jour}" if api.restant_jour is not None else ""))
    return produits, taux


# ---------------------------------------------------------------------------
# Mode démo (aucune clé) : données fictives, toujours les mêmes
# ---------------------------------------------------------------------------
NOMS_DEMO = ["Modèle compact", "Modèle pliable", "Lot de 2", "Version premium", "Format voyage",
             "Édition silicone", "Modèle rechargeable", "Kit complet", "Version inox", "Mini format",
             "Modèle XL", "Version bambou"]


def demo_livraison(rnd):
    mini = rnd.choice([5, 7, 8, 10]); maxi = mini + rnd.choice([3, 5, 7])
    eco = {"mode": "Démo Standard", "delai": f"{mini}-{maxi}", "jours_min": mini, "jours_max": maxi,
           "prix": round(rnd.uniform(1.5, 5), 2)}
    rapide = {"mode": "Démo Express", "delai": "3-6", "jours_min": 3, "jours_max": 6,
              "prix": round(eco["prix"] + rnd.uniform(3, 9), 2)} if rnd.random() < .6 else None
    return {"pays": "FR", **eco, "nb_modes": 2 if rapide else 1, "rapide": rapide}


def mode_demo(cfg):
    rnd = random.Random(42)   # graine fixe : les données démo ne changent pas d'une exécution à l'autre
    produits = []
    for i, r in enumerate(cfg.get("recherches", [])):
        cat = r.get("categorie") or "Divers"
        sujet = (r.get("mot_cle") or "produit").capitalize()
        for j in range(min(int(cfg.get("produits_par_recherche", 20)), 8)):
            pid = f"DEMO-{i:02d}{j:02d}"
            prix_usd = round(rnd.uniform(1.2, 18), 2)
            avis = rnd.choice([0, 0, rnd.randint(3, 40), rnd.randint(40, 900)])
            produits.append({
                "id": pid, "nom": f"[DÉMO] {sujet} – {NOMS_DEMO[j % len(NOMS_DEMO)]}",
                "categorie": cat, "sous_categorie": None,
                "prix_usd": prix_usd, "prix": round(prix_usd * TAUX_USD_EUR, 2),
                "prix_variable": rnd.random() < 0.3, "image": None,
                "lien": "https://cjdropshipping.com/",
                "annonces": rnd.randint(0, 3000), "stock": rnd.choice([0, rnd.randint(20, 9000), rnd.randint(20, 9000)]),
                "delai": rnd.choice(["1-3", "3-5", "5-8", "7-12"]), "livraison_gratuite": rnd.random() < 0.3,
                "note": round(rnd.uniform(3.2, 5), 1) if avis else None, "nb_avis": avis or None,
                "commandes": rnd.randint(0, 2500), "details_maj": None,
                "livraison": demo_livraison(rnd),
            })
    return produits, TAUX_USD_EUR


# ---------------------------------------------------------------------------
def afficher_categories(cle):
    api = CJ(cle, budget=0)
    for n1 in api.categories():
        print(n1.get("categoryFirstName"))
        for n2 in n1.get("categoryFirstList") or []:
            print("   ", n2.get("categorySecondName"))
            for n3 in n2.get("categorySecondList") or []:
                print(f"        {n3.get('categoryName')}  ->  categoryId: {n3.get('categoryId')}")


# ---------------------------------------------------------------------------
# Accès protégé : docs/data.json est chiffré avec l'identifiant + mot de passe du site
# ---------------------------------------------------------------------------
# Les identifiants sont lus dans SITE_LOGIN et SITE_PASSWORD (variables d'environnement /
# secrets GitHub), jamais dans un fichier. Chiffrement AES-256-GCM ; la clé est dérivée de
# "identifiant:mot de passe" par PBKDF2-SHA256 (600 000 tours, recommandation OWASP), ce qui
# rend chaque essai de mot de passe lent. Le site refait exactement le même calcul dans le
# navigateur (WebCrypto) pour déchiffrer après connexion.
KDF_ITERATIONS = 600_000
AAD = b"sourcing-v1"


def b64(b):
    return base64.b64encode(b).decode("ascii")


def b64d(s):
    return base64.b64decode(s)


def identifiants():
    login = (os.environ.get("SITE_LOGIN") or "").strip().lower()
    mdp = os.environ.get("SITE_PASSWORD") or ""
    return (login, mdp) if login and mdp else None


def _cle(ids, sel, iterations):
    return hashlib.pbkdf2_hmac("sha256", f"{ids[0]}:{ids[1]}".encode("utf-8"), sel, iterations, dklen=32)


def chiffrer(donnees, ids, sel=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    sel, iv = sel or os.urandom(16), os.urandom(12)
    brut = json.dumps(donnees, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = AESGCM(_cle(ids, sel, KDF_ITERATIONS)).encrypt(iv, brut, AAD)
    # Seule la date de mise à jour reste lisible (pour l'écran d'accueil).
    return {"chiffre": True, "v": 1, "kdf": "PBKDF2-SHA256", "iter": KDF_ITERATIONS,
            "sel": b64(sel), "iv": b64(iv), "donnees": b64(ct), "maj": donnees["maj"]}


def dechiffrer(fichier, ids):
    """Données en clair, ou None si les identifiants ne correspondent pas."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        cle = _cle(ids, b64d(fichier["sel"]), int(fichier.get("iter", KDF_ITERATIONS)))
        return json.loads(AESGCM(cle).decrypt(b64d(fichier["iv"]), b64d(fichier["donnees"]), AAD))
    except Exception:
        return None


def main():
    cle = (os.environ.get("CJ_API_KEY") or "").strip()
    if "--categories" in sys.argv:
        if not cle:
            sys.exit("Définis d'abord la variable CJ_API_KEY (voir README).")
        afficher_categories(cle)
        return

    cfg = lire_json(F_CONFIG, None)
    if not cfg:
        sys.exit("config.json introuvable ou invalide (vérifie les virgules et guillemets).")

    ids = identifiants()
    if cle and cfg.get("protection", True) and not ids:
        sys.exit("ERREUR : la protection par mot de passe est activée mais SITE_LOGIN / SITE_PASSWORD "
                 "sont absents. Rien n'est écrit, pour ne pas publier les données en clair (voir README).")

    # Ancien fichier : sert de cache (détails, livraison) et à détecter les changements.
    fichier = lire_json(F_SORTIE, {})
    sel = None
    if fichier.get("chiffre"):
        ancien = dechiffrer(fichier, ids) if ids else None
        if ancien is None:
            print("Ancien data.json chiffré illisible (identifiants changés ?) : cache ignoré.")
            ancien = {}
        else:
            sel = b64d(fichier["sel"])   # même sel : les sessions déjà ouvertes restent valides
    else:
        ancien = fichier

    if cle:
        try:
            produits, taux = mode_reel(cle, cfg, ancien)
        except ErreurCJ as e:
            sys.exit(f"ERREUR : {e}")
    else:
        print("CJ_API_KEY absente : génération de données de DÉMONSTRATION.")
        produits, taux = mode_demo(cfg)

    for p in produits:
        if p.get("sous_categorie"):
            p["sous_categorie"] = dernier_niveau(p["sous_categorie"])
    calculer_scores(produits, cfg.get("poids_score") or {})
    calculer_marges(produits, prix_amazon())
    produits.sort(key=lambda p: p["score"], reverse=True)

    # N'écrit le fichier que si les produits ont changé (évite un commit inutile chaque heure).
    if (ancien.get("produits") == produits and ancien.get("demo") == (not cle)
            and bool(fichier.get("chiffre")) == bool(ids)):
        print(f"{len(produits)} produits, aucun changement : docs/data.json non modifié.")
        return
    categories = list(dict.fromkeys(r.get("categorie") or "Divers" for r in cfg.get("recherches", [])))
    sortie = {
        "maj": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": not cle, "devise": "EUR", "taux_usd_eur": taux,
        "frais": {"tva": VAT, "commission": REFERRAL, "fba": FBA_FEE, "transport": SHIP},
        "livraison": {"depart": ((cfg.get("livraison") or {}).get("depart") or "CN").upper(),
                      "pays": ((cfg.get("livraison") or {}).get("pays") or "FR").upper()},
        "categories": categories, "produits": produits,
    }
    os.makedirs(os.path.dirname(F_SORTIE), exist_ok=True)
    tmp = F_SORTIE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if ids:
            json.dump(chiffrer(sortie, ids, sel), f)
        else:
            json.dump(sortie, f, ensure_ascii=False, indent=1)
    os.replace(tmp, F_SORTIE)
    print(f"{len(produits)} produits écrits dans docs/data.json" + (" (chiffré)" if ids else ""))


if __name__ == "__main__":
    main()
