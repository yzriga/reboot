import subprocess
import pytesseract
import numpy as np
import logging
import cv2
import sys
import time
import os
import zap_functions

home_path = os.path.expanduser("~")
save_path = os.path.join(home_path, "results/")
expected_kpi = 90.00
reference_image_path = "ref.png"
focus_region = (86, 44, 186, 158)  # (x1, y1, x2, y2)


def stop_all(capture_hdmi, file, process_ffmpeg, log_f):
    file.close()
    process_ffmpeg.stdin.close()
    process_ffmpeg.wait()
    log_f.close()
    capture_hdmi.release()
    logging.info("déconnexion réussie")


def create_repository(ip, save_path):
    path = save_path + zap_functions.get_device_model(ip) + "/KPI/" + zap_functions.get_os_version(ip) + "/reboot/"
    os.makedirs(path, exist_ok=True)
    return path


def setup_capture_hdmi(hdmi_path):
    capture_hdmi = cv2.VideoCapture(hdmi_path)
    if not capture_hdmi.isOpened():
        logging.error("erreur lors de la lecture du flux HDMI")
        exit(1)
    return capture_hdmi


def write_reboot_time(file, filepath, reboot_time_taken):
    if reboot_time_taken == 0:
        file.write(filepath + ", \n")
    else:
        file.write(filepath + ', ' + str(reboot_time_taken) + "\n")


def reboot_box(ip):
    logging.info("redémarrage de la box en cours...")
    subprocess.run(["adb", "-s", ip, "reboot"], check=True)


def reboot_routine(ip, capture_hdmi, log_dir):
    path = create_repository(ip, save_path)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"reboot_{timestamp}.mp4"

    file_path = os.path.join(path, "results.txt")
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            f.write("Exemple, " + str(expected_kpi) + "\n")

    file = open(file_path, "a")
    log_file = os.path.join(log_dir, "log.txt")
    log_f = open(log_file, 'a')

    reboot_box(ip)

    logging.info("lancement de la capture vidéo HDMI...")
    process_ffmpeg = zap_functions.setup_ffmpeg(int(capture_hdmi.get(3)), int(capture_hdmi.get(4)), 30, path + filename)

    reboot_time = manage_reboot_video(capture_hdmi, process_ffmpeg, log_f)
    write_reboot_time(file, path + filename, reboot_time)
    stop_all(capture_hdmi, file, process_ffmpeg, log_f)


def compare_images(frame, template_path, threshold=0.1):
    try:
        ref_image = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if ref_image is None:
            logging.error("Template image non trouvée !")
            return False

        grayscale_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = focus_region
        cropped_frame = grayscale_frame[y1-10:y2+10, x1-10:x2+10]

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


def manage_reboot_video(capture_hdmi, process_ffmpeg, log_f):
    detect_stream.active = False
    detect_stream.frames_after_detection = 0
    compteur_frames_noires = 0
    est_noir = False

    logging.info("attente de l'apparition du logo...")
    reboot_start_time = time.time()

    time.sleep(60)
    logging.info("⏳ Détection du logo en cours...")
    timeout = 180
    start_detection = time.time()

    while time.time() - start_detection < timeout:
        ret, frame = capture_hdmi.read()
        if not ret or frame is None:
            continue

        if compare_images(frame, reference_image_path):
            logging.info("✅ Logo détecté !")
            break
        time.sleep(1)
    else:
        logging.warning("🚫 Logo non détecté dans le délai imparti.")
        return 0

    logging.info("⏳ attente de 10s avant fin de la capture...")
    time.sleep(10)
    reboot_time = round(time.time() - reboot_start_time, 2)
    return reboot_time


def detect_stream(frame, first_use=False):
    height, width = frame.shape[:2]
    y1, y2 = 200, 400
    x1, x2 = 100, 600

    if y2 > height or x2 > width:
        logging.warning("zone de flux dépasse la taille de la frame")
        return False

    cropped_frame = frame[y1:y2, x1:x2]
    if cropped_frame is None or cropped_frame.size == 0:
        logging.warning("frame vide ou zone de flux invalide")
        return False

    if first_use:
        detect_stream.active = True
        detect_stream.frames_after_detection = 0
        detect_stream.last_frame = cropped_frame
        return False

    if cropped_frame.shape != detect_stream.last_frame.shape:
        detect_stream.last_frame = cropped_frame
        return False

    difference = cv2.absdiff(cropped_frame, detect_stream.last_frame)
    non_identical_pixels = np.sum(difference > 10)
    total_pixels = difference.size
    percentage_difference = (non_identical_pixels / total_pixels) * 100

    logging.debug(f"Différence détectée : {round(percentage_difference, 2)}%")

    if percentage_difference > 5:
        logging.info("💡 Mouvement détecté dans le flux.")
        return True

    detect_stream.last_frame = cropped_frame
    return False


def main(config, log_dir):
    attributes = ["IP", "hdmi"]
    if not all(hasattr(config, attr) for attr in attributes):
        logging.error("attribut manquant dans le fichier de conf")
        sys.exit(1)

    zap_functions.connect_adb(config.IP)
    detect_stream.active = False
    detect_stream.frames_after_detection = 0
    capture_hdmi = setup_capture_hdmi(config.hdmi)

    reboot_routine(config.IP, capture_hdmi, log_dir)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python zap.py <chemin_du_fichier_config> <log_dir>")
        sys.exit(1)

    config_path = sys.argv[1]
    log_dir = sys.argv[2]

    if not os.path.isfile(config_path):
        print(f"[ERREUR] Le fichier {config_path} est introuvable.")
        sys.exit(1)

    try:
        logging.debug(f"Fichier de configuration utilisé : {config_path}")
        logging.debug(f"Enregistrement des logs dans {log_dir}")
        config = zap_functions.load_config(config_path)
    except Exception as e:
        print(f"[ERREUR] Impossible de charger la configuration : {e}")
        sys.exit(1)

    main(config, log_dir)
