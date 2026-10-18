Nouveautés de la 0.21.6 :
- Extinction à la fermeture : si la liaison était perdue au moment de quitter, CAT Pilot rouvre le port et envoie quand même l'ordre d'extinction au poste (avant, il ne l'envoyait pas). L'ordre est aussi répété, après un réveil du processeur CAT.
- Journal de la liaison CAT : il garde maintenant les échanges qui précèdent le tout premier silence du poste (pour trouver la commande qui le bloque), et note les tentatives d'allumage et d'extinction.
