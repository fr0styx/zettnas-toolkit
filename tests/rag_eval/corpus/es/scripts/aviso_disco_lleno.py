# Envía un aviso por Telegram si el disco del NAS supera el 90 %
import shutil
import urllib.parse
import urllib.request

TOKEN = open("/config/telegram_token").read().strip()
CHAT = "123456789"
uso = shutil.disk_usage("/mnt/user")
porcentaje = uso.used / uso.total * 100

if porcentaje > 90:
    texto = f"El NAS está al {porcentaje:.0f} %, borra algo o añade un disco"
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT}&text={urllib.parse.quote(texto)}"
    urllib.request.urlopen(url, timeout=10)
