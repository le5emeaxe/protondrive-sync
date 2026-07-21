# Proton Drive Sync

Suite d'outils de synchronisation Proton Drive pour Linux/GNOME, construite
entièrement au-dessus du **CLI officiel `proton-drive`** (pas de SDK ni
d'API non officielle) :

1. **Démon de synchro en tâche de fond** (`daemon.py`) — façon
   `nextcloud-client-desktop` : icône de tray, dossier local synchronisé
   automatiquement et bidirectionnellement avec Proton Drive.
2. **Extension Nautilus — Partage** (`nautilus_protondrive_share.py`) —
   clic droit sur un fichier synchronisé → génère un lien de partage
   Proton Drive et l'envoie par e-mail.
3. **Extension Nautilus — Badge de statut** (`nautilus_protondrive_emblem.py`)
   — pastille colorée sur l'icône du dossier synchronisé, façon client
   Nextcloud, reflétant l'état courant de la synchro (y compris si le
   démon lui-même s'est arrêté).

---

## Sommaire

- [Présentation fonctionnelle](#présentation-fonctionnelle)
- [Architecture technique](#architecture-technique)
- [Prérequis système](#prérequis-système)
- [Dépendances Python (pip)](#dépendances-python-pip)
- [Installation](#installation)
  - [Étape 1 — Récupérer les fichiers](#étape-1--récupérer-les-fichiers)
  - [Étape 2 — Prérequis système](#étape-2--prérequis-système)
  - [Étape 3 — Dépendance pip](#étape-3--dépendance-pip)
  - [Étape 4 — CLI Proton Drive et authentification](#étape-4--cli-proton-drive-et-authentification)
  - [Étape 5 — Générer les icônes](#étape-5--générer-les-icônes)
  - [Étape 6 — Premier lancement du démon](#étape-6--premier-lancement-du-démon)
  - [Étape 7 — Installer les extensions Nautilus](#étape-7--installer-les-extensions-nautilus)
  - [Étape 8 — Configuration de l'envoi d'e-mail (swaks)](#étape-8--configuration-de-lenvoi-de-mail-swaks)
- [Première connexion à Proton Drive (CLI)](#première-connexion-à-proton-drive-cli)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Démarrage automatique](#démarrage-automatique)
- [Icônes](#icônes)
- [Journal des appels CLI](#journal-des-appels-cli)
- [Détection instantanée des changements locaux](#détection-instantanée-des-changements-locaux)
- [Limitations connues](#limitations-connues)
- [Dépannage](#dépannage)

---

## Présentation fonctionnelle

### 1. Démon de synchro (tray)

- **Synchronisation bidirectionnelle** entre un dossier local
  (`~/protondrive` par défaut) et `/my-files` sur Proton Drive : upload des
  nouveaux fichiers locaux, téléchargement des nouveaux fichiers distants,
  propagation des suppressions dans les deux sens.
- **Icône de tray** (dossier violet + pastille de statut) :
  - 🟢 vert — actif, synchronisé · 🔵 bleu — simulation (dry-run) ·
    ⚪ gris — en pause · 🔴 rouge — dernière synchro en erreur
  - pendant une synchro : la pastille verte clignote doucement (variation
    d'opacité)
- **Détection instantanée des changements locaux** via `inotify`, en plus
  d'un sondage périodique classique pour le sens distant → local.
- **Journal d'activité** et **panneau de paramètres** (dry-run,
  suppressions, intervalle) accessibles depuis le menu du tray, tout
  s'appliquant à chaud.
- **Gestion des conflits sans perte de données** : si un fichier a été
  modifié des deux côtés depuis la dernière synchro, les deux versions
  sont conservées, jamais d'écrasement silencieux.
- **Authentification intégrée** : détecte si la session Proton Drive est
  valide et propose de se reconnecter directement depuis le menu si besoin.
- **Journal des appels CLI** pour le diagnostic, et fenêtre **« À propos »**.

### 2. Extension Nautilus — Partage

Clic droit sur un fichier situé sous le dossier synchronisé → **« Partager
via Proton Drive »** : génère (ou récupère) un lien de partage public via
`proton-drive sharing set-url`, l'affiche dans une petite fenêtre, et
permet de l'envoyer par e-mail à un destinataire (via `swaks`, sans
authentification SMTP).

### 3. Extension Nautilus — Badge de statut

Superpose une pastille colorée sur l'icône du dossier `~/protondrive`
lui-même dans Nautilus, reflétant en direct l'état écrit par le démon de
synchro :

- 🟢 synchronisé · 🔵 simulation (dry-run) · ⚪ en pause · 🔴 erreur

Le badge vérifie aussi que **le démon est réellement en cours
d'exécution** (via son PID, pas seulement le dernier statut écrit) : s'il
a été arrêté ou a planté, la pastille repasse au gris (« stopped ») plutôt
que de rester figée sur le dernier état connu — avec une revérification
toutes les 30 secondes même sans nouvelle écriture du démon.

### Ce que l'application n'est PAS

- Pas de synchronisation temps réel côté serveur : Proton Drive n'expose
  pas d'API d'événements pour les intégrations tierces. Les changements
  **distants** ne sont détectés que par sondage périodique.
- Le périmètre synchronisé est volontairement limité à `/my-files`, pas la
  racine `/` de Proton Drive (qui contient aussi corbeille, partages,
  photos — pas pertinent à traiter comme un dossier générique
  bidirectionnel).

---

## Architecture technique

### Démon de synchro

| Fichier | Rôle |
|---|---|
| `backend.py` | Appelle le binaire `proton-drive` en JSON, stratégies de conflit toujours explicites (jamais de prompt interactif). Journalise chaque appel CLI. |
| `state_db.py` | SQLite : dernier état connu par fichier + journal d'activité. |
| `sync_engine.py` | Logique de diff/synchro, sans dépendance GTK. |
| `config.py` | Chargement/écriture de `~/.config/proton-drive-sync/config.json`. |
| `daemon.py` | Point d'entrée : icône de tray, minuteur, menu, authentification, écriture du fichier de statut (avec PID), câblage des autres composants. |
| `local_watcher.py` | Surveillance récursive de `~/protondrive` via `Gio.FileMonitor` (inotify). |
| `activity_window.py` | Fenêtre « dernières synchronisations ». |
| `settings_window.py` | Panneau de paramètres. |
| `about_window.py` | Fenêtre « À propos ». |
| `icons.py` | Installe/découvre les icônes SVG du tray sur le disque. |
| `generate_icons.py` | Génère toutes les icônes (tray, application, pastilles Nautilus) et les installe. |
| `icon_version.py` | Numéros de version des icônes (cache-busting shell). |
| `trayer_patch.py` | Corrige `trayer` pour exposer `IconThemePath` (nécessaire pour que gnome-shell trouve nos icônes custom). |
| `protondrive-sync.desktop` / `.service` | Entrée de menu / autostart / service systemd. |

### Extensions Nautilus

| Fichier | Rôle |
|---|---|
| `nautilus_protondrive_share.py` | Menu contextuel de partage + envoi e-mail. Utilise `Gio.Subprocess` en asynchrone (pas de thread Python brut — voir Dépannage). |
| `nautilus_protondrive_emblem.py` | Badge de statut sur le dossier synchronisé, via `Nautilus.InfoProvider`. Mis à jour en direct par `Gio.FileMonitor` sur le fichier de statut, complété par une vérification périodique (30s) de la vivacité du démon via son PID. |

Les deux extensions lisent `~/.config/proton-drive-sync/config.json` pour
connaître le mapping dossier local ↔ distant, et restent donc cohérentes
avec la configuration du démon sans duplication.

### Fichier de statut (`~/.cache/proton-drive-sync/status.json`)

Écrit par `daemon.py` après chaque cycle de synchro, lu par l'extension
badge :
```json
{
  "status": "synced",
  "local_root": "/home/toi/protondrive",
  "last_sync": 1737360000.0,
  "pid": 12345
}
```
Le champ `pid` permet à l'extension de vérifier que le processus qui a
écrit ce statut est toujours vivant (et que c'est bien `daemon.py`, pas un
autre programme ayant récupéré ce PID depuis) avant de lui faire
confiance.

### Principe de la synchronisation

Le CLI Proton Drive n'exposant aucune API d'événements pour les
intégrations tierces, `sync_engine.py` fonctionne par **sondage
périodique** : lister local + distant, comparer au dernier état connu,
décider action par action (envoyer / télécharger / créer un dossier /
mettre à la corbeille / rien faire), et en cas de modification des deux
côtés depuis le dernier passage, conserver les deux versions plutôt que de
choisir. `local_watcher.py` complète ça côté local par une détection
instantanée via inotify.

---

## Prérequis système

### Arch Linux
```bash
sudo pacman -S python-gobject gtk4 libadwaita python-dbus nautilus-python swaks
```

### Debian / Ubuntu
```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-dbus python3-nautilus swaks
```

### Fedora
```bash
sudo dnf install python3-gobject gtk4 libadwaita python3-dbus nautilus-python swaks
```

`nautilus-python` (Arch/Fedora) / `python3-nautilus` (Debian/Ubuntu) est
le paquet qui permet à Nautilus de charger des extensions écrites en
Python — indispensable pour les deux extensions de ce projet, inutile si
vous n'utilisez que le démon de synchro seul.

### GNOME uniquement — extension requise pour voir l'icône de tray

GNOME Shell n'affiche plus nativement les icônes de zone de notification.
Installer et activer **AppIndicator and KStatusNotifierItem Support** :
```
https://extensions.gnome.org/extension/615/appindicator-support/
```
```bash
gnome-extensions enable appindicatorsupport@ubuntu.com
# puis déconnexion/reconnexion de la session
```

### Le CLI Proton Drive lui-même

Indispensable et installé séparément : télécharger le binaire officiel
depuis `proton.me/download/drive/cli`.

---

## Dépendances Python (pip)

```bash
pip install trayer --break-system-packages
```

`trayer` implémente l'icône de tray en GTK4 pur via D-Bus
(StatusNotifierItem), nécessaire car GTK4 a supprimé `Gtk.StatusIcon` et
les bibliothèques historiques (AppIndicator3) sont conçues pour GTK3,
incompatible en cohabitation dans le même process Python. Aucune autre
dépendance pip n'est nécessaire (les extensions Nautilus n'utilisent que
la bibliothèque standard + PyGObject, déjà couvert par les paquets système
ci-dessus).

---

## Installation

### Étape 1 — Récupérer les fichiers

```bash
mkdir -p ~/proton-drive-sync
cd ~/proton-drive-sync
# copier ici tous les fichiers .py, le dossier icons/, et les .desktop/.service
```

Vérifiez que vous avez bien tous les fichiers listés dans
[Architecture technique](#architecture-technique) :
```bash
ls ~/proton-drive-sync
```

### Étape 2 — Prérequis système

Voir [Prérequis système](#prérequis-système) ci-dessus selon votre
distribution. Vérifiez que PyGObject fonctionne avant d'aller plus loin :
```bash
python3 -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk, Adw; print('OK')"
```
Si ça affiche `OK` sans erreur, l'environnement GTK4/libadwaita est prêt.

### Étape 3 — Dépendance pip

```bash
pip install trayer --break-system-packages
python3 -c "import trayer; print('trayer OK')"
```

### Étape 4 — CLI Proton Drive et authentification

Voir la section dédiée [Première connexion à Proton Drive
(CLI)](#première-connexion-à-proton-drive-cli) plus bas — à faire avant de
lancer le démon, sinon il démarrera en état « non authentifié » (ce n'est
pas bloquant, une entrée de menu permet de se reconnecter après coup, mais
autant le faire dans l'ordre).

### Étape 5 — Générer les icônes

```bash
cd ~/proton-drive-sync
python3 generate_icons.py
```

Ceci génère et installe **trois jeux d'icônes** en une seule commande :
icônes du tray, icône d'application (menu/launcher), et pastilles de
statut Nautilus. Vérifiez que ça s'est bien passé :
```bash
ls ~/.local/share/icons/hicolor/scalable/apps/ | grep protondrive
```
Vous devriez voir une quinzaine de fichiers `.svg`.

### Étape 6 — Premier lancement du démon

```bash
python3 daemon.py
```

Vérifiez dans l'ordre :
1. Une icône violette (dossier + pastille) apparaît dans la zone de
   notification.
2. Un clic dessus ouvre un menu avec au moins « Synchroniser maintenant »,
   « Voir l'activité », « Quitter ».
3. Le dossier `~/protondrive` a bien été créé automatiquement s'il
   n'existait pas.

Si l'icône n'apparaît pas, voir [Dépannage](#dépannage) — c'est
généralement l'extension AppIndicator qui manque ou n'est pas activée.

Une fois validé, laissez tourner ou passez à
[Démarrage automatique](#démarrage-automatique) pour ne plus avoir à le
relancer manuellement à chaque session.

### Étape 7 — Installer les extensions Nautilus

Cette étape est **optionnelle** et **indépendante** du démon : vous pouvez
très bien n'utiliser que la synchronisation en tâche de fond sans les
extensions Nautilus, ou l'inverse (bien que les extensions supposent que
le démon tourne pour être vraiment utiles — le badge de statut, en
particulier, n'a de sens que si `daemon.py` écrit son fichier de statut).

**7.1 — Créer le dossier d'extensions Nautilus s'il n'existe pas :**
```bash
mkdir -p ~/.local/share/nautilus-python/extensions
```

**7.2 — Copier les deux fichiers d'extension** (vous pouvez n'en installer
qu'un seul si vous ne voulez pas les deux fonctionnalités) :
```bash
cp nautilus_protondrive_share.py ~/.local/share/nautilus-python/extensions/
cp nautilus_protondrive_emblem.py ~/.local/share/nautilus-python/extensions/
```

**7.3 — Vérifier que les fichiers sont bien là et lisibles :**
```bash
ls -l ~/.local/share/nautilus-python/extensions/
```
Vous devriez voir les deux fichiers `.py` avec des droits de lecture pour
votre utilisateur (pas besoin d'exécutable, Nautilus les importe comme
modules Python, il ne les exécute pas directement).

**7.4 — Fermer complètement Nautilus, puis le relancer depuis un
terminal** (important pour la vérification qui suit — lancer depuis le
dock/menu d'applications ne vous laisserait pas voir d'éventuelles
erreurs) :
```bash
pkill -f nautilus
nautilus &
```
Le `&` à la fin garde la main sur le terminal pour que vous puissiez
continuer à voir ce qu'affiche Nautilus pendant que la fenêtre reste
ouverte.

**7.5 — Vérifier que les extensions se sont chargées sans erreur.**
Regardez la sortie du terminal juste après le lancement : un chargement
réussi ne produit généralement aucun message particulier pour ces deux
extensions (pas de erreur = bon signe). Si vous voyez un `Traceback`
Python mentionnant `nautilus_protondrive_share.py` ou
`nautilus_protondrive_emblem.py`, copiez-le pour diagnostiquer — c'est
plus parlant qu'un simple "ça ne marche pas".

**7.6 — Tester l'extension Partage :**
- Naviguez dans `~/protondrive` (ou un sous-dossier).
- Clic droit sur un fichier (pas un dossier — l'extension ne s'active que
  sur les fichiers).
- Vérifiez qu'une entrée **« Partager via Proton Drive »** apparaît dans
  le menu contextuel.
- Cliquez dessus : une petite fenêtre « Génération du lien… » doit
  apparaître immédiatement, suivie quelques secondes plus tard (aller-
  retour réseau vers Proton) d'une fenêtre avec l'URL de partage et un
  champ e-mail.

Si l'entrée de menu n'apparaît pas du tout : vérifiez que le fichier
cliqué est bien réellement sous le `local_root` configuré (par défaut
`~/protondrive`) — l'extension vérifie ce mapping via
`~/.config/proton-drive-sync/config.json` et n'ajoute l'entrée de menu que
si le fichier s'y trouve.

**7.7 — Tester l'extension Badge de statut :**
- Le démon (`daemon.py`) doit être **en cours d'exécution** pour ce test
  (voir Étape 6).
- Regardez l'icône du dossier `~/protondrive` lui-même dans Nautilus (pas
  son contenu — le dossier en tant que tel, visible depuis son dossier
  parent, ex. votre dossier personnel).
- Une petite pastille colorée doit apparaître en surimpression sur
  l'icône du dossier (verte si tout est synchronisé).
- Test de la détection d'arrêt : tuez le démon (`pkill -f daemon.py` ou
  fermez-le via le menu « Quitter »), attendez jusqu'à 30 secondes, et
  vérifiez que la pastille passe au gris.

Si le badge n'apparaît pas du tout, voir la section dédiée dans
[Dépannage](#dépannage) — plusieurs comportements différents selon les
versions de Nautilus ont été rencontrés pendant le développement de cette
extension, et le fichier installe volontairement les icônes à deux
emplacements différents pour couvrir ces cas.

### Étape 8 — Configuration de l'envoi d'e-mail (swaks)

`nautilus_protondrive_share.py` envoie le lien de partage par e-mail via
**`swaks`**, qu'il faut installer séparément :

```bash
sudo pacman -S swaks          # Arch
sudo apt install swaks        # Debian/Ubuntu
sudo dnf install swaks        # Fedora
```

Vérifiez que la commande est bien disponible :
```bash
which swaks
```

Les paramètres d'envoi (adresse expéditrice, serveur SMTP, port) sont en
dur en haut du fichier `nautilus_protondrive_share.py` — à adapter à votre
propre serveur avant utilisation, **puis à recopier dans le dossier
d'extensions Nautilus** (l'étape 7.2 recopie une version figée du
fichier, donc toute modification faite après coup doit être re-déployée
de la même façon) :

```python
FROM_ADDRESS = "partage@domaine.fr"
SMTP_SERVER = "192.168.1.6"
SMTP_PORT = "25"
```

```bash
# Après avoir modifié les valeurs ci-dessus dans votre copie du fichier :
cp nautilus_protondrive_share.py ~/.local/share/nautilus-python/extensions/
pkill -f nautilus
nautilus &
```

Ces valeurs par défaut correspondent à un envoi **sans authentification ni
TLS** (réseau local de confiance). Pour toute option supplémentaire (TLS,
auth, pièces jointes, CC/BCC, etc.), voir la documentation officielle de
swaks : **https://www.jetmore.org/john/code/swaks/** — la fonction
`send_share_email_async()` dans `nautilus_protondrive_share.py` est
l'unique endroit à modifier pour ajuster les arguments passés à `swaks`.

Pour tester l'envoi indépendamment de l'extension, en ligne de commande :
```bash
swaks --to votre-adresse-de-test@example.com \
      --from partage@domaine.fr \
      --server 192.168.1.6:25 \
      --h-Subject "Test" \
      --body "Ceci est un test."
```
Si ça échoue en ligne de commande, ça échouera aussi depuis l'extension —
utile pour isoler un problème réseau/serveur SMTP de l'extension elle-même.

---

## Première connexion à Proton Drive (CLI)

Le CLI `proton-drive` doit être connecté à votre compte Proton
**indépendamment de cette application** — l'authentification et la
session sont entièrement gérées par le CLI officiel.

```bash
proton-drive auth login
```

Cette commande ouvre votre **navigateur** pour une authentification
OAuth (pas de mot de passe tapé dans le terminal). La session est ensuite
stockée automatiquement et en sécurité par le système (`libsecret`/GNOME
Keyring sur Linux), et persiste tant que le token n'expire pas ou que vous
ne faites pas `auth logout`.

Vérifier que la connexion fonctionne :
```bash
proton-drive filesystem list -j /my-files
```
Si ça renvoie une liste JSON (même vide, `[]`) sans erreur, tout est prêt.

Le démon lui-même détecte l'état d'authentification au démarrage et
propose une entrée **« ⚠ Authentification »** dans son menu si la session
n'est pas valide — cliquer dessus relance `auth login` automatiquement.

**Point d'attention Arch** : `libsecret` a besoin d'un service Secret
Service actif (GNOME Keyring) pour fonctionner ; sur une install Arch
minimaliste, ce n'est pas toujours présent par défaut :
```bash
systemctl --user status gnome-keyring-daemon
# si absent :
sudo pacman -S gnome-keyring
```

Pour se déconnecter : `proton-drive auth logout`.

---

## Configuration

Fichier `~/.config/proton-drive-sync/config.json`, créé automatiquement au
premier lancement :

```json
{
  "local_root": "/home/toi/protondrive",
  "remote_root": "/my-files",
  "interval_seconds": 900,
  "sync_deletions": true,
  "dry_run": true
}
```

| Clé | Effet |
|---|---|
| `local_root` | Dossier local synchronisé. Changement pris en compte au redémarrage du démon (et lu aussi par les deux extensions Nautilus). |
| `remote_root` | Dossier distant synchronisé. Ne pas mettre `/`. |
| `interval_seconds` | Intervalle de sondage. Modifiable à chaud (Paramètres du tray, en minutes). |
| `sync_deletions` | Si `false`, aucune suppression n'est jamais propagée. Modifiable à chaud. |
| `dry_run` | Mode simulation, **activé par défaut** au premier lancement. Modifiable à chaud. |

`local_root`/`remote_root` ne sont volontairement pas modifiables depuis
l'interface, pour éviter un changement accidentel de périmètre en cours
de route.

---

## Utilisation

### Menu du tray

- **Synchroniser maintenant**, **Voir l'activité**, **Ouvrir le dossier
  local**, **Mettre en pause/Reprendre**, **Paramètres…**, **À propos**,
  **Quitter**.
- Entrée **Compte : email@…** ou **⚠ Authentification** selon l'état de
  connexion.
- Un clic gauche sur l'icône ouvre directement la fenêtre d'activité.

### Dans Nautilus

- Clic droit sur un fichier sous `~/protondrive` → **Partager via Proton
  Drive** → fenêtre avec l'URL + champ e-mail + bouton Envoyer (se ferme
  automatiquement une fois l'e-mail envoyé).
- Le dossier `~/protondrive` lui-même affiche une pastille de couleur
  reflétant l'état courant de la synchro — y compris si le démon s'est
  arrêté (pastille grise dans les 30s suivant son arrêt).

---

## Démarrage automatique

### Option A — service systemd utilisateur (recommandé pour le démon)

```bash
mkdir -p ~/.config/systemd/user
cp protondrive-sync.service ~/.config/systemd/user/
# Ajuster ExecStart= si besoin
systemctl --user daemon-reload
systemctl --user enable --now protondrive-sync.service
journalctl --user -u protondrive-sync.service -f
```

### Option B — entrée .desktop en autostart

```bash
mkdir -p ~/.config/autostart
cp protondrive-sync.desktop ~/.config/autostart/
```

La même entrée, copiée dans `~/.local/share/applications/` plutôt que
`~/.config/autostart/`, fait apparaître l'application dans le menu
d'applications standard (icône dédiée, bon `WM_CLASS`) sans la lancer
automatiquement.

Les extensions Nautilus, elles, se chargent automatiquement à chaque
démarrage de Nautilus une fois copiées dans
`~/.local/share/nautilus-python/extensions/` — rien d'autre à configurer,
pas de service à activer pour elles.

---

## Icônes

- **Tray** : dossier violet + pastille de statut, versionnées
  (`protondrive-sync-idle-vN.svg`…) pour contourner le cache d'icônes du
  shell. Si vous modifiez le design, **incrémentez `ICON_VERSION`** dans
  `icon_version.py` avant de relancer `generate_icons.py`.
- **Application** (menu/launcher) : `protondrive-sync.svg`, nom stable,
  pas de souci de cache pour ce contexte-là.
- **Pastilles Nautilus** : `protondrive-emblem-<statut>-vN.svg`, installées
  à la fois dans `hicolor/scalable/emblems/` et `hicolor/scalable/apps/`
  (Nautilus s'est montré capricieux sur l'emplacement exact selon le
  contexte — les deux couvrent toutes les éventualités). Version suivie
  séparément via `EMBLEM_VERSION` dans `icon_version.py`.

`generate_icons.py` installe automatiquement tout ça ; `daemon.py` refait
l'installation des icônes de tray à chaque démarrage par sécurité.

---

## Journal des appels CLI

Chaque appel à `proton-drive` fait par le démon (commande exacte, code de
sortie, stdout, stderr, durée) est journalisé dans :
```
~/.local/share/proton-drive-sync/cli.log
```
Rotation automatique passé 5 Mo (`cli.log.old`).
```bash
tail -f ~/.local/share/proton-drive-sync/cli.log
```
Ce fichier ne contient jamais d'identifiants — l'authentification se fait
par navigateur, jamais en argument de ligne de commande.

---

## Détection instantanée des changements locaux

En plus du sondage périodique, `daemon.py` surveille `~/protondrive` en
temps réel via `Gio.FileMonitor` (inotify) :
- Surveillance récursive (sous-dossiers existants et créés après coup).
- Rafales de changements regroupées (debounce 1,5s) en une seule synchro.
- Courte pause (2s) après chaque synchro pour ignorer les événements
  causés par ses propres écritures (évite la boucle).
- Le sondage périodique reste nécessaire en parallèle pour détecter les
  changements faits côté Proton Drive par un autre appareil.

---

## Limitations connues

- Pas de synchro par blocs/delta : un fichier modifié est retransféré en
  entier.
- Pas de détection de renommage (traité comme suppression + ajout).
- Détection de changement local basée sur taille + date de modification,
  pas un hash complet du contenu.
- Le sondage distant reste nécessaire malgré la détection locale
  instantanée : pas d'API d'événements distante côté Proton Drive. Éviter
  de descendre l'intervalle très bas (fair-use Proton).
- Extension de partage : le champ JSON utilisé pour extraire l'URL
  (`publicLink.url`) a été confirmé par un test réel, mais reste
  dépendant du format de sortie du CLI, qui pourrait évoluer.
- La pastille Nautilus distingue « en pause » (choix volontaire dans le
  menu) et « arrêté » (démon tué/planté) avec la même icône grise — pas de
  distinction visuelle entre les deux pour l'instant.

---

## Dépannage

**L'icône de tray n'apparaît pas du tout**
Vérifier que l'extension AppIndicator est installée, activée, et que la
session a été redémarrée depuis son activation. Tester avec une icône
système standard (`icon_name="folder-symbolic"` dans `daemon.py`) pour
isoler si le problème est général ou spécifique à nos icônes.

**L'icône reste bloquée sur l'ancienne version après une modification**
Incrémenter `ICON_VERSION` (ou `EMBLEM_VERSION`) dans `icon_version.py` et
relancer `generate_icons.py` — le shell met en cache une icône par *nom*,
remplacer le fichier sans changer le nom ne suffit pas toujours.

**Erreur `command not found` ou options CLI qui ne correspondent pas**
La syntaxe du CLI peut évoluer. Vérifier avec `proton-drive --help` et
`proton-drive filesystem <sous-commande> --help`, ajuster `backend.py`
(les appels y sont centralisés).

**Une synchro semble bloquée sur l'icône « en cours »**
Vérifier `journalctl --user -f -o cat _COMM=gnome-shell | grep -i protondrive`.
Si rien côté Python mais l'icône reste figée visuellement, c'est un souci
de rafraîchissement côté extension GNOME, pas côté application.

**L'entrée « Partager via Proton Drive » n'apparaît pas dans le menu**
- Vérifier que `nautilus-python`/`python3-nautilus` est bien installé
  (sans lui, Nautilus ignore silencieusement tous les fichiers `.py` du
  dossier d'extensions).
- Vérifier que le fichier cliqué est réellement sous le `local_root`
  configuré (`~/.config/proton-drive-sync/config.json`).
- Vérifier qu'on a bien cliqué droit sur un **fichier**, pas un dossier
  (l'extension ne s'active pas sur les dossiers).
- Relancer Nautilus depuis un terminal (`pkill -f nautilus && nautilus &`)
  pour voir d'éventuelles erreurs de chargement.

**L'extension Nautilus de partage met un temps anormalement long à répondre**
Peut arriver si Nautilus est lui-même occupé (ex. génération de
miniatures) au moment du clic : un thread Python brut peut alors se faire
affamer du GIL pendant plusieurs minutes. C'est pour ça que
`nautilus_protondrive_share.py` utilise `Gio.Subprocess` en asynchrone
plutôt que `threading.Thread` — si le problème revient malgré tout,
vérifier `~/.cache/nautilus-protondrive-share-timing.log` (instrumentation
laissée en place) pour localiser précisément où passe le temps.

**"Failed to load icon .../scalable/emblems/..." ou badge absent dans Nautilus**
Les pastilles sont installées à la fois dans `scalable/emblems/` et
`scalable/apps/` justement pour couvrir les deux comportements observés
selon le contexte — si le badge n'apparaît toujours pas après
`generate_icons.py` + redémarrage de Nautilus, vérifier que les 4 fichiers
`protondrive-emblem-*-vN.svg` existent bien dans les deux dossiers :
```bash
ls ~/.local/share/icons/hicolor/scalable/emblems/ | grep protondrive-emblem
ls ~/.local/share/icons/hicolor/scalable/apps/ | grep protondrive-emblem
```

**La pastille reste verte alors que le démon est arrêté**
Corrigé : l'extension vérifie désormais la vivacité du démon via son PID
(champ `pid` dans `status.json`), avec une revérification toutes les 30s.
Si ça se reproduit malgré tout, vérifier que `daemon.py` a bien été
redémarré après la mise à jour du code (l'ancien fichier de statut
n'aurait pas de champ `pid`).

**L'envoi d'e-mail (swaks) échoue depuis l'extension mais fonctionne en CLI**
Vérifier que la copie du fichier dans
`~/.local/share/nautilus-python/extensions/` correspond bien à votre
dernière modification des constantes `FROM_ADDRESS`/`SMTP_SERVER`/
`SMTP_PORT` — voir [Étape 8](#étape-8--configuration-de-lenvoi-de-mail-swaks).
