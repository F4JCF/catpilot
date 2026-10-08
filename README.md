# CAT Pilot 0.8 — Yaesu FT-991A, FT-891 et Icom IC-705

Logiciel de pilotage CAT des Yaesu FT-991A, FT-891 et de l'Icom IC-705 sous Windows, avec partage du CAT
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
- **Chute d'eau** : analyse de l'audio de réception du codec USB du poste
  (« USB Audio CODEC », présélectionné), sur environ 3 kHz autour de la
  fréquence affichée, comme dans WSJT-X. Le survol indique la fréquence réelle.
  Réglages : contraste et seuil. Le CAT du FT-991A ne transmet pas les données
  de son propre scope, d'où ce choix.
- **Réception** : volume, gain HF, squelch.
- **Émission** : puissance, gain micro, MOX, VOX, processeur.
- **CW** : keyer, BK-IN, ZIN, vitesse.
- **Filtres** : largeur, IF shift, contour, notch manuel, DNR et son niveau,
  NAR, NB, DNF, APF.
- **Clarifier et relais FM** : RX/TX clarifier, pas de ±10/±100 Hz, CLR,
  décalage relais, mode de tonalité, fréquence CTCSS.
- **QMB** : mémoires rapides (STO / RCL) dans le cadre VFO.

### Trafic au quotidien
- **Profils** (barre du haut) : « FT8 20 m », « BLU 40 m »… règlent d'un clic
  fréquence, mode, puissance et filtres. « Enregistrer… » crée un profil à
  partir des réglages actuels.
- **Puissance mémorisée par bande** : chaque bande retrouve sa dernière puissance.
- **Sécurité TX** : coupure de l'émission au-delà d'une durée réglable, quel que
  soit le logiciel qui émet (3 min par défaut, 0 = désactivée).
- **Clic sur la chute d'eau** : en BLU, DATA ou CW, le poste s'accorde sur le
  signal cliqué ; la ligne pointillée montre où il sera placé (1500 Hz, ou la
  note CW du poste).
- **Raccourcis** (menu Aide) : F12 = MOX, Ctrl+↑/↓ = accord, Page préc./suiv. =
  bande, Ctrl+M = mémoires, Ctrl+W = chute d'eau, Échap = arrêt du scan. Un
  bouton d'accord USB se programme pour envoyer Ctrl+↑ / Ctrl+↓.

### Mémoires et scan (bouton « Mémoires »)
- Lecture des 117 canaux avec leurs noms ; en mode mémoire, le nom s'affiche à
  côté du numéro. Double-clic sur le numéro : rappel.
- **Édition** : double-clic sur le nom, la fréquence, le mode, le relais ou la
  tonalité. Les lignes modifiées passent en jaune. « Ajouter un canal » crée un
  canal libre avec la fréquence actuelle.
- **Import / export CSV** (séparateur « ; »), colonnes : Canal, Nom, Fréquence
  (MHz), Mode, Relais (+, −), Tonalité (TSQ, Tone, DCS).
- **Écrire dans le poste** : envoie les lignes en jaune, puis les relit pour
  vérifier. Les mémoires du poste sont d'abord sauvegardées automatiquement dans
  Documents\CATPilot\sauvegardes. La fréquence de la tonalité CTCSS n'est pas
  transmise par cette commande : à régler sur le poste si besoin.
- **Scan** des mémoires du tableau ou d'une plage de fréquences, arrêt sur
  signal au-dessus du seuil choisi, écoute de quelques secondes puis reprise
  (0 s = arrêt définitif sur le signal).

### Horloge et propagation (barre du haut)
- Heure UTC (et locale), flux solaire, indices A et K, taches solaires, et état
  des bandes 80-40 / 30-20 / 17-15 / 12-10 (vert bonne, orange moyenne, rouge
  mauvaise, jour ou nuit selon l'heure locale). Données hamqsl.com (N0NBH),
  actualisées toutes les 30 min ou par un clic. Détails dans l'infobulle.

### CW au clavier (bouton « CW clavier »)
- Texte libre, 5 messages programmables (F1 à F5 ou Alt+F1 à F5) avec
  {MYCALL}, {CALL}, <BT>, <SK>, <AR>, <KN>, et lecture des 5 mémoires du keyer
  du poste. La vitesse est celle du keyer du poste (curseur du cadre CW).
- Deux méthodes : **mémoire 5 du keyer du poste** (CAT, rien à régler, mais
  cette mémoire est réécrite ; un message déjà parti se termine même après
  Stop), ou **ligne DTR / RTS du port COM Standard** (régler le menu PC KEYING
  du poste ; CAT Pilot active BK-IN si besoin).

### Enregistrement de la réception
- « ● Enregistrer » sous la chute d'eau : fichier WAV de l'audio reçu, nommé avec
  la date, la fréquence et le mode, dans Documents\CATPilot\enregistrements.

### Audio d'émission (bouton « Audio TX »)
- Égaliseur micro marche/arrêt, processeur et son niveau, moniteur et son
  niveau, VOX et son gain. Le réglage fin de l'égaliseur (3 bandes) se fait dans
  l'**éditeur des menus** (bouton « Menus de l'égaliseur… »), avec sauvegarde
  automatique avant la première modification. Les noms de menus affichés sont
  indicatifs : à comparer avec l'écran du poste avant d'écrire.

### FT-891
- Même interface ; 2 m, 70 cm et C4FM sont masqués. Le FT-891 n'a pas de carte
  son USB : pour la chute d'eau et l'enregistrement, choisir l'entrée d'une
  interface audio externe (SCU-17…). Menus en groupe-item (05-06 = CAT RATE).

### Mise à jour (menu « Mise à jour », à côté de « Aide »)
- « Vérifier les mises à jour… » consulte la dernière version publiée sur
  GitHub ; « Mettre à jour maintenant » télécharge CATPilot.exe, vérifie son
  empreinte, ferme le logiciel, remplace l'exécutable et le relance (le poste
  n'est pas éteint pendant ce redémarrage).
- Vérification automatique au démarrage (désactivable) ; un « ● » sur le menu
  signale une nouvelle version.
- Chaque changement du numéro de version publie automatiquement une
  « Release » sur GitHub. Le dépôt doit être **public** pour que les
  exécutables déjà installés puissent la télécharger.

### Icom IC-705
- Choisir « Icom IC-705 », le port COM du câble USB, vitesse **115200**.
  Sur le poste : MENU > SET > Connectors > CI-V : CI-V USB Baud Rate « Auto »
  (ou 115200), adresse CI-V **A4h** (par défaut).
- Pris en charge : fréquence, VFO B, A/B, split, modes (dont DATA), PTT,
  S-mètre, puissance (0,5 à 10 W), ROS, ALC, volume, gain HF, squelch, micro,
  processeur, VOX, moniteur, NB, NR, notch auto et manuel, ATT, préampli, AGC,
  break-in, vitesse et note CW, RIT/ΔTX, décalage relais et CTCSS, CW au clavier
  (commande CI-V directe), allumage/extinction, chute d'eau (codec USB intégré).
- Grisés car sans équivalent : largeur et shift façon Yaesu, contour, APF,
  NAR, keyer, QMB, mémoires du keyer. Pas encore pris en charge : lecture et
  écriture des mémoires, sauvegarde des menus, mode DV.

### Sauvegarde du poste (menu « Poste »)
- **Sauvegarder les menus du poste** : tous les réglages du menu, plus les
  mémoires si elles ont été lues, dans un fichier .json.
- **Restaurer les menus du poste** : seuls les réglages différents sont
  réécrits puis vérifiés. Les menus CAT 031 à 033 ne sont jamais modifiés.

**Marche / arrêt** (cases sous la barre de liaison, cochées par défaut) :
- se connecter automatiquement au lancement du logiciel (avec le dernier port utilisé) ;
- allumer le poste à la connexion (commande CAT PS1) ;
- éteindre le poste à la fermeture du logiciel (commande CAT PS0). Le bouton
  « Déconnecter » seul n'éteint jamais le poste.

Pour l'allumage, le poste doit rester alimenté en 13,8 V et relié en USB.

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

Points à vérifier au premier essai : l'écriture d'une mémoire (essayer d'abord
sur un canal libre), la restauration des menus, les QMB, la CW par le keyer du
poste, les réglages du cadre « Audio TX » (ils se grisent si le poste les
refuse), et l'ensemble des fonctions sur le FT-891, qui n'a été testé qu'avec
un poste simulé.

## Pas encore inclus

DX cluster, spots POTA/SOTA, carnet de trafic,
panoramique large de toute la bande (il faudrait un SDR branché sur le poste).
