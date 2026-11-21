import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import unicodedata
import os
import sys
import math
import wave
import struct
import shutil
import tempfile
import threading
import subprocess

# ---------------- CONFIG ----------------
NIE = "Y9785209B"
FULL_NAME = "RAED KOSSRA"          # the site usually expects uppercase
PROVINCE = "Barcelona"
SEDE_KEYWORD = "CUALQUIER OFICINA"
TRAMITE_KEYWORD = "TOMA DE HUELLAS"

# Only used if the form asks for them
NATIONALITY = "SIRIA"
BIRTH_YEAR = "1973"

MAX_ATTEMPTS = 2000
WAIT_BETWEEN_ATTEMPTS = 120        # seconds; don't hammer the site
PROFILE_DIR = "/home/abdul/.cita-profile"

# Sound
SOUND_ENABLED = True
ALARM_MAX_SECONDS = 300            # alarm stops by itself after this long (or when you press Enter)
BEEP_ON_WAF_BLOCK = True           # one low beep if the site blocks you
# ----------------------------------------


class FatalError(Exception):
    """Errors that retrying will not fix."""


# ---------------- SOUND ----------------
_SOUND_DIR = tempfile.mkdtemp(prefix="cita_sound_")


def _make_tone_wav(path, freq, duration, volume=0.7, rate=44100):
    """Generate a simple sine-wave beep so we don't depend on system sound files."""
    n = int(rate * duration)
    fade = int(rate * 0.01)  # 10 ms fade in/out to avoid clicks
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade) if fade else 1.0
            sample = int(32767 * volume * env * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", sample)
        w.writeframes(bytes(frames))
    return path


ALARM_WAV = _make_tone_wav(os.path.join(_SOUND_DIR, "alarm.wav"), 1000, 0.25)
ALARM_WAV_HIGH = _make_tone_wav(os.path.join(_SOUND_DIR, "alarm_high.wav"), 1400, 0.25)
WARN_WAV = _make_tone_wav(os.path.join(_SOUND_DIR, "warn.wav"), 300, 0.6)


def play_wav(path):
    """Play a wav file on Windows, macOS or Linux. Returns True if a player ran."""
    if not SOUND_ENABLED:
        return False
    try:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
            return True
        if sys.platform == "darwin":
            subprocess.run(["afplay", path], check=True)
            return True
        players = [
            ["paplay", path],                                              # PulseAudio / PipeWire
            ["pw-play", path],                                             # PipeWire
            ["aplay", "-q", path],                                         # ALSA
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            ["play", "-q", path],                                          # SoX
        ]
        for cmd in players:
            if shutil.which(cmd[0]):
                result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.returncode == 0:
                    return True
    except Exception:
        pass
    # Last resort: terminal bell
    print("\a", end="", flush=True)
    return False


def beep_warn():
    threading.Thread(target=play_wav, args=(WARN_WAV,), daemon=True).start()


def alarm_loop(stop_event):
    """Two-tone alarm that repeats until stop_event is set or time runs out."""
    start = time.time()
    while not stop_event.is_set() and time.time() - start < ALARM_MAX_SECONDS:
        play_wav(ALARM_WAV)
        play_wav(ALARM_WAV_HIGH)
        play_wav(ALARM_WAV)
        play_wav(ALARM_WAV_HIGH)
        stop_event.wait(0.8)


def test_sound():
    print("🔊 Testing sound...")
    ok = play_wav(ALARM_WAV)
    if not ok:
        print("⚠️ No audio player found; falling back to the terminal bell. "
              "On Linux install one: sudo apt install pulseaudio-utils (paplay) or alsa-utils (aplay)")
# ---------------------------------------


def normalize(text):
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower()


def select_by_keyword(select_element, keyword, label):
    select = Select(select_element)
    for opt in select.options:
        if normalize(keyword) in normalize(opt.text):
            select.select_by_visible_text(opt.text)
            print(f"✅ {label} selected: {opt.text}")
            return True
    print(f"❌ No {label} containing '{keyword}'. Available options:")
    for opt in select.options:
        print("   -", opt.text)
    return False


def human_delay():
    time.sleep(random.uniform(1.5, 3.0))


def nuke_cookie_bar(driver):
    try:
        driver.execute_script("""
            var bar = document.getElementById('cookie-law-info-bar');
            if (bar) bar.remove();
        """)
        time.sleep(0.5)
    except Exception:
        pass


def js_click(driver, wait, by, selector):
    el = wait.until(EC.presence_of_element_located((by, selector)))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
    time.sleep(0.5)
    driver.execute_script("arguments[0].click();", el)


def check_waf_block(driver):
    src = driver.page_source.lower()
    if "rejected" in src or "support id" in src:
        print("🚫 WAF block detected!")
        if BEEP_ON_WAF_BLOCK:
            beep_warn()
        return True
    return False


def no_citas_available(driver):
    return "no hay citas disponibles" in driver.page_source.lower()


def select_tramite_by_text(driver, wait, keyword):
    sel_el = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "select[name='tramiteGrupo[0]']"))
    )
    return select_by_keyword(sel_el, keyword, "Trámite")


def fill_optional_fields(driver):
    """Handle extra fields some trámites ask for."""
    if NATIONALITY:
        els = driver.find_elements(By.ID, "txtPaisNac")
        if els:
            sel = Select(els[0])
            for opt in sel.options:
                if normalize(NATIONALITY) in normalize(opt.text):
                    sel.select_by_visible_text(opt.text)
                    print(f"✅ Nationality selected: {opt.text}")
                    human_delay()
                    break
    if BIRTH_YEAR:
        els = driver.find_elements(By.ID, "txtAnnoCitado")
        if els:
            els[0].clear()
            els[0].send_keys(BIRTH_YEAR)
            human_delay()


def run_attempt(driver, wait):
    # --- Step 1: Province ---
    driver.get("https://icp.administracionelectronica.gob.es/icpplus/index.html")
    human_delay()
    nuke_cookie_bar(driver)

    select = Select(wait.until(EC.element_to_be_clickable((By.ID, "form"))))
    human_delay()
    select.select_by_visible_text(PROVINCE)
    print(f"✅ {PROVINCE} selected!")

    human_delay()
    js_click(driver, wait, By.ID, "btnAceptar")
    print("✅ Aceptar clicked!")
    human_delay()

    if check_waf_block(driver):
        return False

    # --- Step 2: Oficina (Cualquier oficina) ---
    nuke_cookie_bar(driver)
    sede_el = wait.until(EC.element_to_be_clickable((By.ID, "sede")))
    human_delay()
    if not select_by_keyword(sede_el, SEDE_KEYWORD, "Oficina"):
        raise FatalError("Office option not found. Change SEDE_KEYWORD.")
    human_delay()

    # --- Step 3: Trámite ---
    if not select_tramite_by_text(driver, wait, TRAMITE_KEYWORD):
        raise FatalError("Trámite not available for this office. "
                         "Change SEDE_KEYWORD or TRAMITE_KEYWORD.")

    human_delay()
    nuke_cookie_bar(driver)
    js_click(driver, wait, By.ID, "btnAceptar")
    print("✅ Aceptar clicked!")
    human_delay()

    if check_waf_block(driver):
        return False

    # --- Step 4: Sin Cl@ve ---
    nuke_cookie_bar(driver)
    js_click(driver, wait, By.ID, "btnEntrar")
    print("✅ Sin Cl@ve selected!")
    human_delay()

    if check_waf_block(driver):
        return False

    # --- Step 5: Personal data ---
    nuke_cookie_bar(driver)

    nie_radio = wait.until(EC.presence_of_element_located((By.ID, "rdbTipoDocNie")))
    driver.execute_script("arguments[0].click();", nie_radio)
    human_delay()

    nie_field = wait.until(EC.presence_of_element_located((By.ID, "txtIdCitado")))
    nie_field.clear()
    nie_field.send_keys(NIE)
    human_delay()

    name_field = wait.until(EC.presence_of_element_located((By.ID, "txtDesCitado")))
    name_field.clear()
    name_field.send_keys(FULL_NAME)
    human_delay()

    fill_optional_fields(driver)

    nuke_cookie_bar(driver)
    js_click(driver, wait, By.ID, "btnEnviar")
    print("✅ Personal data submitted!")
    human_delay()

    if check_waf_block(driver):
        return False

    # --- Step 6: Solicitar Cita ---
    nuke_cookie_bar(driver)
    js_click(driver, wait, By.ID, "btnEnviar")
    print("✅ Solicitar Cita clicked!")
    human_delay()

    if check_waf_block(driver):
        return False

    # --- Check result ---
    if no_citas_available(driver):
        print("❌ No citas available yet.")
        try:
            js_click(driver, wait, By.ID, "btnSalir")
            human_delay()
        except Exception:
            pass
        return False

    print("🎉 CITA AVAILABLE! Check the browser!")
    return True


# --- Main ---
test_sound()

options = uc.ChromeOptions()
options.add_argument("--no-sandbox")
options.add_argument("--window-size=1920,1080")
options.add_argument("--ignore-certificate-errors")
options.add_argument(f"--user-data-dir={PROFILE_DIR}")

driver = uc.Chrome(options=options, version_main=157)
wait = WebDriverWait(driver, 20)

try:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n🔄 Attempt {attempt}/{MAX_ATTEMPTS}")
        try:
            if run_attempt(driver, wait):
                print("✅ CITA FOUND! Bot stopping.")
                stop_alarm = threading.Event()
                alarm_thread = threading.Thread(target=alarm_loop, args=(stop_alarm,), daemon=True)
                alarm_thread.start()
                input("🔔 ALARM RINGING - finish booking in the browser, then press Enter to stop the alarm...")
                stop_alarm.set()
                break
        except FatalError as e:
            print(f"🛑 {e}")
            beep_warn()
            break
        except Exception as e:
            print(f"⚠️ Error on attempt {attempt}: {e}")

        if attempt < MAX_ATTEMPTS:
            wait_time = WAIT_BETWEEN_ATTEMPTS + random.randint(0, 30)
            print(f"⏳ Waiting {wait_time}s before next attempt...")
            time.sleep(wait_time)

    print("\n🏁 Done.")
    input("Press Enter to close the browser...")
finally:
    driver.quit()
    shutil.rmtree(_SOUND_DIR, ignore_errors=True)