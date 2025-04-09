import cv2
import time
import os
import numpy as np
import subprocess
import sys
import importlib.util
import logging

# Paramètres
max_wait_time = 180  # Timeout max pour éviter boucle infinie
result_base_dir = "results/"  # Chemin de stockage des résultats
reference_image_path = "ref.png"  # Image de référence du menu

def compare_images(screenshot, template):
    """ Compare un screenshot avec un template et détecte si un élément est en focus."""
    threshold = 0.98
    try:
        logging.debug("Checking if element is in focus...")
        reference_image = cv2.imread(template, cv2.IMREAD_GRAYSCALE)
        grayscale_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(grayscale_screenshot, reference_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            logging.debug("Element is in focus.")
            return True, max_loc
        logging.debug("Element is not in focus.")
        return False, None
    except Exception as e:
        logging.error(f'Erreur lors de la vérification de l\'élément en focus: {e}')
        return False, None

def get_device_model(ip):
    try:
        model_result = subprocess.run(
            ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'ro.product.model'],
            capture_output=True, text=True, timeout=30
        )
        model = model_result.stdout.strip()
        return model
    except subprocess.TimeoutExpired:
        logging.error(f"Erreur : Timeout lors de la récupération du modèle pour {ip}")
        return "unknown_model"

def get_os_version(ip):
    try:
        os_version_result = subprocess.run(
            ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'ro.build.version.incremental'],
            capture_output=True, text=True, timeout=30
        )
        os_version = os_version_result.stdout.strip()
        return os_version
    except subprocess.TimeoutExpired:
        logging.error(f"Erreur : Timeout lors de la récupération de la version pour {ip}")
        return "unknown_version"

def wait_for_device(ip, timeout=max_wait_time):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            result = subprocess.run(
                ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'sys.boot_completed'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() == "1":
                return time.time() - start_time
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5)
    return None

def capture_screenshot(ip):
    """ Capture un screenshot de l'écran de la box et l'enregistre."""
    captures_menu_path = "captures_menu/"
    device_path = f"/sdcard/menu_{ip}.png"
    local_path = captures_menu_path + "/menu_" + ip + ".png"
    logging.debug(f"Capturing screenshot to {local_path}...")
    subprocess.run(['adb', '-s', f'{ip}:5555', 'shell', 'screencap', device_path])
    subprocess.run(['adb', '-s', f'{ip}:5555', 'pull', device_path, local_path])
    return local_path

def measure_boot_time(ip, log_dir, video_source):
    os_version = get_os_version(ip)
    device_model = get_device_model(ip)
    base_dir = result_base_dir + device_model + "KPI" + os_version + "reboot"
    os.makedirs(base_dir, exist_ok=True)
    result_file = os.path.join(base_dir, "results.txt")
    timestamp = int(time.time())
    video_filename = os.path.join(base_dir, f"capture_{timestamp}.mp4")
    
    logging.debug("Démarrage de l'enregistrement vidéo avec ffmpeg...")
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-f', 'v4l2', '-framerate', '30',
        '-video_size', '1920x1080', '-i', video_source,
        '-c:v', 'libx264', '-preset', 'ultrafast', video_filename
    ]
    ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    logging.debug("Redémarrage de la box...")
    subprocess.run(["adb", "-s", f"{ip}:5555", "reboot"])
    time.sleep(5)
    reboot_time = wait_for_device(ip)
    if reboot_time is None:
        logging.debug("Abandon : La box ne s'est pas reconnectée.")
        return
    
    logging.debug("Attente de la détection du menu...")
    timeout_start = time.time()
    while time.time() - timeout_start < max_wait_time:
        screenshot_path = capture_screenshot(ip)
        current_screen = cv2.imread(screenshot_path)
        is_match, _ = compare_images(current_screen, reference_image_path)
        
        if is_match:
            logging.debug("Menu détecté, arrêt de la capture vidéo.")
            break
        time.sleep(5)
    
    ffmpeg_process.terminate()
    ffmpeg_process.wait()
    logging.debug("Enregistrement vidéo terminé.")
    
    with open(result_file, 'a') as f:
        f.write(f"{video_filename},{reboot_time:.2f}\n")
    
    logging.debug("Test terminé.")
    logging.debug(f"Résultats enregistrés dans : {result_file}")

def load_config(config_path):
    if not os.path.isfile(config_path):
        logging.error(f"[ERREUR] Le fichier de configuration {config_path} n'existe pas.")
        sys.exit(1)
    
    spec = importlib.util.spec_from_file_location("config", config_path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config

def main(config, log_dir):
    try:
        ip = config.IP
        video_source = config.hdmi 

        if not video_source:
            logging.error("[ERREUR] Aucune source vidéo définie dans le fichier de configuration.")
            sys.exit(1)

        os.makedirs(log_dir, exist_ok=True)
        measure_boot_time(ip, log_dir, video_source)
    except Exception as e:
        logging.error(f"Erreur : {e}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        logging.debug("Usage : python script_reboot.py <chemin_du_fichier_config> <log_dir>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    log_dir = sys.argv[2]
    
    if not os.path.isfile(config_path):
        logging.error(f"[ERREUR] Le fichier {config_path} est introuvable.")
        sys.exit(1)
    
    try:
        config = load_config(config_path)
    except Exception as e:
        logging.error(f"[ERREUR] Impossible de charger la configuration : {e}")
        sys.exit(1)
    
    main(config, log_dir)
