# Sourcing fournisseurs (CJ Dropshipping)

Un site simple qui affiche, par catégorie, les produits fournisseurs **CJ Dropshipping** les moins chers avec le meilleur rapport qualité/prix, avec des filtres et un lien vers chaque produit.
Les données sont récupérées via l'**API officielle de CJ** (pas de scraping) et se mettent à jour **toutes les heures** grâce à GitHub.

---

## Les fichiers

| Fichier | À quoi il sert |
|---|---|
| `config.json` | **Tes réglages** : catégories, mots-clés, nombre de produits, poids du score… |
| `amazon_prices.csv` | Facultatif : prix Amazon.fr que tu saisis à la main pour calculer profit et ROI |
| `fetch.py` | Le programme qui interroge l'API CJ et écrit `docs/data.json` |
| `docs/index.html` | Le site (une seule page) |
| `docs/data.json` | Les produits (généré automatiquement, ne pas modifier à la main) |
| `.github/workflows/update.yml` | La mise à jour automatique toutes les heures sur GitHub |
| `lancer-site.bat`, `serve.ps1` | Pour ouvrir le site sur ton PC sans rien installer |

`suppliers.csv` n'est plus utilisé : tu peux le supprimer.

---

## 1. Voir le site tout de suite (mode démo)

Sans clé CJ, le site montre des **produits fictifs** avec un bandeau jaune « Mode démonstration ».

**Sous Windows, sans rien installer** : double-clique sur **`lancer-site.bat`**. Le site s'ouvre sur http://localhost:8000.
Garde la fenêtre noire ouverte pendant que tu utilises le site, et ferme-la pour l'arrêter.

**Avec Python** (une fois Python installé, voir l'étape 2) :

```
python fetch.py
cd docs
python -m http.server 8000
```

Ouvre ensuite http://localhost:8000 dans ton navigateur.

Le site s'ouvre sur un **écran d'accueil**. Clique sur « Ouvrir le sourcing » ou appuie sur Entrée pour accéder aux produits.
Pour arriver directement sur les produits, ajoute `#app` à la fin de l'adresse, par exemple `http://localhost:8000/#app`.
Raccourcis : `/` pour rechercher, `Échap` pour effacer la recherche.

> Ouvrir `docs/index.html` par un double-clic **ne marche pas** : le navigateur bloque la lecture de `data.json`. Il faut passer par un petit serveur local, comme ci-dessus.

---

## 2. Installer Python (pour lancer `fetch.py` sur ton PC)

1. Va sur https://www.python.org/downloads/ et télécharge la dernière version de Python 3.
2. Lance l'installateur et **coche la case « Add python.exe to PATH »** avant de cliquer sur *Install Now*.
3. Ferme puis rouvre ton terminal (PowerShell) et tape `python --version` : un numéro de version doit s'afficher.

Installe ensuite la seule bibliothèque nécessaire, `cryptography`, qui sert à chiffrer les données du site :

```
python -m pip install -r requirements.txt
```

---

## 3. Créer ton compte CJ et récupérer ta clé API

1. Crée un compte gratuit sur https://cjdropshipping.com (bouton *Sign up*) et confirme ton e-mail.
2. Connecte-toi, puis va dans ton espace **My CJ**. Ouvre le menu **Authorization → API** (selon la version du site, la page peut aussi s'appeler « API » ou « API Key »).
3. Clique sur **Generate** (générer) pour créer ta clé API, puis copie-la. Elle ressemble à `CJ1234567@api@xxxxxxxx…`.
4. **Ne colle jamais cette clé dans un fichier du projet.** Elle va uniquement :
   - dans une variable d'environnement sur ton PC (étape 4) ;
   - dans les *secrets* GitHub (étape 7).

Documentation officielle : https://developers.cjdropshipping.com

---

## 4. Tester avec ta vraie clé sur ton PC

Dans PowerShell, depuis le dossier du projet :

```
$env:CJ_API_KEY = "colle-ta-cle-ici"
$env:SITE_LOGIN = "ton-identifiant"
$env:SITE_PASSWORD = "ton-mot-de-passe"
python fetch.py
```

Ces valeurs ne sont gardées que dans cette fenêtre PowerShell : elles disparaissent quand tu la fermes.
Lance ensuite le site comme à l'étape 1 et connecte-toi avec ton identifiant et ton mot de passe. Les vrais produits s'affichent.

Pour voir la liste des catégories CJ et leurs identifiants (`categoryId`) :

```
python fetch.py --categories
```

---

## 5. Choisir tes catégories et tes recherches (`config.json`)

Ouvre `config.json` avec le Bloc-notes. La partie importante est `recherches` :

```json
"recherches": [
  {"categorie": "Cuisine", "mot_cle": "kitchen gadget"},
  {"categorie": "Animaux", "categoryId": "identifiant-trouvé-avec---categories"}
]
```

- `categorie` : le nom affiché sur le site. Plusieurs lignes peuvent avoir le même nom.
- `mot_cle` : la recherche dans le catalogue CJ, **en anglais**.
- `categoryId` : facultatif, pour cibler une catégorie précise de CJ.

Les autres réglages sont expliqués directement dans le fichier : nombre de produits, fourchette de prix, pays de stock, poids du score, budget de points…

⚠️ En JSON, chaque ligne d'une liste se termine par une virgule **sauf la dernière**, et le texte doit être entre guillemets droits `"`.

---

## 6. Ajouter tes prix Amazon (facultatif)

Dans `amazon_prices.csv`, ajoute une ligne par produit :

```
id_cj,prix_amazon,asin
2410221030871601000,24.90,B0XXXXXXXX
```

- `id_cj` : l'identifiant CJ du produit. Clique sur **« Copier l'ID »** sur la carte du produit.
- `prix_amazon` : le prix TTC en euros constaté sur Amazon.fr, **avec un point** (exemple : `24.90`).
- `asin` : facultatif ; il ajoute un bouton « Amazon » sur la carte.

Pour ces produits, le site affiche le **profit** et le **ROI**. Les frais se règlent en haut de `fetch.py` : TVA 20 %, commission 15 %, FBA 3,50 € et transport 0,80 €.
Supprime les lignes `DEMO-…`, qui ne servent qu'au mode démo.

---

## 7. Mettre le site en ligne gratuitement (GitHub)

### a) Créer le dépôt
1. Crée un compte sur https://github.com.
2. En haut à droite, clique sur **+ → New repository**. Donne-lui un nom (par exemple `sourcing`) et choisis **Public** : GitHub Pages est gratuit pour les dépôts publics. Clique sur **Create repository**.
3. Envoie les fichiers du dossier. Le plus simple est d'installer **GitHub Desktop** (https://desktop.github.com), puis :
   *File → Add local repository* → choisis ce dossier → *create a repository* → *Publish repository*.
   (Les fichiers `config.json` et `amazon_prices.csv` seront visibles publiquement. La clé, elle, ne l'est jamais.)

### b) Ajouter les 3 secrets
1. Sur la page du dépôt : **Settings → Secrets and variables → Actions**.
2. Clique sur **New repository secret** et crée ces trois secrets, un par un :
   - `CJ_API_KEY` : ta clé CJ ;
   - `SITE_LOGIN` : l'identifiant pour entrer sur le site ;
   - `SITE_PASSWORD` : le mot de passe du site.
3. Clique sur **Add secret** à chaque fois.

Sans `SITE_LOGIN` et `SITE_PASSWORD`, la mise à jour s'arrête volontairement : les vrais produits ne sont jamais publiés en clair.

### c) Activer GitHub Pages sur /docs
1. **Settings → Pages**.
2. Dans *Source*, choisis **Deploy from a branch**.
3. Dans *Branch*, choisis **main** et le dossier **/docs**, puis clique sur **Save**.
4. Après 1 à 2 minutes, l'adresse de ton site s'affiche en haut de la page, par exemple `https://ton-pseudo.github.io/sourcing/`.

### d) Lancer la première mise à jour
1. Onglet **Actions**. Si GitHub le demande, clique sur le bouton pour activer les workflows.
2. Clique sur **maj-produits → Run workflow**.
3. Après quelques minutes, la coche verte indique que c'est terminé. La mise à jour se lance ensuite **toute seule toutes les heures**.
   Si rien n'a changé, aucun commit n'est créé.

---

## Accès protégé par identifiant et mot de passe

Le site s'ouvre sur un écran de connexion. Ce n'est pas un simple écran à contourner : **les produits sont chiffrés** dans `docs/data.json`.

- **Chiffrement** : AES-256-GCM, avec une clé dérivée de « identifiant:mot de passe » (PBKDF2-SHA256, 600 000 tours). Sans les bons identifiants, le fichier est illisible, même si quelqu'un le télécharge.
- **Où sont stockés les identifiants** : uniquement dans les secrets GitHub (et dans tes variables d'environnement sur ton PC), jamais dans un fichier du projet.
- **« Rester connecté sur cet appareil »** : garde l'accès dans le navigateur. Sans cette option, il faut se reconnecter à chaque nouvel onglet. Le bouton de déconnexion efface l'accès.
- **Changer de mot de passe** : modifie le secret `SITE_PASSWORD`, puis relance le workflow. L'ancien mot de passe ne fonctionnera plus.

Ce qui reste visible publiquement :
- le design du site ;
- la date de dernière mise à jour ;
- le contenu du dépôt GitHub public, dont `config.json` (tes mots-clés de recherche) et `amazon_prices.csv`.

Choisis un mot de passe **long**, par exemple 4 mots au hasard comme `velo-orange-piano-nuage`. Comme le fichier chiffré est public, un mot de passe court peut être deviné par un ordinateur qui essaie des millions de combinaisons.

---

## Comment est calculé le score qualité/prix (0 à 100)

Le score est calculé **à l'intérieur de chaque catégorie** :

- **Prix** (50 %) : prix le plus bas de la catégorie ÷ prix du produit. Le produit le moins cher obtient la note maximale.
- **Ventes** (30 %) : popularité du produit. C'est la moyenne entre le nombre de commandes passées chez CJ et le nombre de boutiques qui vendent le produit. On utilise une échelle logarithmique pour qu'un best-seller n'écrase pas tous les autres.
- **Note** (20 %) : note CJ du produit ÷ 5. Si CJ ne donne pas de note, ce poids est réparti sur les deux autres critères.
- Un produit en **rupture de stock** voit son score divisé par 2.

Tu peux changer ces poids dans `config.json` (`poids_score`).

---

## Limites de l'API CJ (compte gratuit)

- **1 requête par seconde**. Le programme fait les pauses tout seul et réessaie en cas d'erreur ou de lenteur.
- **50 000 points par jour**. Une recherche coûte 50 points.
  Avec 10 recherches par heure (500 points) et les calculs de livraison une fois par jour (environ 2 000 points), cela fait environ 14 000 points par jour : c'est largement suffisant.
  `budget_points_par_execution` arrête le programme avant de trop consommer.
- La note, le nombre d'avis, les commandes et la sous-catégorie demandent un appel par produit. Cet appel ne coûte pas de points, mais il prend 1 seconde. Ces informations sont gardées 24 h.
- **Livraison** : pour chaque produit, CJ calcule le délai (en jours) et les frais de port d'une unité, de la Chine vers la France. Cela coûte 10 points par produit, et le résultat est gardé 24 h.
  - Parmi tous les modes de transport proposés, le site affiche le **meilleur compromis prix/délai** : un jour de plus compte comme 0,25 € (constante `LIVRAISON_EUR_PAR_JOUR` en haut de `fetch.py`).
  - Il affiche aussi le **mode le plus rapide** quand il existe.
  - Pays de départ et d'arrivée : réglage `livraison` dans `config.json`.
- Peu de produits CJ ont une note : elle est souvent « — ».
- Les prix CJ sont en **dollars**. Ils sont convertis en euros avec le taux du jour de la Banque centrale européenne. Ce sont des prix hors frais de port CJ.
- D'après la documentation CJ, l'accès API peut être **désactivé après 30 jours sans aucune commande** sur le compte. Si la mise à jour s'arrête avec un message « API access has been disabled », contacte CJ.

## Le lien « Voir le fournisseur »

La documentation de l'API CJ ne précise pas l'adresse des fiches produit sur le site cjdropshipping.com. Le modèle utilisé est réglable dans `config.json` (`lien_produit`).
Pour le vérifier :

1. Ouvre une fiche produit sur cjdropshipping.com et regarde son adresse.
2. Si le format est différent, adapte le modèle. `{id}` est remplacé par l'identifiant du produit.

## Dépannage

- **« config.json introuvable ou invalide »** : il y a une virgule ou un guillemet en trop ou en moins dans `config.json`.
- **« clé API refusée »** : vérifie la clé (aucun espace avant ou après), en local comme dans le secret GitHub.
- **« quota CJ épuisé »** : attends le lendemain (remise à zéro à 1 h du matin, heure de Paris en hiver), ou réduis le nombre de recherches.
- **Le site affiche toujours la démo en ligne** : le secret `CJ_API_KEY` est absent ou mal nommé. Relance ensuite le workflow.
- **« la protection par mot de passe est activée mais SITE_LOGIN / SITE_PASSWORD sont absents »** : ajoute ces deux secrets (étape 7b).
- **« Identifiant ou mot de passe incorrect » alors qu'ils sont bons** : vérifie qu'ils sont identiques aux secrets GitHub (majuscules comprises pour le mot de passe ; l'identifiant, lui, ignore les majuscules).
- **Une erreur rouge dans l'onglet Actions** : clique dessus pour lire le message. En cas d'erreur, `docs/data.json` n'est pas modifié et le site garde les données précédentes.
