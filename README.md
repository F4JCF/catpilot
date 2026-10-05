# CAT Pilot 0.2 — Yaesu FT-991A

Logiciel de pilotage CAT du Yaesu FT-991A sous Windows, avec partage du CAT
vers WSJT-X, JTDX, Log4OM, N1MM… grâce à un serveur compatible rigctld.

## Obtenir l'exécutable

1. **Sans rien installer** : déposer ce dossier dans un dépôt GitHub. L'action
   « Construire l'exécutable Windows » produit `CATPilot.exe`, à télécharger dans
   l'onglet *Actions* > dernière exécution > *Artifacts*.
2. **Sur le PC Windows** : installer Python 3.12 (cocher « Add to PATH »), puis
   double-cliquer sur `build.bat`. L'exécutable apparaît dans `dist\`.
3. **Pour tester directement** : `pip install -r requirements.txt` puis `python run.py`.

Le poste « Simulateur » permet de tout essayer sans radio.

## Réglage du FT-991A

- Câble USB direct, pilote Silicon Labs CP210x installé.
- Windows crée deux ports COM : choisir le port **Enhanced** (CAT). CAT Pilot
  le présélectionne quand il le reconnaît.
- Menu 031 CAT RATE : 38400 bps (même valeur dans CAT Pilot).
- Si rien ne répond : essayer 2 bits de stop, et vérifier le menu 033 CAT RTS.

## Ce que fait CAT Pilot

- **VFO** : afficheur VFO A (molette sur un chiffre pour le régler), VFO B
  (molette aussi), A/B, A>B, B>A, Split, V/M, UP/DN, saisie directe, pas d'accord.
- **Bandes** : 160 m à 70 cm ; chaque bande mémorise la dernière fréquence utilisée.
- **Modes** : USB, LSB, CW, CW-R, AM, FM, RTTY, DATA-L/U/FM, C4FM.
- **RF** : ATT, IPO / AMP 1 / AMP 2, AGC, coupleur (ATU) et Tune.
- **Mesures** : S-mètre et ROS à aiguille ; en émission, puissance émise et ALC.
- **Réception** : volume, gain HF, squelch.
- **Émission** : puissance, gain micro, MOX, VOX, processeur.
- **CW** : keyer, BK-IN, ZIN, vitesse.
- **Filtres** : largeur, IF shift, contour, notch manuel, DNR et son niveau,
  NAR, NB, DNF, APF.
- **Clarifier et relais FM** : RX/TX clarifier, pas de ±10/±100 Hz, CLR,
  décalage relais, mode de tonalité, fréquence CTCSS.
- **Mémoires** (bouton « Mémoires ») : lecture des 117 canaux avec leurs noms,
  rappel par double-clic, export CSV.

Si le poste refuse une commande (« ?; »), le bouton correspondant est grisé
au lieu de couper la liaison.

## Partager le CAT avec WSJT-X

1. Dans CAT Pilot : connecter le poste, cocher « Serveur rigctld » (port 4532).
2. Dans WSJT-X > Paramètres > Radio :
   - Radio : **Hamlib NET rigctl**
   - Serveur CAT : **127.0.0.1:4532**
   - Méthode PTT : **CAT**
   - Mode : **Data/Pkt**, Split : **Aucun** (ou « Fake It »)
3. Cliquer sur « Tester le CAT ».

Si un logiciel se déconnecte pendant qu'il est en émission, CAT Pilot coupe le
PTT par sécurité. Même chose à la fermeture de CAT Pilot.

## À valider sur le poste

Cette version n'a été testée que contre un FT-991A simulé. Points à vérifier
lors du premier essai : la commande Split, les largeurs de filtre affichées
(indicatives), le notch manuel et le contour, le coupleur.

## Pas encore inclus

Écriture des mémoires, mémoires rapides (QMB), messages CW, égaliseur micro,
spectre (le scope du FT-991A n'est pas transmis par le CAT).
