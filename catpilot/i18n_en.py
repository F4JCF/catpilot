"""Traduction anglaise de l'interface (textes fixes et modèles de textes variables)."""

EXACT = {
    # --- menus et barre d'outils
    "Poste": "Radio", "Affichage": "View", "Carnet": "Log", "Aide": "Help", "Mise à jour": "Update",
    "Mise à jour ●": "Update ●", "Outils": "Tools", "Profil": "Profile", " Profil ": " Profile ",
    "Appliquer": "Apply", "Enregistrer…": "Save…", "Supprimer": "Delete",
    "Puissance mémorisée par bande": "Power remembered per band",
    "Chaque bande retrouve la dernière puissance utilisée": "Each band gets back its last used power",
    "Sécurité TX : coupure après ": "TX safety: cut after ", "désactivée": "off",
    "Coupe l'émission si elle dure plus longtemps (quel que soit le logiciel)":
        "Stops transmitting if it lasts longer (whatever program is transmitting)",
    "Heure UTC (heure locale entre parenthèses)": "UTC time (local time in brackets)",
    "Locator ?": "Locator ?", "Position de la station. Clic : régler": "Station position. Click: set",
    "Propagation…": "Propagation…", "Propagation : indisponible": "Propagation: unavailable",
    "Clic : actualiser": "Click: refresh",
    "Règle le poste selon le profil choisi": "Sets the radio from the chosen profile",
    "Crée un profil à partir des réglages actuels": "Creates a profile from the current settings",
    "Allumer et connecter": "Power on and connect", "Éteindre et déconnecter": "Power off and disconnect",
    "Sauvegarder les menus du poste…": "Back up the radio menus…",
    "Restaurer les menus du poste…": "Restore the radio menus…",
    "Ouvrir le dossier des sauvegardes": "Open the backup folder", "Menus du poste…": "Radio menus…",
    "Position de la station…": "Station position…",
    "Couper l'émission hors des bandes amateurs": "Cut transmission outside amateur bands",
    "Spots POTA, SOTA et DX": "POTA, SOTA and DX spots", "Carnet de trafic": "Logbook",
    "Mémoires et scan": "Memories and scan", "CW au clavier": "CW keyboard",
    "Messages vocaux": "Voice messages", "Audio d'émission": "TX audio", "Rotor d'antenne": "Antenna rotator",
    "Satellites": "Satellites", "Panoramique SDR": "SDR panadapter", "Accès à distance": "Remote access",
    "Mode compact": "Compact mode", "Mode nuit": "Night mode", "Taille du texte": "Text size",
    "Langue": "Language",
    "Ouvrir le carnet": "Open the log", "Importer un fichier ADIF…": "Import an ADIF file…",
    "Exporter tout le carnet en ADIF…": "Export the whole log to ADIF…",
    "Exporter l'activation du jour (POTA/SOTA)…": "Export today's activation (POTA/SOTA)…",
    "Réglages : indicatif et HamQTH…": "Settings: callsign and HamQTH…",
    "Réglages : indicatif, QRZ.com et HamQTH…": "Settings: callsign, QRZ.com and HamQTH…",
    "Raccourcis clavier": "Keyboard shortcuts", "À propos de CAT Pilot": "About CAT Pilot",
    "Vérifier les mises à jour…": "Check for updates…", "Vérifier au démarrage": "Check at startup",
    "Voir toutes les versions sur GitHub": "See all versions on GitHub",

    # --- face avant
    "Bandes": "Bands", "RF": "RF", "VFO": "VFO", "Mesures": "Meters", "Mode": "Mode", "CW": "CW",
    "Clarifier et relais FM": "Clarifier and FM repeaters", "Émission": "Transmit", "Réception": "Receive",
    "Filtres": "Filters", "Liaison et partage du CAT": "Connection and CAT sharing",
    "Clic : IPO → AMP 1 → AMP 2": "Click: IPO → AMP 1 → AMP 2", "Tune": "Tune",
    "Molette sur un chiffre pour le régler": "Mouse wheel on a digit to tune it",
    "Fréquence en MHz, par ex. 145.500, puis Entrée": "Frequency in MHz, e.g. 145.500, then Enter",
    "Pas": "Step", "12,5 kHz": "12.5 kHz",
    "Mémoire rapide : enregistrer la fréquence actuelle": "Quick memory: store the current frequency",
    "Mémoire rapide : rappeler (clics successifs = mémoires suivantes)":
        "Quick memory: recall (successive clicks = next memories)",
    "S-mètre": "S-meter", "ROS": "SWR", "Puissance émise": "Output power",
    "Signal de test (sans poste)": "Test signal (no radio)", "Chute d'eau": "Waterfall",
    "Chute d'eau arrêtée": "Waterfall stopped", "Contraste": "Contrast", "Seuil": "Threshold",
    "Contraste de la chute d'eau": "Waterfall contrast",
    "Seuil : plus à droite, moins de bruit de fond visible": "Threshold: further right, less background noise",
    "● Enregistrer": "● Record",
    "Enregistre l'audio de réception en WAV dans Documents\\CATPilot\\enregistrements":
        "Records the received audio as WAV in Documents\\CATPilot\\enregistrements",
    "Clic sur un signal (BLU, CW, DATA) : le poste s'accorde dessus.\nLa ligne pointillée montre où le signal sera placé.":
        "Click on a signal (SSB, CW, DATA): the radio tunes to it.\nThe dotted line shows where the signal will land.",
    "Keyer": "Keyer", "Vitesse": "Speed", "Simplex": "Simplex", "Décalage +": "Shift +", "Décalage −": "Shift −",
    "Sans tonalité": "No tone", "TSQ (enc./déc.)": "TSQ (enc./dec.)", "Tonalité à l'émission": "TX tone",
    "Puissance": "Power", "Micro": "Mic", "Volume": "Volume", "Gain HF": "RF gain", "Squelch": "Squelch",
    "Largeur": "Width", "Shift": "Shift", "Contour": "Contour", "Notch": "Notch", "défaut": "default",
    "Port": "Port", "Actualiser la liste des ports": "Refresh the port list", "Stop": "Stop",
    "Connecter": "Connect", "Déconnecter": "Disconnect", "Serveur rigctld": "rigctld server",
    "WSJT-X : Radio « Hamlib NET rigctl », serveur 127.0.0.1:4532, PTT « CAT »":
        "WSJT-X: Radio \"Hamlib NET rigctl\", server 127.0.0.1:4532, PTT \"CAT\"",
    "arrêté": "stopped", "Mémoires": "Memories", "CW clavier": "CW keyboard", "Audio TX": "TX audio",
    "Spots": "Spots", "WSJT-X": "WSJT-X", "Rotor": "Rotator", "SDR": "SDR", "À distance": "Remote",
    "Panneaux :": "Panels:",
    "Se connecter au lancement du logiciel": "Connect when the program starts",
    "Allumer le poste à la connexion": "Power the radio on when connecting",
    "Éteindre le poste à la fermeture du logiciel": "Power the radio off when closing the program",
    "Le poste doit rester alimenté en 13,8 V et relié en USB": "The radio must stay powered (13.8 V) and on USB",
    "Le poste doit rester alimenté et relié en USB": "The radio must stay powered and on USB",
    "Choisissez le port du FT-991A puis cliquez sur Connecter": "Choose the radio's port, then click Connect",
    "Simulateur (sans poste)": "Simulator (no radio)", "Simulateur": "Simulator",
    "Poste distant (CAT Pilot)": "Remote radio (CAT Pilot)",
    "Ce poste n'a pas de carte son USB : choisissez l'entrée de votre interface audio (SCU-17, Signalink…)":
        "This radio has no USB sound card: choose the input of your audio interface (SCU-17, Signalink…)",
    "VFO B": "VFO B", "Mémoire": "Memory",

    # --- messages généraux
    "Déconnecté": "Disconnected", "Allumage du poste…": "Powering the radio on…", "Poste allumé": "Radio on",
    "Poste déjà allumé": "Radio already on", "Extinction du poste…": "Powering the radio off…",
    "Aucun port": "No port",
    "Aucun port série n'est sélectionné. Branchez le câble USB du poste puis cliquez sur ⟳.":
        "No serial port selected. Plug in the radio's USB cable, then click ⟳.",
    "Connexion impossible": "Cannot connect", "Serveur indisponible": "Server unavailable",
    "Erreur": "Error", "Sauvegarde": "Backup", "Restauration": "Restore", "Menus": "Menus",
    "Connectez d'abord le poste.": "Connect the radio first.",
    "Connectez d'abord le poste : le profil reprend ses réglages actuels.":
        "Connect the radio first: the profile takes its current settings.",
    "Nouveau profil": "New profile", "Nom du profil :": "Profile name:",
    "Inclure la fréquence et le mode actuels ?\n\nNon : le profil ne changera que les réglages (puissance, filtres…).":
        "Include the current frequency and mode?\n\nNo: the profile will only change settings (power, filters…).",
    "Éteindre": "Power off", "Éteindre le FT-991A ?": "Power the radio off?",
    "Restaurer une sauvegarde": "Restore a backup", "Sauvegarde (*.json)": "Backup (*.json)",
    "Fichier illisible": "Unreadable file", "Restaurer les menus": "Restore menus",
    "Mémoires": "Memories", "Enregistrer la sauvegarde": "Save the backup", "Sauvegarde terminée": "Backup finished",
    "Le poste n'a renvoyé aucun menu.": "The radio returned no menu.",
    "Restauration des menus": "Menu restore",
    " (mémoires non incluses : lisez-les d'abord pour les ajouter)":
        " (memories not included: read them first to add them)",
    "Position de la station": "Station position", "Locator saisi": "Locator entered",
    "ex. JN33LP": "e.g. JN33LP", "GPS du poste (IC-705)": "Radio GPS (IC-705)",
    "GPS NMEA sur un port COM (GPS USB, sortie GPS de l'IC-705…)": "NMEA GPS on a COM port (USB GPS, IC-705 GPS output…)",
    "Le locator saisi sert aussi de position de secours quand le GPS n'a pas de position.":
        "The entered locator is also the fallback position when the GPS has no fix.",
    "Position": "Position", "GPS du poste": "radio GPS", "locator saisi": "entered locator", "GPS NMEA": "NMEA GPS",
    "Hors des bandes amateurs": "Outside the amateur bands",
    "Plan de bandes IARU Région 1, à titre indicatif": "IARU Region 1 band plan, for guidance only",
    "Numérique": "Digital", "BLU et tous modes": "SSB and all modes", "Tous modes": "All modes",
    "Balises (ne pas émettre)": "Beacons (do not transmit)", "FM simplex": "FM simplex",
    "Relais FM": "FM repeaters", "Satellites (ne pas émettre en terrestre)": "Satellites (no terrestrial TX)",
    "Garde": "Guard",
    "Mise à jour disponible": "Update available", "Mettre à jour maintenant": "Update now",
    "Plus tard": "Later", "Ignorer cette version": "Skip this version",
    "Le logiciel sera fermé, mis à jour puis relancé automatiquement.":
        "The program will close, update and restart automatically.",
    "Mise à jour automatique possible uniquement avec CATPilot.exe : la page de téléchargement va s'ouvrir.":
        "Automatic update only works with CATPilot.exe: the download page will open.",
    "Le poste est en émission : réessayez après.": "The radio is transmitting: try again afterwards.",
    "Annuler": "Cancel", "Mise à jour : redémarrage de CAT Pilot…": "Update: restarting CAT Pilot…",
    "aucune version publiée n'est accessible (dépôt privé, ou pas encore de version publiée)":
        "no published version is reachable (private repository, or nothing published yet)",
    "l'empreinte du fichier ne correspond pas : téléchargement corrompu": "file checksum mismatch: corrupted download",
    "téléchargement annulé": "download cancelled", "fichier incomplet": "incomplete file",
    "Redémarrer maintenant": "Restart now",
    "La langue sera changée au prochain démarrage de CAT Pilot.": "The language will change the next time CAT Pilot starts.",

    # --- panneaux annexes : CW, audio TX, éditeur de menus
    "Mémoire 5 du keyer du poste (CAT)": "Radio keyer memory 5 (CAT)",
    "Ligne DTR du port Standard": "DTR line of the Standard port", "Ligne RTS du port Standard": "RTS line of the Standard port",
    "CAT : rien à régler, mais la mémoire 5 du keyer du poste est réécrite.\nDTR / RTS : régler le menu PC KEYING du poste sur DTR (ou RTS).":
        "CAT: nothing to set, but the radio's keyer memory 5 is overwritten.\nDTR / RTS: set the radio's PC KEYING menu to DTR (or RTS).",
    "Mon indicatif": "My callsign", "Correspondant": "Other station", "Indicatif": "Callsign", "Corresp.": "Other",
    "Texte à émettre en CW, puis Entrée": "Text to send in CW, then Enter", "Émettre": "Send",
    "Messages programmables  ({MYCALL}, {CALL}, <BT>, <SK>, <AR>, <KN>)":
        "Programmable messages  ({MYCALL}, {CALL}, <BT>, <SK>, <AR>, <KN>)",
    "Messages enregistrés dans le poste": "Messages stored in the radio", "Pas de poste connecté": "No radio connected",
    "Le poste n'est pas en CW. Passer en CW ?": "The radio is not in CW. Switch to CW?",
    "Arrêt demandé (un message déjà transmis au poste se termine)": "Stop requested (a message already sent to the radio will finish)",
    "Arrêté": "Stopped", "Égaliseur micro": "Mic equalizer", "Processeur": "Processor", "Moniteur": "Monitor",
    "Réglage fin de l'égaliseur (fréquence, niveau et largeur des 3 bandes) et des filtres d'émission : par les menus du poste.":
        "Fine equalizer settings (frequency, level and width of the 3 bands) and TX filters: through the radio menus.",
    "Menus de l'égaliseur…": "Equalizer menus…", "Tous les menus…": "All menus…", "Menus du poste": "Radio menus",
    "Les noms sont indicatifs : comparez avec le menu affiché sur le poste avant de modifier. Une sauvegarde complète des menus est faite avant la première écriture. Les valeurs sont celles du protocole CAT, pas toujours celles de l'écran.":
        "Names are for guidance: compare with the menu shown on the radio before changing anything. A full menu backup is made before the first write. Values are those of the CAT protocol, not always those on the display.",
    "Filtrer (numéro ou nom, ex. EQ, POWER, CW)": "Filter (number or name, e.g. EQ, POWER, CW)",
    "Lire depuis le poste": "Read from the radio", "Menu": "Menu", "Nom (indicatif)": "Name (guidance)",
    "Valeur CAT": "CAT value", "Écrire les modifications": "Write changes", "Fermer": "Close",
    "Lecture des menus…": "Reading menus…", "Écrire les menus": "Write menus", "Écriture en cours…": "Writing…",

    # --- mémoires et scan
    "Canal": "Channel", "Nom": "Name", "Fréquence": "Frequency", "Relais": "Repeater", "Tonalité": "Tone",
    "Lire les mémoires": "Read memories", "Rappeler": "Recall", "Ajouter un canal": "Add a channel",
    "Nouveau canal libre avec la fréquence et le mode actuels": "New free channel with the current frequency and mode",
    "Écrire dans le poste": "Write to the radio", "Envoie au poste les lignes modifiées (en jaune)":
        "Sends the changed rows (in yellow) to the radio",
    "Importer CSV": "Import CSV", "Exporter CSV": "Export CSV", "Groupe de mémoires": "Memory group",
    "L'IC-705 range ses mémoires en 100 groupes de 100 canaux": "The IC-705 stores memories in 100 groups of 100 channels",
    "Double-clic sur le numéro : rappeler la mémoire.\nDouble-clic sur une autre colonne : modifier.":
        "Double-click the number: recall the memory.\nDouble-click another column: edit.",
    "Scan": "Scan", "Mémoires du tableau": "Memories in the table", "Plage de fréquences": "Frequency range",
    "De (MHz)": "From (MHz)", "À (MHz)": "To (MHz)", "Écoute": "Listen",
    "Temps d'écoute sur un signal avant de repartir (0 = arrêt sur le signal)":
        "Listening time on a signal before moving on (0 = stop on the signal)",
    "Démarrer le scan": "Start scan", "Arrêter le scan": "Stop scan", "Scan arrêté": "Scan stopped",
    "Scan arrêté (émission ou liaison coupée)": "Scan stopped (transmitting or link lost)",
    "Lisez d'abord les mémoires": "Read the memories first",
    "Plus de place": "No room left", "Aucune mémoire": "No memory", "Lisez d'abord les mémoires du poste.": "Read the radio's memories first.",
    "Exporter les mémoires": "Export memories", "Importer des mémoires": "Import memories",
    "Import impossible": "Import failed", "Import terminé": "Import finished", "Valeur refusée": "Value rejected",
    "Lecture nécessaire": "Reading needed",
    "Lisez d'abord les mémoires du poste : elles servent de modèle pour l'écriture et sont sauvegardées avant toute modification.":
        "Read the radio's memories first: they are the template for writing and are backed up before any change.",
    "Rien à écrire": "Nothing to write", "Aucune ligne modifiée.": "No changed row.",
    "Écriture terminée": "Writing finished", "fréquence vide": "empty frequency",

    # --- position, plan, rotor
    "Rotor simulé": "Simulated rotator", "Yaesu GS-232 (port série)": "Yaesu GS-232 (serial port)",
    "rotctld (Hamlib, réseau)": "rotctld (Hamlib, network)", "Cap": "Heading", "Aller": "Go",
    "Viser un locator (ex. JO40)": "Point at a locator (e.g. JO40)", "Long path": "Long path",
    "Orienter vers les spots, le carnet et WSJT-X (double-clic)": "Turn towards spots, log and WSJT-X (double-click)",
    "Clic : orienter l'antenne dans cette direction": "Click: turn the antenna this way",
    "Connectez d'abord le rotor": "Connect the rotator first", "Rotor connecté": "Rotator connected",
    "Indiquez d'abord la position de la station (menu Poste)": "Set the station position first (Radio menu)",
    "le rotor ne répond pas": "the rotator does not answer", "O": "W",

    # --- satellites, SDR
    "Filtrer (ex. ISS, SO-50, RS-44)": "Filter (e.g. ISS, SO-50, RS-44)",
    "Seulement avec liaison montante": "Only with an uplink", "Satellite": "Satellite", "Transpondeur": "Transponder",
    "Suivre ce satellite": "Track this satellite", "Piloter le rotor": "Drive the rotator",
    "Règle le poste (VFO A réception, VFO B émission en split) et corrige le Doppler en continu. Tournez le VFO pour vous déplacer dans un transpondeur linéaire : l'émission suit.":
        "Sets the radio (VFO A receive, VFO B transmit in split) and corrects Doppler continuously. Turn the VFO to move across a linear transponder: transmit follows.",
    "Passages au-dessus de": "Passes above", "Actualiser les données": "Refresh data", "Date": "Date",
    "AOS": "AOS", "LOS": "LOS", "Élév. max": "Max elev.", "Azimuts": "Azimuths", "Durée": "Duration",
    "Chargement des orbites…": "Loading orbits…", "Suivi arrêté": "Tracking stopped", "en cours": "now",
    "Connectez le poste et choisissez un transpondeur": "Connect the radio and choose a transponder",
    "Indiquez la position de la station (menu Poste) pour calculer les passages":
        "Set the station position (Radio menu) to compute passes",
    "ISS — relais FM": "ISS — FM repeater", "ISS — phonie FM (Région 1)": "ISS — FM voice (Region 1)",
    "ISS — APRS": "ISS — APRS", "SO-50 — relais FM": "SO-50 — FM repeater", "PO-101 — relais FM": "PO-101 — FM repeater",
    "RS-44 — transpondeur linéaire": "RS-44 — linear transponder", "AO-7 — mode B linéaire": "AO-7 — mode B linear",
    "rtl_tcp (réseau)": "rtl_tcp (network)", "Clé RTL-SDR USB": "RTL-SDR USB dongle", "Démarrer": "Start",
    "Arrêter": "Stop", "Convertisseur": "Converter", "Gain": "Gain",
    "Décalage d'un convertisseur : 125 MHz pour un Ham It Up": "Converter offset: 125 MHz for a Ham It Up",
    "Échantillonnage direct (HF, clé V3)": "Direct sampling (HF, V3 dongle)",
    "Gain (tout à gauche : automatique)": "Gain (far left: automatic)",
    "Antenne séparée ou coupleur protégé obligatoire : jamais sur la sortie de l'émetteur.":
        "Separate antenna or protected coupler required: never on the transmitter output.",
    "Clic : accorder le poste sur ce signal": "Click: tune the radio to this signal",
    "SDR en marche. Clic sur un signal : le poste s'y accorde.": "SDR running. Click on a signal: the radio tunes to it.",

    # --- spots, carnet, WSJT-X
    "Bande": "Band", "Toutes": "All", "Tous": "All", "Phonie": "Phone", "Bandes de mon poste": "My radio's bands",
    "Actualiser": "Refresh", "UTC": "UTC", "Référence": "Reference", "Infos": "Info", "Distance": "Distance",
    "DX cluster": "DX cluster", "Cluster": "Cluster", "Adresse:port du cluster (DXSpider, AR-Cluster…)":
        "Cluster address:port (DXSpider, AR-Cluster…)",
    "Double-clic : accorder le poste et préparer le QSO dans le carnet": "Double-click: tune the radio and prepare the QSO in the log",
    "Actualisation": "Refresh", "manuelle": "manual", "Actualisation…": "Refreshing…",
    "Adresse du cluster au format hôte:port": "Cluster address as host:port",
    "Indiquez votre indicatif (menu Carnet > Réglages)": "Enter your callsign (Log menu > Settings)",
    "Cluster déconnecté": "Cluster disconnected",
    "Indicatif, puis Entrée": "Callsign, then Enter", "QTH": "QTH", "Locator": "Locator", "RST envoyé": "RST sent",
    "RST reçu": "RST rcvd", "Sa réf. POTA/SOTA": "Their POTA/SOTA ref.", "Ma réf. (activation)": "My ref. (activation)",
    "ex. FR-0123 ou F/AM-123": "e.g. FR-0123 or F/AM-123", "votre référence en activation": "your reference when activating",
    "Commentaire": "Comment", "Enregistrer le QSO": "Save QSO",
    "Raccourci : Entrée dans le champ Commentaire, ou Ctrl+L": "Shortcut: Enter in the Comment field, or Ctrl+L",
    "Effacer": "Clear", "Rechercher un indicatif dans le carnet": "Search a callsign in the log",
    "Env.": "Sent", "Reçu": "Rcvd", "Réf.": "Ref.", "Importer ADIF": "Import ADIF", "Exporter ADIF": "Export ADIF",
    "Exporter une activation": "Export an activation", "Nouvel indicatif": "New callsign",
    "Indicatif manquant": "Callsign missing", "Importer un fichier ADIF": "Import an ADIF file",
    "Exporter en ADIF": "Export to ADIF", "Import ADIF": "ADIF import", "Activation": "Activation",
    "Indiquez votre référence dans « Ma réf. (activation) ».": "Enter your reference in \"My ref. (activation)\".",
    "Réception : décodeur CW (audio USB du poste, comme la chute d'eau)": "Receive: CW decoder (radio USB audio, like the waterfall)",
    "Décoder": "Decode", "Note auto": "Auto tone",
    "Décoder le morse reçu. Lance la chute d'eau si besoin.": "Decode received Morse. Starts the waterfall if needed.",
    "Coché : suit le signal CW le plus fort (300 à 1500 Hz).\nDécoché : décode sur la tonalité CW du poste (PITCH) ;\nun clic sur un signal dans la chute d'eau l'y amène.":
        "Checked: follows the strongest CW signal (300 to 1500 Hz).\nUnchecked: decodes on the radio's CW pitch;\nclicking a signal in the waterfall brings it there.",
    "Signal décodé (le seuil s'adapte tout seul)": "Decoded signal (the threshold adapts by itself)",
    "Le texte reçu s'affiche ici. Double-clic sur un indicatif : il passe dans Correspondant et dans le carnet.":
        "Received text shows here. Double-click a callsign to put it in Other station and in the log.",
    "Choisissez l'entrée audio du poste (chute d'eau)": "Choose the radio's audio input (waterfall)",
    "Compte QRZ.com": "QRZ.com account", "Mot de passe QRZ.com": "QRZ.com password",
    "Ouvrir la fiche de l'indicatif sur QRZ.com": "Open the callsign page on QRZ.com",
    "Ouvrir la fiche de l'indicatif sur HamQTH.com": "Open the callsign page on HamQTH.com",
    "Les deux comptes sont facultatifs. HamQTH.com est gratuit et donne nom, QTH et locator. QRZ.com donne la fiche complète avec un abonnement XML, et seulement une partie sans. Sans compte, CAT Pilot trouve quand même le pays et les zones, et les indicatifs américains via callook.info. Les mots de passe sont enregistrés sur ce PC.":
        "Both accounts are optional. HamQTH.com is free and gives name, QTH and locator. QRZ.com gives the full record with an XML subscription, and only part of it without. Without an account, CAT Pilot still finds the country and zones, and US callsigns via callook.info. Passwords are stored on this PC.",
    "Indicatif inconnu": "Unknown callsign",
    "Réglages du carnet": "Log settings", "Compte HamQTH": "HamQTH account", "Mot de passe HamQTH": "HamQTH password",
    "Compte gratuit sur hamqth.com. Le mot de passe est enregistré sur ce PC.":
        "Free account on hamqth.com. The password is stored on this PC.",
    "Indiquez votre compte HamQTH (menu Carnet > Réglages)": "Enter your HamQTH account (Log menu > Settings)",
    "connexion refusée": "login refused",
    "Port UDP": "UDP port", "multicast (facultatif)": "multicast (optional)",
    "Ex. 224.0.0.1 si JTAlert ou GridTracker écoutent aussi WSJT-X": "E.g. 224.0.0.1 if JTAlert or GridTracker also listen to WSJT-X",
    "Écouter WSJT-X": "Listen to WSJT-X", "Inscrire au carnet les QSO journalisés dans WSJT-X": "Add QSOs logged in WSJT-X to the log",
    "Seulement les CQ": "CQ only", "Vider": "Clear", "SNR": "SNR", "DF": "DF", "Message": "Message",
    "Double-clic : demander à WSJT-X d'appeler cette station.\nVert : CQ d'un indicatif jamais contacté.":
        "Double-click: ask WSJT-X to call this station.\nGreen: CQ from a callsign never worked.",
    "En écoute de WSJT-X…": "Listening to WSJT-X…",

    # --- messages vocaux
    "Micro du PC": "PC microphone", "Sortie vers le poste": "Output to the radio", "Niveau d'émission": "TX level",
    "Réglez pour que l'ALC bouge à peine pendant le message": "Set so that ALC barely moves during the message",
    "Module audio indisponible sur cet ordinateur.": "Audio module unavailable on this computer.",
    "Passer en DATA pendant le message (modulation par l'USB)": "Switch to DATA during the message (USB modulation)",
    "Le poste prend sa modulation sur l'USB en mode DATA. Sans cette option, réglez la source de modulation de la BLU sur USB dans les menus du poste.":
        "The radio takes its modulation from USB in DATA mode. Without this option, set the SSB modulation source to USB in the radio menus.",
    "Répéter toutes les": "Repeat every", "non": "no",
    "Appel en boucle : le message repart après ce délai d'écoute. Toute action sur MOX ou Échap arrête la boucle.":
        "Loop call: the message restarts after this listening delay. MOX or Esc stops the loop.",
    "Clic : renommer": "Click: rename", "● Enr.": "● Rec.", "Enregistrer au micro du PC ; recliquer pour arrêter":
        "Record from the PC microphone; click again to stop", "Écouter": "Listen",
    "Émettre ce message (Ctrl+F1 à Ctrl+F4 pour les quatre premiers)": "Send this message (Ctrl+F1 to Ctrl+F4 for the first four)",
    "CQ": "CQ", "Report 59": "Report 59", "Merci 73": "Thanks 73", "QRZ ?": "QRZ?",
    "Nom du message": "Message name", "Nom :": "Name:", "Aucun micro disponible": "No microphone available",
    "Enregistrement trop court, rien n'a été gardé": "Recording too short, nothing kept",
    "Ce message n'est pas encore enregistré": "This message is not recorded yet",
    "Émission déjà en cours": "Already transmitting", "Choisissez la sortie audio reliée au poste.": "Choose the audio output connected to the radio.",
    "Message émis": "Message sent", "Message interrompu": "Message interrupted",

    # --- accès à distance
    "Ce PC est relié au poste (station)": "This PC is connected to the radio (station)", "Port TCP": "TCP port",
    "Mot de passe": "Password", "6 caractères au moins": "at least 6 characters",
    "Audio venant du poste": "Audio from the radio", "Audio vers le poste": "Audio to the radio",
    "Autoriser l'accès à distance": "Allow remote access", "Pas d'audio": "No audio",
    "Ce PC pilote une station distante": "This PC controls a remote station", "Station": "Station",
    "adresse:4540 (IP, nom ou adresse VPN)": "address:4540 (IP, name or VPN address)",
    "Micro de ce PC": "This PC's microphone", "Haut-parleurs de ce PC": "This PC's speakers",
    "Puis choisissez « Poste distant (CAT Pilot) » dans la liste des postes et cliquez sur Connecter. Pour Internet, passez de préférence par un VPN (WireGuard, Tailscale).":
        "Then choose \"Remote radio (CAT Pilot)\" in the radio list and click Connect. Over the Internet, preferably use a VPN (WireGuard, Tailscale).",
    "Module audio indisponible : pilotage sans audio.": "Audio module unavailable: control without audio.",
    "En attente de connexion": "Waiting for a connection", "Poste distant": "Remote radio",
    "Indiquez l'adresse de la station et son mot de passe dans le panneau « Accès à distance ».":
        "Enter the station address and password in the \"Remote access\" panel.",
    "mot de passe refusé par la station": "password refused by the station",
    "ce n'est pas une station CAT Pilot": "this is not a CAT Pilot station",
    "mot de passe trop court (6 caractères au moins)": "password too short (at least 6 characters)",
    "Émission distante coupée : plus d'audio reçu": "Remote transmission cut: no more audio received",

    # --- compact
    "Fenêtre complète": "Full window", "Au premier plan": "Always on top",

    # --- erreurs des pilotes
    "le poste ne s'est pas allumé (alimentation 13,8 V coupée ?)": "the radio did not power on (13.8 V supply off?)",
    "l'IC-705 ne s'est pas allumé (batterie ou alimentation ?)": "the IC-705 did not power on (battery or supply?)",
    "liaison perdue pendant la restauration ; vérifiez la vitesse CAT du poste": "link lost during restore; check the radio's CAT speed",
    "liaison perdue pendant la restauration ; vérifiez le poste": "link lost during restore; check the radio",
    "lisez d'abord les mémoires : un canal programmé sert de modèle": "read the memories first: a programmed channel is the template",
    "liaison distante perdue": "remote link lost", "liaison fermée": "link closed",
}

# Modèles : « {} » = partie variable. Ordre des parties conservé.
TEMPLATES = {
    "Connecté : {} sur {}": "Connected: {} on {}",
    "Poste allumé : {} sur {}": "Radio on: {} on {}", "Poste déjà allumé : {} sur {}": "Radio already on: {} on {}",
    "Allumage impossible : {}": "Power-on failed: {}", "Liaison perdue avec le poste : {}": "Link to the radio lost: {}",
    "CAT Pilot {} — {}": "CAT Pilot {} — {}", "Le port {} n'a pas pu être ouvert.\n\n{}\n\nVérifiez qu'aucun autre logiciel ne l'utilise déjà.":
        "Port {} could not be opened.\n\n{}\n\nCheck that no other program is using it.",
    "La station {} n'a pas pu être jointe.\n\n{}": "Station {} could not be reached.\n\n{}",
    "Le port TCP {} est déjà utilisé.\n\n{}": "TCP port {} is already in use.\n\n{}",
    "{} logiciel connecté": "{} program connected", "{} logiciels connectés": "{} programs connected",
    "Mémoire {}   {}": "Memory {}   {}", "Mémoire {}": "Memory {}", "{} — hors segment du plan": "{} — outside band plan segments",
    "{} — {}  ({} – {} MHz)": "{} — {}  ({} – {} MHz)", "PO {} %": "PO {} %", "ROS ≈ {}": "SWR ≈ {}",
    "{} Hz → {}": "{} Hz → {}", "{} W": "{} W", "{} wpm": "{} wpm", "niveau {}": "level {}", "pos. {}": "pos. {}",
    "UTC {}  ({})": "UTC {}  ({})", "{} — {}°, {}° ({}). Clic : régler": "{} — {}°, {}° ({}). Click: set",
    "Données hamqsl.com inaccessibles ({}). Clic : réessayer": "hamqsl.com data unreachable ({}). Click: retry",
    "Flux solaire {}, indice A {}, indice K {}, taches {}, rayons X {}\nChamp géomagnétique : {}, bruit : {}\n\n{}\n\nSource hamqsl.com (N0NBH), mise à jour {}.\nClic : actualiser":
        "Solar flux {}, A index {}, K index {}, sunspots {}, X-ray {}\nGeomagnetic field: {}, noise: {}\n\n{}\n\nSource hamqsl.com (N0NBH), updated {}.\nClick: refresh",
    "{} : jour {}, nuit {}": "{}: day {}, night {}",
    "Nouvelle version disponible : {}": "New version available: {}",
    "<b>CAT Pilot {}</b> est disponible (vous avez la {}).": "<b>CAT Pilot {}</b> is available (you have {}).",
    "Téléchargement de CAT Pilot {}…": "Downloading CAT Pilot {}…", "Téléchargement… {} / {} Mo": "Downloading… {} / {} MB",
    "Impossible de vérifier les mises à jour.\n\n{}": "Could not check for updates.\n\n{}",
    "Vous avez déjà la dernière version ({}).": "You already have the latest version ({}).",
    "Le téléchargement a échoué.\n\n{}": "The download failed.\n\n{}", "L'installation n'a pas pu démarrer.\n\n{}": "The installation could not start.\n\n{}",
    "erreur HTTP {}": "HTTP error {}",
    "Profil « {} » appliqué": "Profile \"{}\" applied", "Supprimer le profil « {} » ?": "Delete profile \"{}\"?",
    "Bande {} : puissance remise à {} W": "Band {}: power set back to {} W",
    "Sécurité : émission coupée après {} min": "Safety: transmission cut after {} min",
    "Émission coupée : {} est hors des bandes amateurs (option dans le menu Poste)":
        "Transmission cut: {} is outside the amateur bands (option in the Radio menu)",
    "Attention : émission sur {}, hors des bandes amateurs": "Warning: transmitting on {}, outside the amateur bands",
    "« {} » n'est pas une fréquence valide": "\"{}\" is not a valid frequency",
    "« {} » n'est pas un locator valide (ex. JN33LP).": "\"{}\" is not a valid locator (e.g. JN33LP).",
    "Ce fichier n'est pas une sauvegarde CAT Pilot.\n\n{}": "This file is not a CAT Pilot backup.\n\n{}",
    "Sauvegarde du {} : {} menus et {} mémoires.\n\nSeuls les menus différents seront réécrits. Les menus CAT (031 à 033) ne sont jamais modifiés, pour ne pas couper la liaison.\n\nRestaurer les menus ?":
        "Backup of {}: {} menus and {} memories.\n\nOnly different menus will be rewritten. CAT menus are never changed, so the link stays up.\n\nRestore the menus?",
    "Sauvegarde du {} : {} menus.\n\nSeuls les menus différents seront réécrits. Les menus CAT (031 à 033) ne sont jamais modifiés, pour ne pas couper la liaison.\n\nRestaurer les menus ?":
        "Backup of {}: {} menus.\n\nOnly different menus will be rewritten. CAT menus are never changed, so the link stays up.\n\nRestore the menus?",
    "Attention : cette sauvegarde vient d'un {}, le poste connecté est un {}.\n\n{}":
        "Warning: this backup comes from a {}, the connected radio is a {}.\n\n{}",
    "Restaurer aussi les {} mémoires de la sauvegarde ?": "Also restore the {} memories of the backup?",
    "{} menus et {} mémoires enregistrés dans\n{}": "{} menus and {} memories saved to\n{}",
    "{} menus{} enregistrés dans\n{}": "{} menus{} saved to\n{}",
    "Menus modifiés : {}\nDéjà identiques : {}\nNon modifiables ou en échec : {}":
        "Menus changed: {}\nAlready identical: {}\nNot changeable or failed: {}",
    "Enregistrement en cours : {}": "Recording: {}", "Enregistrement terminé ({} s) : {}": "Recording finished ({} s): {}",
    "Impossible de créer le fichier.\n\n{}": "Could not create the file.\n\n{}",
    "L'entrée audio n'a pas pu être ouverte.\n\n{}": "The audio input could not be opened.\n\n{}",
    "CAT Pilot {}\nPilotage CAT de postes Yaesu et Icom\nF4JCF": "CAT Pilot {}\nCAT control for Yaesu and Icom radios\nF4JCF",
    "GPS : port {} impossible à ouvrir ({})": "GPS: port {} cannot be opened ({})", "locator invalide : {}": "invalid locator: {}",
    # CW, menus
    "Émission ({} wpm, ≈ {} s) : {}": "Sending ({} wpm, ≈ {} s): {}", "Émettre ce message (raccourci Alt+F{})": "Send this message (shortcut Alt+F{})",
    "Mém. {}": "Mem. {}", "Faire jouer la mémoire {} du keyer du poste": "Play the radio's keyer memory {}",
    "Mémoire {} du keyer en cours d'émission": "Keyer memory {} being sent",
    "Le port {} n'a pas pu être ouvert.\n\n{}": "Port {} could not be opened.\n\n{}",
    "{} menus lus": "{} menus read", "{} menu(s) modifié(s)": "{} menu(s) changed", "{} menu(s) modifié(s), échec : {}": "{} menu(s) changed, failed: {}",
    "Modifier ces menus du poste ?\n\n{}": "Change these radio menus?\n\n{}",
    # pilotes, travaux longs
    "Lecture des mémoires… {}/{}": "Reading memories… {}/{}", "Écriture des mémoires… {}/{}": "Writing memories… {}/{}",
    "Lecture des menus du poste… {}": "Reading radio menus… {}", "Lecture des menus du poste… groupe {}": "Reading radio menus… group {}",
    "Restauration des menus… {}/{}": "Restoring menus… {}/{}", "commande refusée : {}": "command refused: {}",
    "pas de réponse à {}": "no answer to {}", "pas de réponse CI-V à {}": "no CI-V answer to {}",
    "{} (à distance)": "{} (remote)", "liaison distante perdue : {}": "remote link lost: {}",
    "la lecture des mémoires de l'{} n'est pas encore prise en charge": "reading the {} memories is not supported yet",
    "l'écriture des mémoires de l'{} n'est pas encore prise en charge": "writing the {} memories is not supported yet",
    "la sauvegarde des menus de l'{} n'est pas encore prise en charge": "backing up the {} menus is not supported yet",
    # mémoires
    "{} mémoires lues sur le poste": "{} memories read from the radio", "{} canaux": "{} channels",
    "{} canaux — {} modifié(s), à écrire dans le poste": "{} channels — {} changed, to write to the radio",
    "Mémoires exportées dans {}": "Memories exported to {}",
    "{} canaux importés. Ils sont en jaune : cliquez sur « Écrire dans le poste » pour les envoyer.":
        "{} channels imported. They are in yellow: click \"Write to the radio\" to send them.",
    "{} canaux importés. Ils sont en jaune : cliquez sur « Écrire dans le poste » pour les envoyer.\n\nLignes ignorées :\n{}":
        "{} channels imported. They are in yellow: click \"Write to the radio\" to send them.\n\nIgnored lines:\n{}",
    "Fichier illisible :\n{}": "Unreadable file:\n{}", "Les canaux {} à {} sont tous occupés.": "Channels {} to {} are all used.",
    "Écrire {} canal(aux) dans le {} ?\n\n{}\n\nLes mémoires actuelles du poste seront d'abord sauvegardées.":
        "Write {} channel(s) to the {}?\n\n{}\n\nThe radio's current memories will be backed up first.",
    "Sauvegarde faite dans {} — écriture en cours…": "Backup saved to {} — writing…",
    "{} canal(aux) écrit(s) et vérifié(s).": "{} channel(s) written and checked.",
    "{} canal(aux) écrit(s) et vérifié(s).\n\nÉchec ou vérification impossible pour : {}":
        "{} channel(s) written and checked.\n\nFailed or not checkable: {}",
    "Scan : {}": "Scan: {}", "Signal trouvé : {} ({})": "Signal found: {} ({})", "Écoute : {} ({})": "Listening: {} ({})",
    "canal {} hors limites ({} à {})": "channel {} out of range ({} to {})", "ligne {} : {}": "line {}: {}",
    "fréquence hors limites : {}": "frequency out of range: {}",
    # rotor
    "Rotation vers {}°": "Turning to {}°", "Rotation vers {}°, élévation {}°": "Turning to {}°, elevation {}°",
    "{} : {} km, cap {}°": "{}: {} km, heading {}°", "{} : {} km, cap {}° (long path)": "{}: {} km, heading {}° (long path)",
    "Azimut {}°": "Azimuth {}°", "Azimut {}°   Élévation {}°": "Azimuth {}°   Elevation {}°",
    "Rotor injoignable : {}": "Rotator unreachable: {}", "Rotor : liaison perdue ({})": "Rotator: link lost ({})",
    # satellites, SDR
    "{} satellites — {}": "{} satellites — {}", "Orbites indisponibles : {}": "Orbits unavailable: {}",
    "Orbite inutilisable : {}": "Orbit unusable: {}",
    "Azimut {}°   Élévation {}°   Distance {} km   Vitesse radiale {} km/s":
        "Azimuth {}°   Elevation {}°   Range {} km   Range rate {} km/s",
    "Azimut {}°   Élévation {}°   Distance {} km   Vitesse radiale {} km/s   — VISIBLE":
        "Azimuth {}°   Elevation {}°   Range {} km   Range rate {} km/s   — VISIBLE",
    "Réception {} MHz ({} Hz)": "Receive {} MHz ({} Hz)", "Réception {} MHz ({} Hz)   Émission {} MHz ({} Hz)": "Receive {} MHz ({} Hz)   Transmit {} MHz ({} Hz)",
    "Suivi de {} : réception VFO A, émission VFO B (split)": "Tracking {}: receive VFO A, transmit VFO B (split)",
    "Suivi de {} : réception VFO A, émission VFO B (split), tonalité {} Hz": "Tracking {}: receive VFO A, transmit VFO B (split), tone {} Hz",
    "{} min {}": "{} min {}", "SDR injoignable : {}": "SDR unreachable: {}", "SDR : {}": "SDR: {}",
    "orbites : {} ; transpondeurs : {}": "orbits: {} ; transponders: {}",
    # spots, carnet, WSJT-X
    "Mis à jour à {} UTC": "Updated at {} UTC", "Accordé sur {} {} kHz {}": "Tuned to {} {} kHz {}",
    "Connexion à {}:{}…": "Connecting to {}:{}…", "{} indisponible : {}": "{} unavailable: {}",
    "Cluster injoignable : {}": "Cluster unreachable: {}", "Connecté à {} en tant que {}": "Connected to {} as {}",
    "QSO avec {} enregistré": "QSO with {} saved", "{} QSO": "{} QSOs", "{} QSO importés, {} doublons ignorés.": "{} QSOs imported, {} duplicates skipped.",
    "{} QSO exportés dans {}": "{} QSOs exported to {}", "Supprimer {} QSO du carnet ?": "Delete {} QSO(s) from the log?",
    "Aucun QSO aujourd'hui (UTC) depuis {}.": "No QSO today (UTC) from {}.", "HamQTH injoignable : {}": "HamQTH unreachable: {}",
    "HamQTH : {}": "HamQTH: {}", "Déjà contacté {} fois : {}": "Already worked {} times: {}", "{} trouvé": "{} found",
    "{} Hz · {} mots/min · {} dB": "{} Hz · {} WPM · {} dB", "{} Hz · pas de signal CW": "{} Hz · no CW signal",
    "{} : {}": "{}: {}", "Appel de {} demandé à WSJT-X": "WSJT-X asked to call {}", "Port UDP {} indisponible : {}": "UDP port {} unavailable: {}",
    "QSO WSJT-X avec {} inscrit au carnet": "WSJT-X QSO with {} added to the log", "WSJT-X : {} sur {} MHz": "WSJT-X: {} on {} MHz",
    "WSJT-X : {} sur {} MHz — émission": "WSJT-X: {} on {} MHz — transmitting",
    # messages vocaux
    "Émission de « {} »": "Sending \"{}\"", "Échec de l'émission du message : {}": "Message transmission failed: {}",
    "Enregistrement de « {} »… recliquez pour arrêter": "Recording \"{}\"… click again to stop",
    "{} — reprise dans {} s (Échap pour arrêter)": "{} — again in {} s (Esc to stop)", "Message {}": "Message {}",
    "Émettre F{}": "Send F{}", "« {} » enregistré ({} s)": "\"{}\" recorded ({} s)", "Micro impossible à ouvrir : {}": "Microphone cannot be opened: {}",
    # accès à distance
    "Opérateur distant connecté depuis {}": "Remote operator connected from {}", "En attente de connexion sur le port {}": "Waiting for a connection on port {}",
    "Opérateur distant {} déconnecté": "Remote operator {} disconnected", "Accès distant refusé à {} (mot de passe)": "Remote access refused to {} (password)",
    "Impossible : {}": "Not possible: {}", "Audio distant indisponible : {}": "Remote audio unavailable: {}",
    "{} opérateur(s) distant(s) connecté(s)": "{} remote operator(s) connected",
}
