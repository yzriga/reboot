import cv2
import time
import os
import numpy as np
import subprocess
import sys
import importlib.util
import logging
from ..zap_ayanleh.zap_functions import get_os_version, get_device_model, load_config

# Paramètres
max_wait_time = 180  # Timeout max pour éviter boucle infinie
result_base_dir = "/home/bytel/IVS/results/"  # Chemin de stockage des résultats
reference_image_path = "/home/bytel/IVS/function/reboot/ref.png"  # Image de référence du menu
focus_region = (77, 36, 177, 136)  # (x1, y1, x2, y2) : zone d'intérêt pour la détection
expected_kpi = 90.00

def compare_images(frame, template):
    """ Compare une image extraite de la vidéo avec le template du logo. """
    threshold = 0.5
    try:
        ref_image = cv2.imread(template, cv2.IMREAD_GRAYSCALE)
        if ref_image is None:
            logging.error("Template image non trouvée !")
            return False

        grayscale_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = focus_region
        cropped_frame = grayscale_frame[y1:y2, x1:x2]

        # Log des dimensions
        logging.debug(f"Dimensions ROI: {cropped_frame.shape}, Dimensions Template: {ref_image.shape}")

        if cropped_frame.shape[0] < ref_image.shape[0] or cropped_frame.shape[1] < ref_image.shape[1]:
            logging.error("La ROI est plus petite que le template !")
            return False

        res = cv2.matchTemplate(cropped_frame, ref_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        logging.debug(f"Similarité détectée : {max_val:.2f}")
        return max_val >= threshold
    except Exception as e:
        logging.error(f"Erreur lors de la comparaison : {e}")
        return False

def detect_logo_in_video(video_path):
    """ Détecte le logo dans une vidéo finalisée """
    if not os.path.exists(video_path):
        logging.error(f"Fichier vidéo introuvable : {video_path}")
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logging.error(f"Impossible d'ouvrir la vidéo {video_path}")
        return None

    # Afficher les dimensions de la vidéo
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    logging.debug(f"Dimensions de la vidéo : {width}x{height}")

    frame_count = 0
    logo_time = None
    start_time = time.time()
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % 10 == 0:
            if compare_images(frame, reference_image_path):
                logo_time = time.time() - start_time
                break
        frame_count += 1

    cap.release()
    return logo_time

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

def measure_boot_time(ip, log_dir, video_source):
    os_version = get_os_version(ip)
    device_model = get_device_model(ip)
    base_dir = os.path.join(result_base_dir, f"{device_model}/KPI/{os_version}/reboot")
    os.makedirs(base_dir, exist_ok=True)
    result_file = os.path.join(base_dir, "results.txt")
    timestamp = int(time.time())
    video_filename = os.path.join(base_dir, f"capture_{timestamp}.mp4")
    
    # Écrire l'entête avec la valeur par défaut 90.00
    if not os.path.exists(result_file):
        with open(result_file, 'w') as f:
            f.write(f"KPI,{expected_kpi}\n")

    # Étape 1: Enregistrement vidéo
    logging.debug("Démarrage de l'enregistrement vidéo...")
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-f', 'v4l2', '-framerate', '30',
        '-video_size', '1920x1080', '-i', video_source,
        '-c:v', 'libx264', '-preset', 'ultrafast', video_filename
    ]
    ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Étape 2: Redémarrage
    logging.debug("Redémarrage de la box...")
    subprocess.run(["adb", "-s", f"{ip}:5555", "reboot"])
    time.sleep(5)

    reboot_time = wait_for_device(ip)
    if reboot_time is None:
        logging.error("La box ne s'est pas reconnectée.")
        ffmpeg_process.terminate()
        return
    
    # Étape 3: Arrêt propre de FFmpeg
    logging.debug("Finalisation de l'enregistrement vidéo...")
    ffmpeg_process.terminate()
    ffmpeg_process.wait()
    time.sleep(2)
    
    # Étape 4: Détection du logo
    logging.debug("Détection du logo...")
    logo_time = detect_logo_in_video(video_filename)
    
    # Gestion des résultats
    if logo_time is not None:
        logging.debug(f"Logo détecté après {logo_time:.2f}s, ajout de 20s de capture supplémentaire...")
        time.sleep(20)  # Attendre 20 secondes avant d'arrêter la capture
    else:
        logging.debug("Logo non détecté")
    
    with open(result_file, 'a') as f:
        f.write(f"{video_filename},{reboot_time:.2f}\n")

    logging.debug("Test terminé.")
    logging.debug(f"Résultats enregistrés dans : {result_file}")

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
    
    try:
        config = load_config(config_path)
    except Exception as e:
        logging.error(f"[ERREUR] Impossible de charger la configuration : {e}")
        sys.exit(1)
    
    main(config, log_dir)
