Nouveautés de la 0.28.6 (décodeur CW bien plus performant) :
- Le décodeur CW a été refait. Sur un banc d'essai de 28 situations (vitesses de 12 à 36 mots/min, bruit, QSB, signal voisin, Farnsworth, manipulation à la main, dérive), le taux d'erreur passe de 72 % à 21 %.
- Signaux faibles : un signal à peine audible dans le bruit (−8 dB dans 2,5 kHz) passe de 85 à 90 % d'erreurs à 6 à 15 % (de 12 à 20 mots/min).
- QSB : un signal qui s'enfonce de 15 dB reste lu (de 46 % à 1 % d'erreurs avec un bon signal).
- Farnsworth et manipulation à la main : les espaces entre lettres et entre mots s'apprennent tout seuls.
- Un signal voisin à 120 Hz ne fait plus perdre la station suivie ; la dérive de la note est suivie.
- Vitesse affichée plus juste.
- Le texte s'affiche avec environ une seconde de retard : le décodeur attend la suite pour trancher entre « point » et « parasite ».
