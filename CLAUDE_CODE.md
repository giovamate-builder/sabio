# Instrucciones para Claude Code

Pegale esto a Claude Code abierto en esta carpeta:

---
Este es el proyecto SABIO (FastAPI + widget JS). Leé README.md y DEPLOY.md. Quiero publicarlo en Render
con el plan gratuito:
1. Corré `pip install -r requirements.txt` y `pytest -q` para confirmar que todo pasa.
2. Inicializá git, creá un repositorio privado en mi GitHub llamado `sabio` con `gh repo create` y subí el código
   (no subas la carpeta data/ ni archivos .env).
3. Guiame paso a paso para crear el servicio en Render con New › Blueprint usando render.yaml, y decime qué
   variables cargar (SABIO_ADMIN_TOKEN con una clave que generes vos, y ANTHROPIC_API_KEY si tengo una).
4. Cuando tenga la URL, verificá con curl que `/api/health` responda y que `/api/chat` conteste
   "me das la receta de la chocotorta" con estado fuera_de_alcance en demo-tecnosur y respondida en demo-dulcepilar.
5. Dame la URL final y la línea de instalación del widget para pegar en otro sitio.
---
