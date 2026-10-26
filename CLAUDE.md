# Consignes pour les évolutions de ce logiciel

À chaque nouvelle version (changement de `__version__` dans `catpilot/__init__.py`) :

1. Écrire `NOTES.md` (notes de la version publiées sur GitHub), en français simple.
2. Ajouter la même version **en tête** de `assets/manuel/nouveautes.txt`
   (`== version | AAAA-MM-JJ | titre`, puis une ligne `- …` par nouveauté).
   L'auto-test (`--selftest`, lancé par GitHub Actions) échoue si la version en cours n'y est pas en premier.
3. Mettre à jour le mode d'emploi `assets/manuel/manuel.html` (onglet « Mode d'emploi », imprimable) :
   décrire la nouvelle fonction dans le bon chapitre (un chapitre = un `<h2 id="...">`), corriger ce qui a changé.
   Le mode d'emploi décrit l'état actuel du logiciel ; l'historique reste dans nouveautes.txt.

L'utilisateur ne peut pas lancer Python : toujours livrer par GitHub Actions (exécutables Windows et Linux).
