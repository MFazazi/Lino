# Préparation de la distribution publique

Le nettoyage a été effectué sur une copie. Le dossier original n'a pas été modifié.
Cette archive ne contient pas d'historique Git.

## Éléments exclus

- `.env`, identifiants et jetons OAuth Google.
- Événements, diagnostics, verrous et autres données de `.runtime`.
- Hooks personnels et sauvegarde ; chemins reconstruits lors de l'installation.
- Dépendances installées : `node_modules` et `.venv`.
- Compilations desktop/Android, caches Gradle/Python et fichiers TypeScript incrémentaux.
- Paramètres IDE et Android `local.properties`.
- Ancienne image `lino-mascot.png`, sans référence dans l'application.
- Trois fichiers du thème Compose d'exemple inutilisé : l'activité utilise directement MaterialTheme.
- Dépendance Python `pyttsx3`, non importée ; le code utilise Edge TTS et SAPI.

Les trois feuilles de style sont conservées car elles sont importées et participent
à la cascade. Les fonctionnalités, tests et fichiers de verrouillage sont conservés.
Aucun fichier n'a été retiré uniquement parce qu'il est ancien.

## Adaptations

- Téléchargements dans un dossier calculé depuis le profil utilisateur.
- Core limité à la boucle locale par défaut ; accès Android explicitement configurable.
- URL Android via `linoCoreUrl`, sans IP personnelle.
- Génération locale des commandes de hooks.
- `.env.example` sans clé et `.gitignore` étendu.
- README détaillé et deux GIF issus des animations CSS de la mascotte.
- Nom de l'icône Google Docs corrigé dans les crédits.

## Vérifications

- TypeScript/Vite : compilation réussie avec les dépendances locales disponibles.
- Python : 70 tests réussis sur 71 ; DPAPI indisponible dans l'environnement de contrôle
  (erreur Windows 2 reproduite séparément). Aucun affaiblissement du chiffrement
  ni suppression du test n'a été effectué.
- Compilation native Tauri et Android non exécutée.
- Comparaison des fichiers livrés aux valeurs sensibles des fichiers privés exclus,
  sans inscrire ces valeurs dans les rapports.
- Recherche de formats de secrets, chemins personnels et fichiers interdits dans
  l'archive finale. Les fixtures explicitement fictives des tests sont conservées.

Un contrôle statique ne garantit pas absolument l'absence de toute donnée sensible.
L'archive ne contient que les sources et médias sélectionnés, sans données de compte,
caches ni dépendances installées.
