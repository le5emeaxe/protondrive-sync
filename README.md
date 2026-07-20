# Proton Drive Sync

Un client de synchronisation en tâche de fond pour Proton Drive, façon
`nextcloud-client-desktop` : icône de zone de notification, dossier local
synchronisé automatiquement, historique des dernières actions.

Construit au-dessus du CLI officiel `proton-drive` (pas de SDK non officiel).

## ⚠️ À lire avant de lancer pour de vrai

- **Pas de synchro temps réel.** Le CLI Proton Drive n'expose pas d'API
  d'événements pour les intégrations tierces — seulement des commandes
  ponctuelles. Ce projet **sonde** (liste l'arborescence distante) à
  intervalle régulier. Proton demande explicitement de ne pas faire de
  traversées récursives fréquentes ; l'intervalle par défaut est de 15
  minutes, à ajuster dans la config si besoin, mais évitez de descendre
  très bas (quelques minutes) pour rester dans les clous du fair-use.
- **Le périmètre est `/my-files`, pas `/`.** La racine `/` de Proton Drive
  n'est pas un vrai dossier : elle liste des catégories virtuelles (corbeille,
  partagés par/avec moi, photos...). Les synchroniser comme un dossier
  générique bidirectionnel n'aurait pas de sens (et serait dangereux pour
  la corbeille ou les partages). Le périmètre par défaut est donc
  `/my-files` ↔ `~/protondrive` — modifiable dans la config si tu veux
  vraiment cibler autre chose.
- **Mode simulation par défaut.** `dry_run: true` au premier lancement :
  rien n'est modifié, seul le journal d'activité indique ce qui *serait*
  fait. Vérifie le journal (icône tray → « Voir l'activité »), et quand tu
  es à l'aise avec ce que ferait la synchro, passe `dry_run` à `false` dans
  `~/.config/proton-drive-sync/config.json`.
- **Détection de changement locale par taille+date**, pas par hash complet
  (pour ne pas relire tous les fichiers à chaque sondage). Un fichier dont
  le contenu change sans changer ni taille ni date de modification ne sera
  pas détecté — cas rare en pratique.
- **Conflits réels (modifié des deux côtés depuis le dernier sync) : jamais
  d'écrasement silencieux.** Les deux versions sont conservées (la copie
  distante est retéléchargée à côté via `keep-both`, puis la version locale
  est envoyée comme copie de référence).

## Dépendances

```bash
pip install trayer --break-system-packages
```

### Arch Linux
```bash
sudo pacman -S python-gobject gtk4 libadwaita
```

### Debian / Ubuntu
```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-dbus
```

### GNOME uniquement : extension nécessaire pour voir l'icône
GNOME Shell n'affiche plus les icônes de zone de notification nativement.
Installe et active :
https://extensions.gnome.org/extension/615/appindicator-support/

```bash
gnome-extensions enable appindicatorsupport@ubuntu.com
# puis déconnexion/reconnexion
```

Il faut bien sûr `proton-drive-cli` installé et authentifié :
```bash
proton-drive auth login
```

## Configuration

`~/.config/proton-drive-sync/config.json` (créé automatiquement au premier
lancement avec ces valeurs par défaut) :

```json
{
  "local_root": "/home/toi/protondrive",
  "remote_root": "/my-files",
  "interval_seconds": 900,
  "sync_deletions": true,
  "dry_run": true
}
```

- `sync_deletions`: si `false`, les suppressions ne sont jamais propagées
  (le fichier reste des deux côtés) — plus prudent si tu veux d'abord
  n'avoir que de l'ajout automatique.
- Les changements de config sont relus à chaque ouverture de la fenêtre
  d'activité et pris en compte au prochain cycle de synchro (redémarre le
  démon pour un changement d'intervalle immédiat).

## Icône d'application et entrée .desktop

En plus des icônes du tray, `generate_icons.py` installe aussi une icône
d'application à nom stable (`protondrive-sync.svg`, pas besoin de
versionner celle-ci — la recherche d'icône standard du lanceur/Nautilus
n'est pas affectée par les problèmes spécifiques à l'extension AppIndicator
rencontrés pour le tray).

Pour l'utiliser via `protondrive-sync.desktop` (menu d'applications et/ou
démarrage automatique) :
```bash
# Ajuste le chemin Exec= dans le fichier si le projet n'est pas dans
# ~/proton-drive-sync, puis :
mkdir -p ~/.local/share/applications
cp protondrive-sync.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications  # si l'outil existe

# Optionnel : démarrage automatique au lieu du service systemd
mkdir -p ~/.config/autostart
cp protondrive-sync.desktop ~/.config/autostart/
```

`StartupWMClass=fr.andytoys.protondrivesync` correspond à l'`application_id`
du `Adw.Application` (déjà utilisé nativement comme `app_id` Wayland), pour
que gnome-shell associe correctement les fenêtres de l'appli à cette
entrée (regroupement dans l'aperçu, épinglage dans le dock, etc.).

## Détection instantanée des changements locaux

En plus du sondage périodique, `daemon.py` surveille `~/protondrive` en
temps réel via `Gio.FileMonitor` — le wrapper natif de GLib au-dessus
d'`inotify` (le mécanisme du noyau Linux prévu pour ça). Pas de nouveau
processus, pas de dépendance supplémentaire, pas de polling actif.

- Surveillance récursive : chaque sous-dossier (existant ou créé après
  coup) est surveillé automatiquement.
- Les rafales de changements (ex. copier 50 fichiers d'un coup) sont
  regroupées (« debounce » de 1,5s) pour ne déclencher qu'une seule
  synchronisation.
- Après chaque synchro, une courte pause (2s) ignore les événements
  locaux : sans ça, les propres téléchargements/suppressions de la synchro
  redéclencheraient aussitôt une nouvelle synchro en boucle.
- Le sondage périodique (intervalle configurable) reste nécessaire en
  parallèle : c'est le seul moyen de détecter un changement fait côté
  Proton Drive par un autre appareil, puisqu'il n'y a pas d'API
  d'événements distante.

## Icône

L'icône du tray est un dossier en dégradé violet inspiré de la palette Proton
(pas une copie du logo officiel), avec une pastille de statut en bas à
droite :
- 🟢 vert — actif, synchronisé
- 🔵 bleu — mode simulation (dry-run)
- ⚪ gris — en pause
- 🔴 rouge — dernière synchro en erreur
- pendant une synchro : la pastille verte **clignote** (l'opacité varie en
  douceur de 100% à 25% et retour, sur 8 images) plutôt que de changer de
  forme — plus discret qu'un gros spinner en plein milieu de l'icône.

Les fichiers SVG sont dans `icons/`. Au premier lancement, `daemon.py` les
copie automatiquement dans `~/.local/share/icons/hicolor/scalable/apps/`
(c'est nécessaire : l'icône du tray est affichée par un *autre processus*
— le shell/l'extension — qui ne voit pas les chemins de recherche internes
à cette appli, seulement le thème d'icônes standard de l'utilisateur).

**Cache d'icônes du shell :** GNOME Shell (et les hôtes StatusNotifierItem
en général) mettent en cache une icône *par nom* une fois chargée — modifier
le fichier SVG sur le disque sans changer son nom peut ne pas être détecté
sans redémarrer le shell. Pour éviter ça, chaque icône porte un numéro de
version dans son nom (`icon_version.py` → `ICON_VERSION`). Si tu modifies
`generate_icons.py` (couleurs, forme...), **incrémente `ICON_VERSION`** puis
relance :
```bash
python3 generate_icons.py
```
Le prochain démarrage du démon installera les nouveaux fichiers sous un nom
inédit — garantissant un affichage à jour sans avoir à redémarrer le shell —
et supprimera les fichiers de l'ancienne version.

## Pourquoi une icône personnalisée peut ne pas s'afficher (et le correctif)

`trayer` (v0.1.1) n'expose pas la propriété D-Bus `IconThemePath` prévue par
la spec StatusNotifierItem pour indiquer où chercher une icône qui n'est pas
dans le thème système. Résultat possible : l'item s'enregistre très bien
(visible dans `busctl --user list`), mais l'extension GNOME ne trouve jamais
le fichier et n'affiche rien — silencieusement, sans erreur.

`trayer_patch.py` corrige ça par monkeypatch au démarrage (avant la création
du `TrayIcon`), sans toucher au paquet pip installé : il ajoute
`IconThemePath` pointant vers `~/.local/share/icons/hicolor/scalable/apps`
(le dossier plat qui contient réellement les fichiers, pas la racine du
thème `hicolor`) — confirmé nécessaire via les logs de gnome-shell
(`journalctl --user -o cat _COMM=gnome-shell`), qui montrent que
l'extension AppIndicator fait une recherche **directe** dans
`IconThemePath` (`IconThemePath/nom.svg`), pas une recherche hiérarchique
`taille/contexte/nom.svg` comme le ferait GTK. C'est fait automatiquement
par `daemon.py`, rien à faire de plus.

Si jamais l'icône reste invisible malgré tout : teste avec une icône
standard (`icon_name="folder-symbolic"` dans `daemon.py`) pour vérifier que
le mécanisme d'affichage lui-même fonctionne, avant de suspecter autre
chose (extension pas activée, shell pas redémarré depuis l'activation...).

## Lancement manuel

```bash
python3 daemon.py
```

## Lancement automatique au démarrage (systemd --user)

```bash
mkdir -p ~/.config/systemd/user
cp protondrive-sync.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now protondrive-sync.service
# suivre les logs :
journalctl --user -u protondrive-sync.service -f
```

## Structure

- `config.py` — chargement/écriture du fichier JSON de config
- `backend.py` — appelle `proton-drive` (list/upload/download/trash/...),
  toujours avec des stratégies de conflit explicites (`-f`/`-d`) pour ne
  jamais tomber sur un prompt interactif
- `state_db.py` — SQLite : dernier état connu par fichier + journal
  d'activité
- `sync_engine.py` — la logique de diff/synchro elle-même, sans aucune
  dépendance GTK (testable isolément)
- `daemon.py` — icône de tray (via la lib `trayer`, StatusNotifierItem pur
  GTK4/D-Bus) + minuteur + menu
- `activity_window.py` — fenêtre "dernières synchronisations"
- `settings_window.py` — panneau « Paramètres » (dry-run, propagation des
  suppressions, intervalle en minutes), accessible depuis le menu du tray,
  application immédiate sans redémarrage

## Limitations connues

- `trayer` est une petite bibliothèque récente (peu d'historique) : si
  l'icône ne s'affiche pas ou se comporte mal, le repli GTK3 classique
  serait d'utiliser `AyatanaAppIndicator3` dans un processus séparé (non
  inclus ici pour ne pas mélanger GTK3/GTK4 dans le même process).
- Pas de synchro par blocs/delta : un fichier modifié est retransféré en
  entier.
- Pas encore de détection de renommage (un renommage est traité comme une
  suppression + un ajout).
