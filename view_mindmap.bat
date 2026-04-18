@echo off
echo ======================================================
echo    Lancement de la Mindmap (Taxonomie)
echo ======================================================
echo.
echo Le serveur tourne sur http://localhost:8000
echo Gardez cette fenetre ouverte tant que vous consultez la mindmap.
echo.
start "" "http://localhost:8000/taxonomy_mindmap.html"
python -m http.server 8000
